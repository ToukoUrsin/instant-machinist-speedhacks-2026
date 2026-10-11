"""Build segment/data.js from darwin/evidence/<slug>/ (segment.json + plan.json) for segment.html.
  python3 darwin/segment/build_data.py ftc-10
Every number on screen comes from these files; GAPS.md short lines are quoted as text.
"""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
slug = sys.argv[1] if len(sys.argv) > 1 else "ftc-10"
ev = HERE.parent / "evidence" / slug
seg = json.loads((ev / "segment.json").read_text())
plan = json.loads((ev / "plan.json").read_text())

rates, costable = None, None
for n in plan["needs"]:
    for c in n["candidates"]:
        for call in ((c.get("probe") or {}).get("calls") or []):
            if call.get("rates") and rates is None:
                rates = {"provider": c["provider"], "protocol": "A2A", "url": c["probe"].get("url"),
                         "from_zip": call["args"].get("from_zip"), "to_zip": call["args"].get("to_zip"),
                         "weight_lb": call["args"].get("weight_lb"), "product": call["args"].get("product"),
                         "rates": sorted(call["rates"], key=lambda r: r["amount"])}
            if call.get("tool") == "estimate_part" and call.get("result_text") and costable is None:
                b = json.loads(call["result_text"])
                costable = {"provider": c["provider"], "p50": b["p50PerUnit"], "p80": b["p80PerUnit"], "p90": b["p90PerUnit"],
                            "material": b["assumptions"]["material"], "cycle_min": b["assumptions"]["cycleTimeMins"]}

# Darwin searches (one per need) with their real timestamps from the run timeline
searches = []
for e in seg["timeline"]:
    if e["step"] == "darwin.search":
        m = re.match(r'(.+?): "(.+?)" -> (\w+), (\d+) agents in ([\d.]+)s', e["msg"])
        if m:
            searches.append({"t": e["t"], "need": m[1], "query": m[2], "status": m[3], "agents": int(m[4]), "secs": float(m[5])})
connects = []
for e in seg["timeline"]:
    if e["step"] == "darwin.connect":
        m = re.match(r"(MCP|A2A) (.+?)(?: connected: (\d+) tools| Parcel Quotes: agent card OK)", e["msg"])
        if m:
            name = m[2] + (" Parcel Quotes" if "agent card" in e["msg"] else "")
            if any(x["name"] == name for x in connects):
                continue
            connects.append({"t": e["t"], "proto": m[1], "name": name, "tools": int(m[3]) if m[3] else None,
                             "skills": "agent card OK" if "agent card" in e["msg"] else None})

m = plan["metrics"]
data = {
    "slug": slug, "part": seg["part"], "ask": seg["ask"], "metrics": seg["metrics"], "rows": seg["rows"],
    "gaps": seg["gaps"], "headline": seg["headline"], "searches": searches, "connects": connects,
    "search_total_s": m["darwin_search_s"], "baseline_by_need": m["manual_baseline_min_ESTIMATE"],
    "rates": rates, "costable": costable,
    # GAPS.md short on-screen lines (SEGMENT.md); counts are quoted from GAPS.md #1, #3, #4, #6
    "gap_lines": [
        ["Bar stock, anodizing, tooling: 0 executable agents", "Live search “6061 aluminum bar”: 0 hits",
         "Index metals service centers and MRO/tooling catalogs (MCP wrappers, WebMCP)"],
        [f"0 of {seg['metrics']['capabilities_found']} results thread-ready on Darwin",
         "Yet every endpoint we resolved answered our live calls in seconds",
         "Re-verify on demand when a result is selected"],
        ["Search returned HTTP 500 on 15 of 20 calls", "Retries and rephrasings recovered all 5 needs",
         "Return no_match or degraded results instead of a 500"],
        ["No endpoint in connectionMethods", "We resolved MCP URLs via the MCP Registry, A2A via agent cards",
         "Return {protocol, url, transport} for public no-auth servers"],
    ],
}
(HERE / "data.js").write_text("window.DATA = " + json.dumps(data) + ";\n")
print("wrote", HERE / "data.js", len(searches), "searches", len(connects), "connects", rates and len(rates["rates"]), "rates")
