"""Darwin sourcing agent for Instant Machinist.

CAM job spec -> what the shop is missing (stock, tools, finishing, overflow capacity, freight)
-> Darwin Search finds agents for each need -> resolve each agent's MCP endpoint -> read-only live probe
-> Claude Opus ranks the options for this job -> sourcing plan JSON + typed events.

Usage (from integrations/):
  python3 -m darwin.find_sources ../instant-machinist/parts/ftc-10/features.json
  options: --slug ftc-10  --nc path/to/program.nc  --no-probe  --no-llm
Optional DARWIN_API_KEY (Search key); without it Darwin Search runs at the anonymous limit.
Read-only by design: never calls quote/order/contact tools, never sends personal data to providers.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPONSORS = HERE.parent
sys.path.insert(0, str(HERE))
from mcp_probe import MCP  # noqa: E402

DARWIN = "https://api.darwin.so/api/v3/search"
CAP = "https://api.darwin.so/api/v2/search/capabilities/"
REGISTRY = "https://registry.modelcontextprotocol.io/v0.1/servers"
UA = "instant-machinist-darwin/0.1"
MODEL = "claude-opus-5-5"
READ_ONLY_PREFIXES = ("search_", "find_", "list_", "market_search")
T0 = time.time()


# ---------------------------------------------------------------- events
class Events:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")

    def __call__(self, step, msg, **kw):
        ev = {"t": round(time.time() - T0, 2), "ts": time.time(), "step": step, "msg": msg, "sponsor": "darwin", **kw}
        with self.path.open("a") as f:
            f.write(json.dumps(ev) + "\n")
        print(f"[{ev['t']:6.1f}s] {step:16s} {msg}", flush=True)


# ---------------------------------------------------------------- http
def http_json(url, data=None, headers=None, timeout=60):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def darwin_search(query, context=None, max_results=8, previous=None, token=None):
    body = {"query": query, "maxResults": max_results}
    if context:
        body["context"] = [{"type": "text", "text": c} for c in context]
    if previous:
        body["previousResponseId"] = previous
    h = {}
    if os.environ.get("DARWIN_API_KEY"):
        h["Authorization"] = "Bearer " + os.environ["DARWIN_API_KEY"]
    elif token:
        h["X-Search-Token"] = token
    t = time.time()
    d = http_json(DARWIN, body, h, timeout=90)
    d["_elapsed_s"] = round(time.time() - t, 2)
    return d


# ---------------------------------------------------------------- job -> needs
def load_gap(spec):
    out = subprocess.run([sys.executable, "-m", "shop.material_gap", str(spec)], cwd=SPONSORS,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def find_tools(spec, nc):
    """Tool list from the posted program header '(T1 D50. FACE MILL ...)' if one is available."""
    cands = [Path(nc)] if nc else []
    spec = Path(spec).resolve()
    for root in (spec.parent, spec.parent.parent):
        cands += sorted(root.glob("**/native/*.nc")) + sorted(root.glob("*.nc"))
    for p in cands:
        if p.is_file():
            tools = re.findall(r"^\((T\d+ D[\d.]+\.? [^)]*)\)", p.read_text(errors="ignore"), re.M)
            if tools:
                return tools, str(p)
    return [], None


def build_needs(spec_path, gap, tools, part_mass_kg=None, from_zip="90058", to_zip="94107"):
    spec = json.loads(Path(spec_path).read_text())
    text = json.dumps(spec).lower()
    part = gap.get("part") or spec.get("part_number")
    mat = gap.get("material", "6061-T6 aluminum")
    tool_txt = "; ".join(tools) if tools else "flat end mills, spot drill and twist drills for aluminum"
    qty = gap.get("qty_needed", 1)
    bx = [b - a for a, b in (spec["part_bbox"][k] for k in "xyz")] if spec.get("part_bbox") else gap["blank_mm"]
    part_kg = part_mass_kg or round(bx[0] * bx[1] * bx[2] * 0.4 * 2.7e-6, 2)  # ~40% fill of the envelope (estimate)
    blank_lb = gap["blank_mm"][0] * gap["blank_mm"][1] * gap["blank_mm"][2] * 2.7e-6 * 2.2046 * max(1, gap.get("blanks_short") or 1)
    needs = []
    if gap.get("missing"):
        needs.append({
            "id": "stock", "label": "Raw stock",
            "ask": gap["ask"],
            "queries": [f"Buy {mat} flat bar stock cut to length for a CNC machine shop",
                        "metal supplier aluminum plate and bar quote",
                        "Find industrial parts and suppliers by specification"],
            "context": [f"Job {part}: {gap['ask']}. Needed for a CNC milling job this week, ship to a US machine shop."],
            "probe_terms": ["6061 aluminum bar", "aluminium", "metal stock"],
        })
    needs.append({
        "id": "tooling", "label": "Cutting tools",
        "ask": f"Cutters for {part}: {tool_txt}",
        "queries": ["Buy carbide end mills and drills for aluminum CNC machining",
                    "Search cutting tool catalog by diameter flute length material"],
        "context": [f"Tool list from the posted CNC program: {tool_txt}. Material {mat}."],
        "probe_terms": ["end mill", "cutting tools", "drill"],
    })
    if any(k in text for k in ("anodiz", "anodis", "heat treat", "plating", "coat", "finish")):
        fin = "anodize / finish as specified on the drawing"
    else:
        fin = "optional clear anodize (Type II) after machining"
    needs.append({
        "id": "finishing", "label": "Finishing",
        "ask": f"{fin} for {gap.get('qty_needed', 1)} x {part} in {mat}",
        "queries": ["Anodizing or surface finishing service for machined aluminum parts",
                    "surface treatment heat treatment supplier", "metal finishing shop quote"],
        "context": [f"{gap.get('qty_needed', 1)} machined {mat} parts, envelope {gap.get('blank_in')} in."],
        "probe_terms": ["anodizing", "surface treatment", "heat treatment"],
    })
    needs.append({
        "id": "overflow", "label": "Overflow machining",
        "ask": f"Backup CNC capacity: quote {gap.get('qty_needed', 1)} x {part} from the STEP if our machine is booked",
        "queries": ["CNC machining quote for an aluminum part from a STEP file",
                    "contract manufacturer CNC milling job shop"],
        "context": [f"Part {part}, {mat}, general tolerance {spec.get('general_tolerance_mm', 0.1)} mm, qty {gap.get('qty_needed', 1)}."],
        "probe_terms": ["CNC milling", "machining"],
        "actions": {"estimate_part": {"description": f"CNC milled {mat} {spec.get('name', 'part').split('(')[0].strip().lower()}, {bx[0]:.0f} x {bx[1]:.0f} x {bx[2]:.0f} mm envelope, "
                                                     f"{part_kg} kg finished, 3-axis milling, +/-{spec.get('general_tolerance_mm', 0.1)} mm",
                                      "countryCode": "US", "batchQty": qty}},
    })
    needs.append({
        "id": "freight", "label": "Freight",
        "ask": f"Inbound freight for the bar stock (~{blank_lb:.1f} lb) from a metals service center to the shop",
        "queries": ["Get shipping rates for a small package of metal parts in the US", "shipping rates"],
        "context": [f"About {blank_lb:.1f} lb of aluminum bar in one box, ground shipping within the US, ZIP {from_zip} to {to_zip}."],
        "probe_terms": [],
        "a2a": {"skill_match": ("quote", "rate"), "data": {"product": f"{mat} flat bar blank, {max(1, gap.get('blanks_short') or 1)} piece(s)",
                "from_zip": from_zip, "to_zip": to_zip, "weight_lb": round(blank_lb + 0.5, 1), "length_in": round(gap["blank_in"][0] + 2),
                "width_in": round(gap["blank_in"][1] + 2), "height_in": round(gap["blank_in"][2] + 2)}},
        "actions": {"get_shipping_rates": {"from_zip": from_zip, "to_zip": to_zip, "weight": round(blank_lb + 0.5, 1), "weight_unit": "lb",
                                           "length_in": round(gap["blank_in"][0] + 2), "width_in": round(gap["blank_in"][1] + 2),
                                           "height_in": round(gap["blank_in"][2] + 2)}},
    })
    return spec, needs


# ---------------------------------------------------------------- darwin search per need
def search_need(need, ev):
    last_err = None
    for q in need["queries"]:
        for attempt in range(4):
            try:
                d = darwin_search(q, need["context"] if attempt < 3 else None)
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                ev("darwin.search_error", f"{need['label']}: Darwin returned {e.code} for \"{q[:60]}\" (try {attempt + 1})",
                   need=need["id"], query=q, http=e.code, attempt=attempt + 1)
                time.sleep(2 + 2 * attempt)
                continue
            except Exception as e:  # timeout etc.
                last_err = type(e).__name__
                continue
            r = d.get("response") or {}
            agents = r.get("agents") or []
            refined = None
            if d.get("status") == "needs_input" and r.get("question"):
                ev("darwin.question", f"Darwin asks: {r['question'][:140]}", need=need["id"], question=r["question"])
                try:  # one refinement, without giving out any personal data
                    refined = darwin_search("Only list matching agents and their tools; do not contact anyone or send anything yet.",
                                            need["context"], previous=d.get("responseId"), token=d.get("searchToken"))
                    agents = agents or ((refined.get("response") or {}).get("agents") or [])
                except Exception as e:
                    ev("darwin.search_error", f"refine failed: {e}", need=need["id"])
            ev("darwin.search", f"{need['label']}: \"{q[:70]}\" -> {d.get('status')}, {len(agents)} agents in {d['_elapsed_s']}s",
               need=need["id"], query=q, status=d.get("status"), agents=len(agents), elapsed_s=d["_elapsed_s"], searchId=d.get("searchId"))
            if agents or d.get("status") == "no_match":
                return q, d, refined, agents
            break
    return None, {"status": "error", "error": last_err}, None, []


def cap_details(cap_id, cache={}):
    if cap_id not in cache:
        try:
            cache[cap_id] = http_json(CAP + cap_id).get("capability") or {}
        except Exception:
            cache[cap_id] = {}
    return cache[cap_id]


def resolve_mcp(owner, cache={}):
    """Darwin returns no confirmed endpoint (connectionMethods=[]); resolve via the official MCP Registry."""
    site = (owner or {}).get("websiteUrl") or ""
    host = urllib.parse.urlparse(site).hostname or ""
    root = host.replace("www.", "").split(".")[0] if host else ""
    name_tok = re.split(r"[\s—\-]+", (owner or {}).get("name", ""))[0].lower()
    key = root or name_tok
    if not key:
        return None
    if key in cache:
        return cache[key]
    best = None
    for term in dict.fromkeys([root, name_tok]):
        if not term:
            continue
        try:
            d = http_json(f"{REGISTRY}?search={urllib.parse.quote(term)}&limit=20")
        except Exception:
            continue
        for x in d.get("servers", []):
            s = x.get("server", x)
            for rem in s.get("remotes") or []:
                u = rem.get("url", "")
                uh = urllib.parse.urlparse(u).hostname or ""
                if (root and root in uh) or (name_tok and name_tok in s.get("name", "").lower()):
                    best = {"registry_name": s.get("name"), "version": s.get("version"), "url": u, "transport": rem.get("type")}
        if best:
            break
    cache[key] = best
    return best


# ---------------------------------------------------------------- live read-only probe
def probe(endpoint, need, ev, cache={}):
    url = endpoint["url"]
    try:
        if url not in cache:
            m = MCP(url, timeout=30)
            info = m.initialize() or {}
            tools = m.tools()
            cache[url] = (m, info, tools)
        m, info, tools = cache[url]
    except Exception as e:
        ev("darwin.connect", f"MCP {url} unreachable: {type(e).__name__}", url=url, ok=False)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    ro = [t for t in tools if (t.get("annotations") or {}).get("readOnlyHint")]
    res = {"ok": True, "server": (info.get("serverInfo") or {}).get("name"), "tools": len(tools),
           "read_only_tools": len(ro), "write_tools": sorted(t["name"] for t in tools if t not in ro)[:8], "calls": []}
    ev("darwin.connect", f"MCP {res['server']} connected: {len(tools)} tools ({len(ro)} read-only)", url=url, ok=True,
       tools=len(tools), read_only=len(ro), need=need["id"])
    QKEYS = ("query", "q", "keywords", "search_term")

    def qkey_of(t):
        props = (t.get("inputSchema") or {}).get("properties", {})
        return next((k for k in QKEYS if k in props), None)
    search_tools = [t for t in ro if (t["name"].startswith(READ_ONLY_PREFIXES) or "search" in t["name"])
                    and t["name"] != "list_categories" and qkey_of(t)]
    pref = ("shopping_search", "search_suppliers", "search_parts", "search_products", "market_search")
    search_tools.sort(key=lambda t: next((i for i, p in enumerate(pref) if p == t["name"]), 99))
    for t in search_tools[:2]:
        props = (t.get("inputSchema") or {}).get("properties", {})
        qkey = qkey_of(t)
        for term in need["probe_terms"][:2]:
            args = {qkey: term}
            if "limit" in props:
                args["limit"] = 3
            try:
                r = m.call(t["name"], args) or {}
                txt = " ".join(c.get("text", "") for c in r.get("content") or [] if c.get("type") == "text")
                try:
                    body = json.loads(txt)
                except Exception:
                    body = {}
                items = next((body[k] for k in ("suppliers", "parts", "items", "products", "shops", "results") if isinstance(body.get(k), list)), [])
                total = body.get("total", len(items))
                names = [i.get("name") for i in items[:3] if isinstance(i, dict)]
                call = {"tool": t["name"], "args": args, "total": total, "top": names}
            except Exception as e:
                call = {"tool": t["name"], "args": args, "error": str(e)[:120]}
            res["calls"].append(call)
            ev("darwin.probe", f"{res['server']}.{t['name']}(\"{term}\") -> " + (f"{call['total']} hits" if "total" in call else call["error"][:60])
               + (f": {', '.join(n for n in call.get('top', []) if n)[:90]}" if call.get("top") else ""),
               need=need["id"], tool=t["name"], term=term, hits=call.get("total"), top=call.get("top"), error=call.get("error"))
            if call.get("total") or call.get("error"):
                break
    # need-specific non-mutating calculators (should-cost estimate, carrier rate lookup); no quote/order/contact tools
    for t in tools:
        args = (need.get("actions") or {}).get(t["name"])
        if not args:
            continue
        try:
            r = m.call(t["name"], args) or {}
            txt = " ".join(c.get("text", "") for c in r.get("content") or [] if c.get("type") == "text")
            call = {"tool": t["name"], "args": args, "result_text": txt[:3000], "is_error": bool(r.get("isError")),
                    "structured": r.get("structuredContent")}
        except Exception as e:
            call = {"tool": t["name"], "args": args, "error": str(e)[:160]}
        res["calls"].append(call)
        ev("darwin.live_call", f"{res['server']}.{t['name']} -> " + (call.get("error") or summarize(t["name"], call)),
           need=need["id"], tool=t["name"], ok=not call.get("error") and not call.get("is_error"), result=summarize(t["name"], call))
    return res


def summarize(tool, call):
    txt = call.get("result_text") or ""
    try:
        body = json.loads(txt)
    except Exception:
        body = call.get("structured") or {}
    if tool == "estimate_part":
        flat = json.dumps(body)
        p = {k: re.search(rf'"{k}[^"]*"\s*:\s*([\d.]+)', flat) for k in ("p50", "p80", "p90")}
        if p["p50"]:
            return "should-cost/unit " + ", ".join(f"{k.upper()} ${float(v.group(1)):,.2f}" for k, v in p.items() if v)
    if "shipping" in tool:
        rates = body.get("rates") if isinstance(body, dict) else None
        if isinstance(rates, list) and rates:
            def price(x):
                return float(x.get("price") or x.get("rate") or x.get("amount") or 1e9)
            best = sorted(rates, key=price)[:3]
            return f"{len(rates)} live rates; cheapest " + "; ".join(
                f"{x.get('carrier', '')} {x.get('service', '')} ${price(x):.2f}" for x in best)
    return re.sub(r"\s+", " ", txt)[:160] or "ok"


def a2a_quote(card, data, ev, need):
    """A2A message/send with a DataPart to a no-auth quote/rate skill (prices only; never checkout skills)."""
    import uuid
    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
        "role": "user", "kind": "message", "messageId": str(uuid.uuid4()), "parts": [{"kind": "data", "data": data}]}}}
    try:
        out = http_json(card["url"], body, {"A2A-Version": "1.0"}, timeout=45)
    except Exception as e:
        ev("darwin.live_call", f"A2A {card['name']} quote failed: {type(e).__name__}", need=need["id"], ok=False)
        return {"error": str(e)[:160]}
    msg = (out.get("result") or {}).get("message") or (out.get("result") or {})
    parts = msg.get("parts") or []
    text = " ".join(p.get("text", "") for p in parts if p.get("text"))
    rates = next((p["data"].get("rates") for p in parts if isinstance(p.get("data"), dict) and p["data"].get("rates")), []) or []
    best = sorted(rates, key=lambda r: r.get("amount") or 1e9)[:3]
    summ = (f"{len(rates)} live carrier rates; cheapest " + "; ".join(f"{r.get('service_label')} ${r.get('amount'):.2f} ({r.get('delivery_window') or str(r.get('delivery_days')) + 'd'})" for r in best)) if rates else text[:160]
    ev("darwin.live_call", f"A2A {card['name']}.message/send -> {summ}", need=need["id"], ok=bool(rates), protocol="A2A",
       rates=[{k: r.get(k) for k in ("service_label", "amount", "delivery_days", "delivery_estimated_date")} for r in rates])
    return {"tool": "a2a:message/send", "args": data, "result_text": text[:1500], "rates": rates, "summary": summ}


def a2a_card(site):
    """Read-only fetch of an A2A agent card (public discovery document)."""
    if not site:
        return None
    url = site if site.endswith(".json") else site.rstrip("/") + "/.well-known/agent-card.json"
    try:
        c = http_json(url, timeout=20)
        iface = c.get("url") or next((i.get("url") for i in c.get("supportedInterfaces") or [] if i.get("url")), None)
        return {"ok": True, "card_url": url, "name": c.get("name"), "url": iface,
                "skills": [s.get("name") or s.get("id") for s in c.get("skills") or []][:6],
                "skill_ids": [s.get("id") for s in c.get("skills") or []],
                "auth": list((c.get("securitySchemes") or {}).keys()) + [str(x) for x in c.get("securityRequirements") or []]}
    except Exception as e:
        return {"ok": False, "card_url": url, "error": f"{type(e).__name__}: {str(e)[:100]}"}


# ---------------------------------------------------------------- opus ranking
RAW_OUT = HERE / "tmp" / "opus_raw.txt"


def live_summary(p):
    if not p:
        return "not probed"
    if not p.get("ok"):
        return "unreachable: " + str(p.get("error"))[:80]
    calls = []
    for c in p.get("calls") or []:
        if "total" in c:
            calls.append(f"{c['tool']}({list(c['args'].values())[0]!r})={c['total']} hits {c.get('top') or ''}")
        else:
            calls.append(f"{c.get('tool')}: {(c.get('summary') or c.get('error') or re.sub(chr(92) + 's+', ' ', c.get('result_text') or ''))[:400]}")
    return {"connected": p.get("server") or p.get("name"), "tools": p.get("tools") or p.get("skills"), "calls": calls}
def rank_with_opus(job, needs, ev):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        ev("darwin.rank", "No ANTHROPIC_API_KEY; skipping Opus ranking", ok=False)
        return None
    brief = []
    for n in needs:
        brief.append({"need": n["id"], "ask": n["ask"], "darwin_status": n["darwin_status"], "darwin_question": n.get("darwin_question"),
                      "candidates": [{k: c.get(k) for k in ("capabilityId", "tool", "provider", "provider_site", "darwin_rank", "reasons",
                                                            "readiness", "canStartThread", "threadUnavailableReason", "auth", "payment",
                                                            "protocols", "mcp_endpoint")} | {"live": live_summary(c.get("probe"))} for c in n["candidates"]]})
    prompt = (
        "You are the purchasing lead of a small CNC machine shop. A CAM job just finished and these are the things the shop "
        "needs to source. Darwin (a search engine over agents) returned candidate agents per need; we resolved MCP endpoints "
        "via the official MCP Registry and ran read-only live probes (hit counts show real catalog coverage).\n\n"
        f"JOB: {json.dumps(job)}\n\nNEEDS+CANDIDATES: {json.dumps(brief)}\n\n"
        "Rank candidates per need for THIS job. Be strict and honest: a candidate whose live probe found 0 relevant hits is not "
        "a fit even if Darwin ranked it; space/defence or consumer catalogs are poor fits for commodity bar stock. "
        "Return ONLY JSON: {\"needs\":[{\"need\":str,\"pick\":capabilityId|null,\"verdict\":\"ready\"|\"usable_with_human\"|\"no_fit\","
        "\"ranked\":[{\"capabilityId\":str,\"fit\":0-10,\"why\":str(<=25 words),\"connect\":str(<=20 words),\"blocker\":str|null}],"
        "\"next_step\":str(<=25 words)}],\"headline\":str(<=20 words),\"gaps\":[str(<=25 words)]}. No markdown fences, no prose."
    )
    t = time.time()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps({
        "model": MODEL, "max_tokens": 12000, "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        ev("darwin.rank", f"Opus call failed: HTTP {e.code}", ok=False)
        return None
    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    RAW_OUT.write_text(text)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        plan = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        plan = None
    ev("darwin.rank", f"Opus ranked {sum(len(n['candidates']) for n in needs)} options in {time.time() - t:.1f}s"
       + (f": {plan.get('headline')}" if plan else " (unparseable)"), ok=bool(plan), model=MODEL,
       elapsed_s=round(time.time() - t, 1), usage=out.get("usage"))
    return plan


# ---------------------------------------------------------------- main
def trim_search(d):
    """Sanitized copy of a Darwin response for evidence (no private searchToken, no long prompts)."""
    if not d:
        return d
    d = json.loads(json.dumps(d))
    d.pop("searchToken", None)
    for a in (d.get("response") or {}).get("agents") or []:
        a.pop("connectionPrompt", None)
        er = a.get("executionRequirements") or {}
        er.pop("derivation", None)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--slug")
    ap.add_argument("--nc")
    ap.add_argument("--no-probe", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--part-mass-kg", type=float, help="finished part mass for the should-cost probe (default: envelope estimate)")
    ap.add_argument("--from-zip", default="90058", help="sample metals service-center ZIP (LA) for the rate probe")
    ap.add_argument("--to-zip", default="94107", help="sample shop ZIP (SF) for the rate probe")
    a = ap.parse_args()

    gap = load_gap(a.spec)
    slug = a.slug or re.sub(r"[^a-z0-9]+", "-", (gap.get("part") or "job").lower().replace("nist ", "")).strip("-")
    ev = Events(SPONSORS / "out" / slug / "darwin.events.jsonl")
    evid = HERE / "evidence" / slug
    (evid / "searches").mkdir(parents=True, exist_ok=True)
    tools, tools_src = find_tools(a.spec, a.nc)
    spec, needs = build_needs(a.spec, gap, tools, a.part_mass_kg, a.from_zip, a.to_zip)
    ev("darwin.start", f"{gap.get('part')}: sourcing {len(needs)} needs via Darwin "
       f"({'Search key' if os.environ.get('DARWIN_API_KEY') else 'anonymous Search'})",
       part=gap.get("part"), needs=[n["id"] for n in needs], auth="key" if os.environ.get("DARWIN_API_KEY") else "anonymous")
    ev("darwin.gap", gap["ask"] if gap.get("missing") else "No stock gap", part=gap.get("part"),
       blanks_short=gap.get("blanks_short"), blank_in=gap.get("blank_in"), material=gap.get("material"))
    if tools:
        ev("darwin.tools", f"{len(tools)} cutters from posted program", tools=tools, source=Path(tools_src).name)

    t_search = time.time()
    seen = {}
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(3) as ex:
        found = list(ex.map(lambda n: search_need(n, ev), needs))
    for n, (q, d, refined, agents) in zip(needs, found):
        n.update(darwin_query=q, darwin_status=d.get("status"), searchId=d.get("searchId"),
                 darwin_question=(d.get("response") or {}).get("question"),
                 darwin_overview=(d.get("response") or {}).get("overview"), candidates=[])
        (evid / "searches" / f"{n['id']}.json").write_text(json.dumps({"query": q, "context": n["context"],
                                                                        "result": trim_search(d), "refined": trim_search(refined)}, indent=1))
        for ag in agents:
            cid = ag["capabilityId"]
            cap = cap_details(cid)
            owner = cap.get("owningAi") or {}
            er = ag.get("executionRequirements") or {}
            c = {"capabilityId": cid, "agentId": ag["agentId"], "tool": ag["name"], "description": ag.get("description", "")[:240],
                 "provider": owner.get("name"), "provider_site": owner.get("websiteUrl"), "provider_verified": owner.get("verified"),
                 "darwin_rank": ag.get("rank"), "reasons": ag.get("reasons"), "uncertainties": ag.get("uncertainties"),
                 "readiness": ag.get("readiness"), "canStartThread": ag.get("canStartThread"),
                 "threadUnavailableReason": cap.get("threadUnavailableReason"),
                 "routeReason": (cap.get("routeDecision") or {}).get("reasonCode"),
                 "connectionMethods": ag.get("connectionMethods"), "protocols": cap.get("protocols"),
                 "auth": (er.get("providerAuthentication") or {}).get("state"), "payment": (er.get("payment") or {}).get("state"),
                 "runtime": (er.get("runtime") or {}).get("kind"), "agent_page": f"https://index.darwin.so/agent/{ag['agentId']}?capability={cid}"}
            dup = cid in seen
            seen.setdefault(cid, c)
            n["candidates"].append(c)
            if not dup:
                ev("darwin.agent", f"#{c['darwin_rank']} {c['tool']} — {c['provider']} [{c['readiness']}, {','.join(c['protocols'] or [])}, "
                   f"auth {str(c['auth']).lower()}, pay {str(c['payment']).lower()}]", need=n["id"], capabilityId=cid,
                   provider=c["provider"], readiness=c["readiness"], protocols=c["protocols"], canStartThread=c["canStartThread"])
    search_s = round(time.time() - t_search, 1)
    providers = {c["provider"] for c in seen.values()}
    ev("darwin.found", f"{len(seen)} capabilities from {len(providers)} providers in {search_s}s; "
       f"{sum(1 for c in seen.values() if c['canStartThread'])} thread-ready on Darwin", capabilities=len(seen),
       providers=len(providers), elapsed_s=search_s)

    # connect: resolve endpoints + live read-only probes
    probes = {}
    if not a.no_probe:
        for n in needs:
            for c in n["candidates"]:
                if "A2A" in (c["protocols"] or []) and "MCP" not in (c["protocols"] or []):
                    card = a2a_card(c["provider_site"])
                    c["probe"] = card or {"ok": False, "error": "no agent-card URL published"}
                    a2a = n.get("a2a") or {}
                    if card and card.get("ok") and card.get("url") and not card["auth"][:1] and any(
                            any(m in (sid or "") for m in a2a.get("skill_match", ())) for sid in card.get("skill_ids", [])):
                        c["probe"]["calls"] = [a2a_quote(card, a2a["data"], ev, n)]
                    ev("darwin.connect", f"A2A {c['provider']}: " + (
                        f"agent card OK ({card['name']}; skills: {', '.join(map(str, card['skills']))[:80]})" if card and card["ok"]
                        else "no reachable agent card" + (f" ({card['error'][:60]})" if card else " (Darwin lists no URL)")),
                       provider=c["provider"], protocol="A2A", ok=bool(card and card["ok"]), need=n["id"])
                    continue
                if "MCP" not in (c["protocols"] or []):
                    continue
                ep = resolve_mcp({"name": c["provider"], "websiteUrl": c["provider_site"]})
                c["mcp_endpoint"] = ep["url"] if ep else None
                if not ep:
                    ev("darwin.connect", f"{c['provider']}: no public MCP endpoint found (Darwin has none confirmed)",
                       provider=c["provider"], ok=False)
                    continue
                pk = (ep["url"], n["id"])
                if pk not in probes:
                    probes[pk] = probe(ep, n, ev)
                c["probe"] = {k: probes[pk].get(k) for k in ("ok", "server", "tools", "read_only_tools", "write_tools", "calls", "error")}
        (evid / "probes.json").write_text(json.dumps([{"endpoint": k[0], "need": k[1], **v} for k, v in probes.items()], indent=1))

    job = {"part": gap.get("part"), "material": gap.get("material"), "qty": gap.get("qty_needed"),
           "blank_in": gap.get("blank_in"), "tools": tools}
    plan = None if a.no_llm else rank_with_opus(job, needs, ev)
    total_s = round(time.time() - T0, 1)

    reachable = sorted({c["provider"] for n in needs for c in n["candidates"] if (c.get("probe") or {}).get("ok")})
    with_hits = sorted({c["provider"] for n in needs for c in n["candidates"]
                        if any((x.get("total") or 0) > 0 for x in ((c.get("probe") or {}).get("calls") or []))})
    baseline_min = {"stock": 40, "tooling": 25, "finishing": 35, "overflow": 45, "freight": 15}
    result = {
        "part": gap.get("part"), "slug": slug, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "darwin_auth": "key" if os.environ.get("DARWIN_API_KEY") else "anonymous",
        "gap": gap, "tools": tools,
        "needs": [{k: n.get(k) for k in ("id", "label", "ask", "darwin_query", "darwin_status", "darwin_question", "darwin_overview",
                                         "searchId", "candidates")} for n in needs],
        "opus_plan": plan,
        "metrics": {
            "agent_total_s": total_s, "darwin_search_s": search_s,
            "capabilities_found": len(seen), "providers_found": len(providers),
            "thread_ready_on_darwin": sum(1 for c in seen.values() if c["canStartThread"]),
            "agents_connected": len(reachable), "providers_connected": reachable,
            "providers_with_live_hits": with_hits,
            "custom_integrations_written": 0,
            "manual_baseline_min_ESTIMATE": baseline_min, "manual_baseline_total_min_ESTIMATE": sum(baseline_min[n["id"]] for n in needs),
            "baseline_note": "ESTIMATE: buyer googles 3-5 vendors per need, reads sites, fills RFQ/web forms; excludes waiting for replies.",
        },
    }
    (evid / "plan.json").write_text(json.dumps(result, indent=1))
    m = result["metrics"]
    ev("darwin.plan", f"Sourcing plan ready in {total_s}s vs ~{m['manual_baseline_total_min_ESTIMATE']} min manual (estimate); "
       f"{m['agents_connected']} live agent connections (MCP + A2A), 0 custom integrations", agent_s=total_s,
       baseline_min_estimate=m["manual_baseline_total_min_ESTIMATE"], connected=m["agents_connected"],
       plan=str((evid / "plan.json").relative_to(SPONSORS)))
    if plan:
        for p in plan.get("needs", []):
            ev("darwin.verdict", f"{p.get('need')}: {p.get('verdict')} — {p.get('next_step')}", need=p.get("need"),
               verdict=p.get("verdict"), pick=p.get("pick"))
    print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
