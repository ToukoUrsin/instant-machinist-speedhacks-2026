"""Build segment/data.js for segment.html + overlay.html from ../evidence (run ../stats.py first).
  cd integrations/alike && python3 stats.py && python3 segment/build_data.py
Every number shown on screen comes from evidence/stats.json (same numbers as evidence/stats.md);
the per-minute chart comes from evidence/alike_live_samples.jsonl; the moments from evidence/served_moments.jsonl.
"""
import json, pathlib, re, subprocess, datetime as dt

HERE = pathlib.Path(__file__).resolve().parent
AL = HERE.parent
EV = AL / "evidence"
S = json.loads((EV / "stats.json").read_text())
A, P, L, SV = S["alike"], S["alike_live_peak"], S["local_non_alike"], S["alike_served"]
moments = [json.loads(x) for x in (EV / "served_moments.jsonl").read_text().splitlines() if x.strip()]
PDT = dt.timedelta(hours=-7)
hhmm = lambda iso: (dt.datetime.fromisoformat(iso) + PDT).strftime("%H:%M")

# Per-minute series: agent sessions with an Alike event in the same 2-min window, by harness.
series = []
for x in (EV / "alike_live_samples.jsonl").read_text().splitlines():
    s = json.loads(x)
    if "active_2m" in s:
        h = s.get("active_2m_by_harness") or {}
        series.append({"t": hhmm(s["at"]), "codex": h.get("codex", 0), "claude": h.get("claude", 0), "n": s["active_2m"]})

# Moment 1: the sponsor-isolation rule served while an agent wrote sponsor code.
m1 = next(m for m in moments if m.get("tool") == "Write" and (m.get("path") or "").startswith("sponsors/"))
p1 = next(p for p in m1["pointers"] if "sponsor integrations" in p["title"])
rule = None
try:  # full sentence of the served (truncated) pointer, read live from the Alike task
    out = subprocess.run(["python3", str(AL / "alike_mcp.py"), "call", "search_entities",
                          json.dumps({"query": p1["title"]})], capture_output=True, text=True, timeout=60).stdout
    hit = re.search(r"Keep sponsor-specific code under sponsors/[^\"\\]*", out)
    rule = hit.group(0).strip() if hit else None
except Exception:
    pass
m1src = m1
m1 = {"at": m1["at_pdt"], "harness": "Claude Code" if m1["session"].startswith("claude") else "Codex",
      "tool": m1["tool"], "path": m1["path"], "kind": p1["kind"], "title": p1["title"],
      "rule": rule or p1["detail"],
      "others": [{"kind": p["kind"], "title": p["title"]} for p in m1src["pointers"] if p is not p1]}

# Moment 2: first Codex swarm worker tool call; Alike serves the audits other workers already finished.
m2 = next(m for m in moments if m["session"].startswith("codex") and m.get("tool"))
seen, done = set(), []
for p in m2["pointers"]:
    if p["title"].startswith("alike-") and p["title"] not in seen:
        seen.add(p["title"])
        done.append({"id": p["title"].split(":")[0], "what": p["title"].split(": ", 1)[1],
                     "status": "completed, exit 0" if "exit=0" in p["detail"] else p["kind"]})
bar = next((x for x in A["load_bearing"] if x["kind"] == "decision" and "acceptance bar" in x["title"]), None)
m2 = {"at": m2["at_pdt"], "harness": "Codex", "done": done[:4], "bar": bar}

swarm_item = max(A["work_items_with_multiple_agent_sessions"], key=lambda w: w["sessions_on_it"], default=None)
data = {
    "generated_at": hhmm(S["generated_at"]),
    "peak": {"n": P["peak_active_2m"], "by": P["peak_active_2m_by_harness"], "at": P["peak_active_2m_at_pdt"]},
    "series": series,
    "sessions_today": A["analytics"]["live_sessions"], "agent_hours": A["analytics"]["live_agent_hours"],
    "decisions": len(A["decisions"]),
    "swarm_item_sessions": swarm_item and swarm_item["sessions_on_it"],
    "pointer_blocks": SV["pointer_blocks_served"], "sessions_served": SV["sessions_served"],
    "box": {"total": L["total_agents_today"], "t3": L["t3_threads_active_today"], "sub": L["claude_subagents_today"],
            "swarm": L["codex_swarm_runs"]},
    "m1": m1, "m2": m2,
}
(HERE / "data.js").write_text("window.DATA = " + json.dumps(data, indent=1) + ";\n")
print("wrote", HERE / "data.js", data["peak"], data["sessions_today"], data["decisions"], "rule:", m1["rule"])
