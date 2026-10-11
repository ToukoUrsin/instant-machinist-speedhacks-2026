"""Summarize Sparta evidence into a results table and typed sponsor events.

    python3 sparta/tools/summarize.py            # prints the markdown table
    python3 sparta/tools/summarize.py --events   # also writes sponsors/out/<slug>/sparta.events.jsonl

Reads only sanitized evidence (evidence/*.json) and agent traces (evidence/traces/*.jsonl).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence"
SEEDED = {"in_kestrel_kd7", "in_orbital_po7781"}
ORDER = ["normal", "interruption", "crash", "crash-late", "double", "ambiguous"]


def runs_of(doc: dict) -> list[dict]:
    return doc["runs"] if "runs" in doc else [doc]


def state(run: dict) -> dict:
    s = run["snapshot"]
    created = s["diff"]["created"]
    new_inv = [i for i in s["records"]["invoices"] if i["id"] not in SEEDED]
    mission = run["missionId"]
    tid = "2" if mission.endswith("ambiguous") else "1"
    t = next(x for x in s["records"]["tickets"] if x["id"] == tid)
    replies = t["comments"][1:]
    return {
        "invoices_created": len(created.get("invoices", [])),
        "items_created": len(created.get("invoiceitems", [])),
        "draft_totals": [i["total"] for i in new_inv],
        "draft_lines": [len(i["lines"]["data"]) for i in new_inv],
        "ticket": tid, "ticket_status": t["status"], "ticket_tags": t["tags"],
        "public_replies": sum(1 for c in replies if c["public"]), "internal_notes": sum(1 for c in replies if not c["public"]),
        "failed_checks": [c["label"] for c in run["grade"]["checks"] if not c["passed"]],
        "passed": run["grade"]["passed"] and run["execution"]["status"] == "passed",
        "injected_500s": sum(1 for r in s["requests"] if r.get("injected")),
        "replayed_writes": None,
    }


def usage(name: str) -> dict:
    p = EV / "traces" / f"{name}.jsonl"
    if not p.exists():
        return {}
    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    done = [r for r in recs if r.get("kind") == "done"]
    return {
        "agent_processes": len(done),
        "input_tokens": sum(r["input_tokens"] for r in done),
        "output_tokens": sum(r["output_tokens"] for r in done),
        "model_steps": sum(r["steps"] for r in done),
        "agent_ms": sum(r["ms"] for r in done),
        "replayed_writes": sum(1 for r in recs if r.get("replayed")),
        "retried": sum(1 for r in recs if r.get("kind") == "connector" and r.get("attempt", 1) > 1),
    }


def rows():
    out = []
    for f in sorted(EV.glob("v*.json")):
        name = f.stem
        ver, rest = name.split("-", 1)
        cond = next((c for c in ["crash-late", "crash", "double", "interruption"] if c in rest), "normal")
        doc = json.loads(f.read_text())
        rs = [state(r) for r in runs_of(doc)]
        out.append({"file": f"evidence/{f.name}", "name": name, "agent": ver, "mission": runs_of(doc)[0]["missionId"], "condition": cond,
                    "runs": len(rs), "passed": sum(r["passed"] for r in rs), "states": rs, "usage": usage(name)})
    out.sort(key=lambda r: (r["mission"], ORDER.index(r["condition"]), r["agent"]))
    return out


def money(c):
    return f"${c/100:,.2f}"


def table(rs) -> str:
    lines = ["| Mission | Condition | Agent | Pass | Invoices / items created | Draft total | Ticket after run | Tokens per run (in/out) | Agent time per run | Evidence |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rs:
        s = r["states"][0]
        u = r["usage"]
        n = max(u.get("agent_processes", 0), 1)
        per_run = max(r["runs"], 1)
        tok = f"{u.get('input_tokens', 0)//per_run:,} / {u.get('output_tokens', 0)//per_run:,}" if u else "n/a"
        secs = f"{u.get('agent_ms', 0)/per_run/1000:.0f} s" if u else "n/a"
        totals = ", ".join(money(t) for t in s["draft_totals"]) or "none"
        tk = f"#{s['ticket']} {s['ticket_status']} {'+'.join(s['ticket_tags'])}, {s['public_replies']} reply" + (f", {s['internal_notes']} notes" if s["internal_notes"] else "")
        lines.append(f"| {r['mission']} | {r['condition']} | {r['agent']} | {r['passed']}/{r['runs']} | {s['invoices_created']} / {s['items_created']} | {totals} | {tk} | {tok} | {secs} | `{r['file']}` |")
    return "\n".join(lines)


def events(rs, slug="ftc-10"):
    out = ROOT.parent / "out" / slug / "sparta.events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ev = [{"t": 0.0, "ts": t0, "step": "sparta.start", "msg": "Sparta Worlds: testing the RFQ -> 50% deposit invoice agent in a local Stripe + ticket desk world",
           "sponsor": "sparta", "part": "NIST FTC-10", "world": "digital-shop", "package": "sparta_worlds@0.9.0-beta.3"}]
    for i, r in enumerate(rs, 1):
        s = r["states"][0]
        ok = r["passed"] == r["runs"]
        msg = (f"{r['agent']} {r['condition']}: {'PASS' if ok else 'FAIL'} {r['passed']}/{r['runs']}"
               + (f", draft {', '.join(money(t) for t in s['draft_totals'])}" if s["draft_totals"] else ", no invoice")
               + (f"; failed: {s['failed_checks'][0]}" if s["failed_checks"] else ""))
        ev.append({"t": float(i), "ts": t0 + i, "step": "sparta.run", "msg": msg, "sponsor": "sparta", "agent": r["agent"], "mission": r["mission"],
                   "condition": r["condition"], "runs": r["runs"], "passed": r["passed"], "invoices_created": s["invoices_created"],
                   "items_created": s["items_created"], "draft_total_cents": s["draft_totals"], "public_replies": s["public_replies"],
                   "input_tokens": r["usage"].get("input_tokens"), "agent_ms": r["usage"].get("agent_ms"), "evidence": r["file"]})
    out.write_text("".join(json.dumps(e) + "\n" for e in ev))
    return out


if __name__ == "__main__":
    rs = rows()
    print(table(rs))
    if "--events" in sys.argv:
        print("\nwrote", events(rs))


def _pname(run: dict, line: dict) -> str:
    seed = run["inputs"]["seed"]["data"]
    price = (line.get("price") or {})
    prod = price.get("product")
    return next((p["name"] for p in seed["products"] if p["id"] == prod), price.get("id"))


def _world(run: dict) -> dict:
    s = run["snapshot"]
    inv = [i for i in s["records"]["invoices"] if i["id"] not in SEEDED]
    t1 = next(x for x in s["records"]["tickets"] if x["id"] == "1")
    return {
        "invoices": [{"id": i["id"], "customer": i["customer"], "status": i["status"], "total_cents": i["total"],
                      "lines": [{"description": l["description"] or _pname(run, l), "quantity": l["quantity"], "amount_cents": l["amount"]} for l in i["lines"]["data"]]} for i in inv],
        "ticket_1": {"status": t1["status"], "tags": t1["tags"], "comments": [{"author": c["author"], "public": c["public"], "body": c["body"][:400]} for c in t1["comments"]]},
        "checks": [{"label": c["label"], "passed": c["passed"]} for c in run["grade"]["checks"]],
        "write_requests": [{"seq": r["seq"], "method": r["method"], "path": r["path"], "status": r["status"]} for r in s["requests"] if r["method"] != "GET"],
    }


def segment(rs) -> Path:
    """Exact data for the 1-minute demo segment (see SEGMENT.md)."""
    by = {r["name"]: r for r in rs}
    load = lambda n: runs_of(json.loads((EV / f"{n}.json").read_text()))
    v1d, v2d = load("v1-deposit-double")[0], load("v2-deposit-double-x3")
    t2 = [json.loads(l) for l in (EV / "traces" / "v2-deposit-double-x3.jsonl").read_text().splitlines()]
    seed = v1d["inputs"]["seed"]["data"]
    mission = next(m for m in v1d["inputs"]["missions"] if m["id"] == "ftc10-deposit")
    data = {
        "task": {"ticket_1": {k: seed["tickets"][0][k] for k in ("subject", "body", "requester")}, "mission_prompt": mission["prompt"],
                 "customers": [{k: c[k] for k in ("id", "name", "email")} for c in seed["customers"]],
                 "expected": json.loads((ROOT / "jobs" / "ftc-10.expected.json").read_text())},
        "v1_double_failure": _world(v1d),
        "v2_double_fixed_run1": _world(v2d[0]),
        "v2_double_replays": [{"delivery": r.get("delivery"), "method": r["method"], "path": r["path"], "replayed": bool(r.get("replayed"))}
                              for r in t2 if r.get("kind") == "connector" and r.get("label") == "write"][:13],
        "scoreboard": [{"agent": r["agent"], "mission": r["mission"], "condition": r["condition"], "passed": r["passed"], "runs": r["runs"],
                        "input_tokens_per_run": (r["usage"].get("input_tokens") or 0) // max(r["runs"], 1),
                        "agent_seconds_per_run": round((r["usage"].get("agent_ms") or 0) / max(r["runs"], 1) / 1000, 1), "evidence": r["file"]} for r in rs],
    }
    out = EV / "segment-data.json"
    out.write_text(json.dumps(data, indent=1) + "\n")
    return out


if __name__ == "__main__" and "--segment" in sys.argv:
    print("wrote", segment(rows()))
