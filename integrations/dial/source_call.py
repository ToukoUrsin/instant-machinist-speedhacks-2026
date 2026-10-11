"""Instant Machinist x Dial: the CAM job knows what stock it needs -> the shop's Dial agent phones suppliers for quotes.

  cd sponsors && \
      python3 dial/source_call.py ../instant-machinist/parts/ftc-10/features.json --slug ftc-10

Flow: material gap -> outbound instruction -> parallel Dial AI voice calls (shop line -> each supplier line)
-> wait for call end + transcript -> Opus extracts a structured quote -> compare quotes -> typed events + evidence.
Safety: only dials numbers owned by this Dial account and listed in dial/lines.json (demo supplier agents).
A call POST is never retried blindly (Dial calls are not idempotent).
"""
import argparse, json, math, pathlib, subprocess, sys, threading, time, re
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
SPONSORS = HERE.parent
sys.path.insert(0, str(HERE))
import dial_api as d  # noqa: E402

MODEL = "claude-opus-5-5"
T0 = time.time()
RUN_ID = time.strftime("dial-%Y%m%dT%H%M%SZ", time.gmtime(T0))
_lock = threading.Lock()


class Events:
    def __init__(self, slug):
        self.path = SPONSORS / "out" / slug / "dial.events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, step, msg, **kw):
        ev = {"t": round(time.time() - T0, 2), "ts": time.time(), "step": step, "msg": msg, "run": RUN_ID, **kw}
        with _lock:
            with self.path.open("a") as f:
                f.write(json.dumps(ev) + "\n")
            print(f"[{ev['t']:7.1f}s] {step}: {msg}", flush=True)


def material_gap(spec):
    out = subprocess.run([sys.executable, "-m", "shop.material_gap", str(spec)], cwd=SPONSORS,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def frac(x):
    """1.125 -> '1-1/8' style for the voice agent."""
    whole, rem = int(x), x - int(x)
    eighths = round(rem * 16) / 16
    names = {0: "", 1/16: "1/16", 1/8: "1/8", 3/16: "3/16", 1/4: "1/4", 5/16: "5/16", 3/8: "3/8", 7/16: "7/16",
             1/2: "1/2", 9/16: "9/16", 5/8: "5/8", 11/16: "11/16", 3/4: "3/4", 13/16: "13/16", 7/8: "7/8",
             15/16: "15/16", 1: ""}
    if eighths == 1:
        whole, eighths = whole + 1, 0
    f = names.get(eighths, f"{rem:.3f}")
    return f"{whole}-{f}" if whole and f else (str(whole) if not f else f)


def suggested(gap):
    m = re.search(r"([\d.]+) in thick x ([\d.]+) in wide flat bar, cut to ([\d.]+) in", gap.get("ask", ""))
    if m:
        return [float(v) for v in m.groups()]
    t, w, l = sorted(gap["blank_in"])
    return [t, w, l]


def mins(gap):
    return [math.ceil(v * 100 - 1e-6) / 100 for v in sorted(gap["blank_in"])]


def build_instruction(gap):
    t_min, w_min, l_min = mins(gap)
    thick, width, length = suggested(gap)
    qty = gap["blanks_short"]
    return f"""You are the purchasing assistant for a small CNC machine shop in Oakland, California, calling a metals supplier to get a quote. You speak for the shop's purchasing desk. Be polite, efficient and natural, like an experienced buyer. If asked whether you are an AI, say yes, you are the shop's AI purchasing assistant.

The job: CNC part "{gap['part']}". The shop is short {qty} blank{'s' if qty != 1 else ''} of {gap['material']}.
Minimum finished blank per piece: {t_min:.2f} in thick x {w_min:.2f} in wide x {l_min:.2f} in long (the part is machined out of this, so the stock must be at least this big in every direction).
Preferred stock: {frac(thick)} inch thick by {frac(width)} inch wide 6061-T6 flat bar, saw-cut to {frac(length)} inch lengths, quantity {qty}.

What to do:
1. Say hi, say you're calling from a machine shop for a quote on 6061-T6 aluminum flat bar.
2. Ask for the preferred size, quantity {qty}, cut to {frac(length)} inch lengths. Answer their questions from the facts above. Tolerance on the saw cut: plus or minus 1/16 inch is fine. A mill cert is nice to have but not required. Delivery to Oakland, California (or will-call pickup if delivery is expensive).
3. If they don't have the exact size, accept the nearest standard size ONLY if it is at least {t_min:.2f} in thick AND at least {w_min:.2f} in wide AND each piece at least {l_min:.2f} in long (bigger is fine, we machine it down). Prefer the smallest size that still covers the blank. A cut-to-size blank is fine too if it covers the blank. Before you agree to any size, check all three numbers out loud against these minimums; if any dimension is smaller, say so and ask for the next size up.
4. Get: price per foot or per piece, saw-cut charge, total for the order, lead time, delivery cost and date, and a quote number. Ask them to repeat the total and the quote number if unclear, and read the quote number back to confirm.
5. Do NOT place or commit to an order and do not give payment details: say you'll confirm the order by email after comparing quotes today. Then thank them and hang up.
Keep it under 3 minutes: as soon as you have the total, lead time and quote number, wrap up. Don't invent facts about the shop beyond what is written here."""


QUOTE_TOOL = {
    "name": "record_quote",
    "description": "Record the supplier quote extracted from the call transcript. Use null where the transcript does not say.",
    "input_schema": {
        "type": "object",
        "properties": {
            "supplier": {"type": "string"},
            "item": {"type": "string", "description": "alloy, temper, form and size quoted, e.g. 6061-T6 flat bar 1-1/4 x 3-1/2 in"},
            "thickness_in": {"type": ["number", "null"]},
            "width_in": {"type": ["number", "null"]},
            "piece_length_in": {"type": ["number", "null"]},
            "qty": {"type": ["integer", "null"]},
            "unit_price": {"type": ["number", "null"], "description": "USD per piece if stated or derivable, else per foot (say which in pricing_basis)"},
            "pricing_basis": {"type": ["string", "null"], "description": "per piece / per foot / per lb, with the quoted rate"},
            "cut_charge": {"type": ["number", "null"], "description": "total USD saw-cut charge for the order"},
            "delivery_charge": {"type": ["number", "null"]},
            "total": {"type": ["number", "null"], "description": "order total in USD before tax as stated by the supplier"},
            "landed_total": {"type": ["number", "null"], "description": "USD before tax to get the material delivered to the shop in Oakland: material + cuts + delivery charge (compute it from the quoted numbers if the supplier quoted will-call)"},
            "lead_days": {"type": ["number", "null"], "description": "business days until delivery/pickup"},
            "delivery": {"type": ["string", "null"], "description": "delivery or pickup terms"},
            "quote_ref": {"type": ["string", "null"]},
            "substitutions": {"type": "array", "items": {"type": "string"}, "description": "any size/material substitution vs what was asked"},
            "covers_blank": {"type": ["boolean", "null"], "description": "true if the quoted stock is at least the minimum blank in every dimension"},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "description": "0..1 confidence the extracted numbers match what was said"},
        },
        "required": ["supplier", "item", "qty", "unit_price", "cut_charge", "total", "lead_days", "delivery",
                     "quote_ref", "substitutions", "confidence"],
    },
}


def extract_quote(gap, supplier_name, call):
    import anthropic
    turns = call.get("transcriptTurns") or []
    text = "\n".join(f"{'BUYER' if t['speaker'] == 'agent' else 'SUPPLIER'}: {t['text']}" for t in turns) \
        or (call.get("transcript") or "")
    t_min, w_min, l_min = mins(gap)
    prompt = (f"A shop's AI buyer phoned {supplier_name} for a quote. Need: {gap['blanks_short']} x {gap['material']} "
              f"blanks, each at least {t_min:.2f} x {w_min:.2f} x {l_min:.2f} in.\n"
              f"Extract the supplier's quote from this call transcript. Check the arithmetic; if the supplier's stated "
              f"total disagrees with its own rates, keep the stated total and mention the mismatch in open_questions.\n\n"
              f"<transcript>\n{text}\n</transcript>")
    client = anthropic.Anthropic()
    msg = client.messages.create(model=MODEL, max_tokens=4000, tools=[QUOTE_TOOL],
                                 system="Always answer by calling the record_quote tool exactly once.",
                                 messages=[{"role": "user", "content": prompt}])
    for b in msg.content:
        if b.type == "tool_use":
            return b.input
    txt = "".join(getattr(b, "text", "") for b in msg.content)
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError("no quote extracted")


def mask(num):
    return (num[:-4] + "xxxx") if num else num


def run_supplier(ev, gap, slug, shop, line, instruction, evdir):
    name = line["persona"]
    # Hard guard: only our own Dial numbers.
    owned = {n["number"] for n in d.numbers()}
    if line["number"] not in owned or shop["number"] not in owned:
        raise SystemExit(f"refusing to dial {mask(line['number'])}: not a number on our Dial account")
    try:
        call = d.make_call(line["number"], shop["id"], instruction, max_s=300, voice="male")
    except d.DialError as e:
        # Never blind-retry: check whether the call exists anyway.
        recent = [c for c in d.list_calls() if c.get("to") == line["number"]
                  and c.get("createdAt", "") >= time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 120))]
        if not recent:
            ev.emit("call_failed", f"{name}: call not placed ({e.status})", supplier=name, http=e.status)
            return None
        call = recent[0]
    cid = call["id"]
    ev.emit("call_placed", f"Dialing {name} from the shop line", supplier=name, call_id=cid,
            from_line=shop["nickname"], to_line=line["nickname"])
    call = d.wait_call(cid, timeout_s=480, on_state=lambda st, c: ev.emit(
        "call_state", f"{name}: {st}", supplier=name, call_id=cid, state=st))
    status = call.get("status") or {}
    turns = call.get("transcriptTurns") or []
    ev.emit("call_ended", f"{name}: {status.get('label') or status.get('state')}, {call.get('duration')} s, "
            f"{len(turns)} turns", supplier=name, call_id=cid, duration_s=call.get("duration"),
            termination=status.get("terminationType"), turns=len(turns))
    meta = {k: call.get(k) for k in ("id", "direction", "status", "duration", "createdAt", "voiceRuntime",
                                      "failureReason", "transferTo", "transferredAt")}
    meta.update(from_line=shop["nickname"], from_number=mask(call.get("from")), to_line=line["nickname"],
                to_number=mask(call.get("to")), supplier=name, played_by="Dial inbound AI agent (demo persona)",
                extra_fields=sorted(set(call) - set(meta) - {"from", "to", "transcript", "transcriptTurns", "instruction"}))
    (evdir / f"{line['nickname']}.call.json").write_text(json.dumps(meta, indent=1))
    (evdir / f"{line['nickname']}.transcript.json").write_text(json.dumps(
        {"call_id": cid, "supplier": name, "note": "Both sides are Dial AI agents; supplier is a demo persona.",
         "turns": [{"speaker": "shop_agent" if t["speaker"] == "agent" else "supplier", "text": t["text"],
                    "startMs": t.get("startMs"), "endMs": t.get("endMs")} for t in turns],
         "transcript": None if turns else call.get("transcript")}, indent=1))
    for _ in range(10):  # the recording usually lands a few seconds after the call ends
        if call.get("recordingAvailable"):
            break
        time.sleep(3)
        call = d.get_call(cid)
    if call.get("recordingAvailable"):
        try:
            rec = d.download_recording(cid, str(evdir / f"{line['nickname']}.recording"))
            if rec:
                ev.emit("recording", f"{name}: call audio saved", supplier=name, call_id=cid,
                        file=pathlib.Path(rec).name)
        except Exception as e:  # audio is nice-to-have
            ev.emit("recording_failed", f"{name}: {type(e).__name__}", supplier=name, call_id=cid)
    return quote_from_call(ev, gap, name, line, call, evdir)


def quote_from_call(ev, gap, name, line, call, evdir):
    cid = call["id"]
    if not (call.get("transcriptTurns") or call.get("transcript")):
        ev.emit("quote_failed", f"{name}: no transcript", supplier=name, call_id=cid)
        return None
    q = extract_quote(gap, name, call)
    q["supplier_as_said"], q["supplier"], q["call_id"] = q.get("supplier"), name, cid
    if q.get("quote_ref"):
        m = re.search(r"\b([A-Z]{2,4})[\s-]*(\d{3,6})\b", q["quote_ref"].upper())
        q["quote_ref"] = f"{m.group(1)}-{m.group(2)}" if m else q["quote_ref"]
    (evdir / f"{line['nickname']}.quote.json").write_text(json.dumps(q, indent=1))
    ev.emit("quote", f"{name}: {q.get('item')} x{q.get('qty')} = ${q.get('total')} (${q.get('landed_total')} delivered), "
            f"{q.get('lead_days')} d, ref {q.get('quote_ref')}", supplier=name, call_id=cid,
            total=q.get("total"), landed_total=q.get("landed_total"), lead_days=q.get("lead_days"), quote_ref=q.get("quote_ref"),
            covers_blank=q.get("covers_blank"), confidence=q.get("confidence"))
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="part spec/features JSON accepted by shop.material_gap")
    ap.add_argument("--slug", help="part slug for out/<slug>/ (default: from part name)")
    ap.add_argument("--suppliers", default="im-supplier-pacific,im-supplier-bayalloy")
    ap.add_argument("--sequential", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the instruction, place no calls")
    ap.add_argument("--finalize", action="store_true",
                    help="no new calls: re-extract quotes from the saved calls of this slug (fetched from Dial by call id)")
    a = ap.parse_args()

    gap = material_gap(pathlib.Path(a.spec).resolve())
    slug = a.slug or re.sub(r"[^a-z0-9]+", "-", gap["part"].lower().replace("nist ", "")).strip("-")
    instruction = build_instruction(gap)
    if a.dry_run:
        print(instruction)
        return
    ev = Events(slug)
    if not a.finalize:
        ev.emit("gap", f"Short {gap['blanks_short']} x {gap['material']} blank(s) for {gap['part']}",
                part=gap["part"], qty=gap["blanks_short"], blank_in=gap["blank_in"])
    if not gap.get("missing"):
        ev.emit("result", "Stock on hand, no call needed", part=gap["part"])
        return
    lines = json.loads((HERE / "lines.json").read_text())
    shop = lines["shop"]
    targets = [lines[s] for s in a.suppliers.split(",")]
    evdir = HERE / "evidence" / slug
    evdir.mkdir(parents=True, exist_ok=True)
    (evdir / "gap.json").write_text(json.dumps(gap, indent=1))
    if not a.finalize:
        (evdir / "outbound_instruction.txt").write_text(instruction)
    if not a.finalize:
        ev.emit("calling", f"Shop agent calling {len(targets)} supplier(s) via Dial", suppliers=[t["persona"] for t in targets])

    if a.finalize:
        quotes = []
        for t in targets:
            meta = json.loads((evdir / f"{t['nickname']}.call.json").read_text())
            quotes.append(quote_from_call(ev, gap, t["persona"], t, d.get_call(meta["id"]), evdir))
    elif a.sequential:
        quotes = [run_supplier(ev, gap, slug, shop, t, instruction, evdir) for t in targets]
    else:
        with ThreadPoolExecutor(len(targets)) as pool:
            futs = []
            for i, t in enumerate(targets):
                futs.append(pool.submit(run_supplier, ev, gap, slug, shop, t, instruction, evdir))
                time.sleep(2)
            quotes = [f.result() for f in futs]

    quotes = [q for q in quotes if q]
    for q in quotes:
        q["compare_total"] = q.get("landed_total") if q.get("landed_total") is not None else q.get("total")
    ok = [q for q in quotes if q.get("compare_total") is not None and q.get("covers_blank") is not False]
    best = min(ok, key=lambda q: (q["compare_total"], q.get("lead_days") or 99)) if ok else None
    recs = [d.get_call(q["call_id"]) for q in quotes]
    iso = lambda x: time.mktime(time.strptime(x[:19], "%Y-%m-%dT%H:%M:%S"))
    wall = (max(iso(c["terminatedAt"]) for c in recs if c.get("terminatedAt")) -
            min(iso(c["createdAt"]) for c in recs)) if recs else None
    summary = {"part": gap["part"], "need": gap["ask"], "quotes": quotes, "best": best and {
        k: best.get(k) for k in ("supplier", "item", "total", "landed_total", "lead_days", "quote_ref", "delivery")},
        "calls_wall_clock_s": wall, "call_seconds_total": sum(c.get("duration") or 0 for c in recs),
        "elapsed_s": round(wall if wall else time.time() - T0, 1)}
    (evdir / "summary.json").write_text(json.dumps(summary, indent=1))
    if best:
        ev.emit("result", f"Best quote: {best['supplier']} ${best['compare_total']} delivered ({best.get('item')}), "
                f"{best.get('lead_days')} d, ref {best.get('quote_ref')} — {len(quotes)} quote(s) in "
                f"{summary['elapsed_s']:.0f} s", part=gap["part"], best_supplier=best["supplier"],
                best_total=best["compare_total"], best_quote_ref=best.get("quote_ref"), n_quotes=len(quotes),
                elapsed_s=summary["elapsed_s"])
    else:
        ev.emit("result", f"No usable quote ({len(quotes)} call(s) completed)", part=gap["part"], n_quotes=len(quotes))


if __name__ == "__main__":
    main()
