"""Compact data file for the Darwin video segment (rendered headlessly from HTML + this JSON).
Usage (from integrations/): python3 darwin/segment_data.py ftc-10   -> darwin/evidence/ftc-10/segment.json"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
slug = sys.argv[1] if len(sys.argv) > 1 else "ftc-10"
plan = json.loads((HERE / "evidence" / slug / "plan.json").read_text())
events = [json.loads(l) for l in (HERE.parent / "out" / slug / "darwin.events.jsonl").read_text().splitlines() if l.strip()]
op = plan.get("opus_plan") or {}
verdicts = {n["need"]: n for n in op.get("needs", [])}
m = plan["metrics"]


def best_live(cands):
    """The strongest live result for a need: a real calculator/A2A answer beats catalog hit counts."""
    for c in cands:
        for call in ((c.get("probe") or {}).get("calls") or []):
            if call.get("rates"):
                r = sorted(call["rates"], key=lambda x: x.get("amount") or 1e9)[0]
                return {"provider": c["provider"], "protocol": "A2A", "result": f"{len(call['rates'])} live carrier rates, from ${r['amount']:.2f} ({r.get('service_label')})"}
            if call.get("tool") == "estimate_part" and call.get("result_text"):
                b = json.loads(call["result_text"])
                return {"provider": c["provider"], "protocol": "MCP", "result": f"should-cost P50 ${b['p50PerUnit']:.2f}/unit (assumes {b['assumptions']['material']})"}
    for c in cands:  # most specific catalog probe (first term) = honest coverage signal
        calls = [x for x in ((c.get("probe") or {}).get("calls") or []) if "total" in x]
        if calls:
            call = calls[0]
            top = f", e.g. {', '.join(call.get('top') or [])[:50]}" if call.get("top") else ""
            return {"provider": c["provider"], "protocol": "MCP", "result": f"live search \"{list(call['args'].values())[0]}\": {call['total']} hits{top}"}
    c = cands[0] if cands else None
    if c and c.get("probe"):
        p = c["probe"]
        err = next((x.get("error") for x in p.get("calls") or [] if x.get("error")), None) or p.get("error")
        return {"provider": c["provider"], "protocol": (c.get("protocols") or ["?"])[0],
                "result": ("connected, " + err[:40]) if p.get("ok") and err else (
                    ("connected, 0 relevant hits" if p.get("calls") else f"connected ({p.get('tools')} tools), no read-only search tool to probe")
                    if p.get("ok") else "not reachable")}
    return {"provider": c["provider"] if c else None, "protocol": None, "result": "no agent found" if not c else "not probed"}


rows = []
for n in plan["needs"]:
    v = verdicts.get(n["id"], {})
    live = best_live(n["candidates"])
    rows.append({"need": n["label"], "ask": n["ask"], "darwin_found": len({c["capabilityId"] for c in n["candidates"]}),
                 "darwin_status": n["darwin_status"], "top_provider": live["provider"], "protocol": live["protocol"],
                 "live_result": live["result"], "verdict": v.get("verdict"), "next_step": v.get("next_step")})

keep = ("darwin.start", "darwin.gap", "darwin.search", "darwin.found", "darwin.connect", "darwin.live_call", "darwin.rank", "darwin.plan")
seg = {
    "part": plan["part"], "slug": slug, "generated_at": plan["generated_at"],
    "headline": op.get("headline"),
    "ask": plan["gap"]["ask"],
    "metrics": {
        "agent_seconds": m["agent_total_s"], "manual_minutes_ESTIMATE": m["manual_baseline_total_min_ESTIMATE"],
        "speedup_x_ESTIMATE": round(m["manual_baseline_total_min_ESTIMATE"] * 60 / m["agent_total_s"]),
        "needs": len(plan["needs"]), "capabilities_found": m["capabilities_found"], "providers_found": m["providers_found"],
        "live_connections": m["agents_connected"], "custom_integrations": m["custom_integrations_written"],
        "thread_ready_on_darwin": m["thread_ready_on_darwin"],
        "baseline_note": m["baseline_note"],
    },
    "rows": rows,
    "gaps": op.get("gaps", []),
    "timeline": [{"t": e["t"], "step": e["step"], "msg": e["msg"]} for e in events if e["step"] in keep][:40],
}
out = HERE / "evidence" / slug / "segment.json"
out.write_text(json.dumps(seg, indent=1))
print(out)
print(json.dumps(seg["metrics"]))
for r in rows:
    print(f"  {r['need']:20s} {r['darwin_found']} found | {str(r['top_provider'])[:30]:30s} {str(r['protocol']):4s} | {r['live_result'][:70]} | {r['verdict']}")
