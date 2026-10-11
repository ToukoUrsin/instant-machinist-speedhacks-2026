"""Real numbers for the Alike video segment. Re-run any time; writes evidence/stats.json + evidence/stats.md.

Two clearly separated sources:
  ALIKE  - read live from the Alike MCP server (alike_mcp.py; read-only calls).
  LOCAL  - this box's own records (T3 Code thread turns, Claude sub-agent transcripts,
           Codex swarm run records). Labelled non-Alike; used for "agents at once".

    python3 stats.py            # since 2026-10-11 15:00 UTC (hackathon day)
Nothing here prints secrets, prompts or transcript text; only counts, times and titles.
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path("~/work/speedruninstanmachinist")
SINCE = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)
T3_DB = Path.home() / ".t3/userdata/state.sqlite"
CLAUDE_PROJECT = Path.home() / ".claude/projects/-home-ubuntu-work-speedruninstanmachinist"
SWARM_RUNS = ROOT / "instant-machinist/swarm/runs"
PDT = "PDT (UTC-7)"


def ts(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s / 1000 if s > 1e11 else s, tz=timezone.utc)
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def pdt(d):
    return (d.timestamp() - 7 * 3600) if d else None


def hhmm(d):
    return datetime.fromtimestamp(pdt(d), tz=timezone.utc).strftime("%H:%M") if d else "-"


def peak(intervals):
    """Max overlap of [start, end) intervals -> (count, time it was first reached)."""
    ev = []
    for s, e in intervals:
        if s and e and e > s:
            ev += [(s, 1), (e, -1)]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = best = 0
    when = None
    for t, d in ev:
        cur += d
        if cur > best:
            best, when = cur, t
    return best, when


# ---------------------------------------------------------------- LOCAL (non-Alike)
def local_t3_threads():
    """T3 Code threads in the speedruninstanmachinist project; a thread is 'busy' while a turn runs."""
    if not T3_DB.exists():
        return [], []
    c = sqlite3.connect(f"file:{T3_DB}?mode=ro", uri=True)
    pids = [r[0] for r in c.execute(
        "select project_id from projection_projects where workspace_root like ?", (str(ROOT) + "%",))]
    if not pids:
        return [], []
    q = ",".join("?" * len(pids))
    threads = c.execute(
        f"select thread_id, title, created_at from projection_threads where project_id in ({q}) and deleted_at is null",
        pids).fetchall()
    tids = [t[0] for t in threads]
    turns = []
    if tids:
        q2 = ",".join("?" * len(tids))
        for tid, st, done in c.execute(
                f"select thread_id, coalesce(started_at, requested_at), completed_at from projection_turns "
                f"where thread_id in ({q2})", tids):
            s = ts(st)
            if s and s >= SINCE:
                e = ts(done) or datetime.now(timezone.utc)
                turns.append((tid, s, e))
    return threads, turns


def local_claude_subagents():
    """Claude Code sub-agents spawned by hackathon threads (first..last line timestamp)."""
    out = []
    for f in CLAUDE_PROJECT.glob("*/subagents/*.jsonl"):
        first = last = None
        for line in f.open(errors="ignore"):
            try:
                t = ts(json.loads(line).get("timestamp"))
            except (ValueError, TypeError):
                continue
            if t:
                first = first or t
                last = t
        if first and last and last >= SINCE:
            out.append((f.stem, first, last))
    return out


def local_codex_swarm():
    out = []
    for f in SWARM_RUNS.glob("*/run.json"):
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        s, e = r.get("started_epoch"), r.get("ended_epoch")
        if s and e:
            out.append((r.get("agent_id", f.parent.name), ts(s), ts(e), r.get("exit_code")))
    return out


# ---------------------------------------------------------------- ALIKE (served context, local tee)
TEE = Path.home() / ".alike/injections"
ISOLATION = re.compile(r"sponsor-specific code|isolated in integrations/|read-only for sponsor", re.I)
POINTER = re.compile(r"^- (\w+) · \[([^\]]+)\] (.+?)(?: — (.*))?$")


def alike_served_moments():
    """What Alike actually put into agents' context. Alike's own hook output, recorded locally by its
    opt-in injection tee (~/.alike/injections, enabled 2026-10-11 13:39 PDT). Titles only, no prompts."""
    moments = []
    for f in TEE.glob("*.jsonl"):
        for line in f.open(errors="ignore"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            out = d.get("output")
            if not out or "coordination-pointers" not in str(out):
                continue
            try:
                ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            except (ValueError, KeyError, TypeError):
                ctx = str(out)
            pointers = []
            for pl in ctx.splitlines():
                m = POINTER.match(pl.strip())
                if m:
                    pointers.append({"badge": m.group(1), "kind": m.group(2), "title": m.group(3)[:140],
                                     "detail": (m.group(4) or "")[:200]})
            path = d.get("tool_path") or ""
            moments.append({
                "at_pdt": hhmm(ts(int(d["t"]))) if d.get("t") else "-",
                "t": d.get("t"),
                "session": (d.get("session") or "")[:15],
                "hook": d.get("mode"),
                "tool": d.get("tool"),
                "path": path.replace(str(ROOT) + "/", "") if path else None,
                "cwd": (d.get("cwd") or "").replace(str(ROOT), "<project>") or None,
                "pointers": pointers,
            })
    moments.sort(key=lambda m: m["t"] or 0)
    return moments


# ---------------------------------------------------------------- ALIKE (MCP)
def alike_numbers():
    sys.path.insert(0, str(HERE))
    from alike_mcp import Alike

    a = Alike()
    res = {}
    sessions = a.call("list_agent_sessions")
    own = sessions.get("own_sessions", [])
    res["agent_sessions_listed"] = len(own)
    res["agent_sessions_live"] = sum(1 for s in own if s.get("live"))
    res["harnesses_listed"] = dict(Counter(s.get("harness") for s in own))
    res["colleague_sessions"] = len(sessions.get("colleague_sessions", []))

    found = a.call("search_environment", {
        "query": "Instant Machinist CNC CAM simulator sponsor hackathon", "data_types": ["agent_session"],
        "limit": 20, "date_range": {"from": SINCE.isoformat(), "to": None}})
    ingested = []
    for r in found.get("results", []):
        m = r.get("metadata", {})
        ingested.append({"session_key": m.get("session_key"), "start": m.get("started_at"), "end": m.get("ended_at")})
    res["sessions_ingested_today"] = len(ingested)
    res["ingested_by_harness"] = dict(Counter((s["session_key"] or ":").split(":")[0] for s in ingested))
    res["alike_peak_concurrent_ingested"], when = peak([(ts(s["start"]), ts(s["end"])) for s in ingested])
    res["alike_peak_at_pdt"] = hhmm(when)

    an = a.call("get_my_analytics", {"days": 1})
    h = (an.get("headline") or {}).get("sinceAlike") or {}
    res["analytics"] = {
        "live_sessions": h.get("liveSessions"),
        "live_agent_hours": round(h["liveAgentHours"], 2) if h.get("liveAgentHours") is not None else None,
        "human_interventions": h.get("liveInterventions"),
        "context_injected": (an.get("contextSupplied") or {}).get("funnel", {}).get("injected"),
        "context_followed": (an.get("contextSupplied") or {}).get("funnel", {}).get("followed"),
        "agent_to_agent_messages": (an.get("a2a") or {}).get("ownAgentMessages"),
    }
    res["load_bearing"] = [
        {"title": e.get("title"), "kind": e.get("kind"), "injected": e.get("injectedCount"), "followed": e.get("followedCount")}
        for e in ((an.get("contextSupplied") or {}).get("loadBearing") or [])[:8]]

    decisions = a.call("list_entities", {"kind": "decision", "limit": 100}).get("entities", [])
    tasks = a.call("list_entities", {"kind": "task", "limit": 100}).get("entities", [])
    res["decisions"] = [{"title": (d["properties"].get("title") or d["properties"].get("name")),
                         "status": d["properties"].get("status"),
                         "origin": "extracted from agent sessions" if d.get("inference") else "recorded"}
                        for d in decisions]
    res["tasks"] = []
    overlaps = []
    for t in tasks:
        p = t["properties"]
        work = p.get("work") or []
        agents = {((w.get("agent_session") or {}).get("id") or (w.get("agent_session") or {}).get("agent_urn") or w.get("id"))
                  for w in work}
        res["tasks"].append({"title": p.get("title") or p.get("name"), "status": p.get("status"),
                             "work_sessions": len(work)})
        if len(agents) > 1:
            overlaps.append({"task": p.get("title") or p.get("name"), "sessions_on_it": len(agents)})
    res["work_items_with_multiple_agent_sessions"] = overlaps
    return res


def main():
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "window_from": SINCE.isoformat()}

    threads, turns = local_t3_threads()
    subs = local_claude_subagents()
    swarm = local_codex_swarm()
    intervals = ([(s, e) for _, s, e in turns] + [(s, e) for _, s, e in subs] + [(s, e) for _, s, e, _ in swarm])
    p_all, p_all_at = peak(intervals)
    p_thr, p_thr_at = peak([(s, e) for _, s, e in turns])
    p_sub, _ = peak([(s, e) for _, s, e in subs])
    p_sw, _ = peak([(s, e) for _, s, e, _ in swarm])
    out["local_non_alike"] = {
        "source": "this box: T3 Code state.sqlite turns, ~/.claude sub-agent transcripts, instant-machinist/swarm/runs/*/run.json",
        "t3_threads_in_project": len(threads),
        "t3_threads_active_today": len({t for t, _, _ in turns}),
        "claude_subagents_today": len(subs),
        "codex_swarm_runs": len(swarm),
        "codex_swarm_runs_ok": sum(1 for *_, rc in swarm if rc == 0),
        "peak_concurrent_agents_all": p_all,
        "peak_all_at_pdt": hhmm(p_all_at),
        "peak_concurrent_t3_threads": p_thr,
        "peak_t3_at_pdt": hhmm(p_thr_at),
        "peak_concurrent_claude_subagents": p_sub,
        "peak_concurrent_codex_swarm": p_sw,
        "total_agents_today": len({t for t, _, _ in turns}) + len(subs) + len(swarm),
    }

    try:
        out["alike"] = alike_numbers()
    except Exception as e:  # report, never invent
        out["alike"] = {"error": f"{type(e).__name__}: {e}"[:300]}

    moments = alike_served_moments()
    iso = [m for m in moments if (m["path"] or "").startswith("integrations/")
           and any(ISOLATION.search(p["title"] + " " + p["detail"]) for p in m["pointers"])]
    out["alike_served"] = {
        "source": "Alike hook output, recorded by Alike's local injection tee (~/.alike/injections) since 13:39 PDT",
        "pointer_blocks_served": len(moments),
        "sessions_served": len({m["session"] for m in moments}),
        "distinct_records_served": len({p["title"] for m in moments for p in m["pointers"]}),
        "isolation_rule_served_while_writing_in_sponsors": len(iso),
    }

    samples_file = HERE / "evidence" / "alike_live_samples.jsonl"
    samples = [json.loads(x) for x in samples_file.read_text().splitlines()] if samples_file.exists() else []
    ok = [s for s in samples if "live" in s]
    best = max(ok, key=lambda s: s["live"], default=None)
    act = [s for s in ok if "active_2m" in s]
    best_act = max(act, key=lambda s: s["active_2m"], default=None)
    out["alike_live_peak"] = {
        "source": "sample_live.py: Alike list_agent_sessions every 60 s from 13:43 PDT",
        "samples": len(ok),
        "peak_active_2m": best_act["active_2m"] if best_act else None,
        "peak_active_2m_by_harness": best_act["active_2m_by_harness"] if best_act else None,
        "peak_active_2m_at_pdt": hhmm(ts(best_act["at"])) if best_act else None,
        "peak_live_sessions": best["live"] if best else None,
        "peak_by_harness": best["by_harness"] if best else None,
        "peak_at_pdt": hhmm(ts(best["at"])) if best else None,
    }

    ev = HERE / "evidence"
    ev.mkdir(exist_ok=True)
    (ev / "stats.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    with (ev / "served_moments.jsonl").open("w") as fh:
        for m in moments:
            fh.write(json.dumps({k: v for k, v in m.items() if k != "t"}) + "\n")

    L, A = out["local_non_alike"], out["alike"]
    md = [f"# Alike segment numbers (generated {out['generated_at']}, times {PDT})", "",
          "## Agents at once (LOCAL, non-Alike data)",
          f"- Peak concurrent agents (T3 threads mid-turn + Claude sub-agents + Codex swarm workers): **{L['peak_concurrent_agents_all']}** at {L['peak_all_at_pdt']}",
          f"- Total agents today: {L['total_agents_today']} = {L['t3_threads_active_today']} T3 threads + {L['claude_subagents_today']} Claude sub-agents + {L['codex_swarm_runs']} Codex swarm runs ({L['codex_swarm_runs_ok']} exit 0)",
          f"- Peak concurrent T3 threads: {L['peak_concurrent_t3_threads']} at {L['peak_t3_at_pdt']}; sub-agents: {L['peak_concurrent_claude_subagents']}; Codex swarm: {L['peak_concurrent_codex_swarm']}",
          "", "## Agents at once (ALIKE: sessions Alike reports live, sampled every 60 s)"]
    P = out["alike_live_peak"]
    md.append(f"- Peak agent sessions with an Alike event in the same 2-minute window: **{P['peak_active_2m']}** {P['peak_active_2m_by_harness']} at {P['peak_active_2m_at_pdt']}  <- use this as 'agents at once'")
    md.append(f"- Peak sessions Alike flags 'live' (looser): {P['peak_live_sessions']} {P['peak_by_harness']} at {P['peak_at_pdt']} ({P['samples']} samples)")
    md += ["", "## What Alike recorded (ALIKE MCP, live)"]
    if "error" in A:
        md.append(f"- Alike read failed: {A['error']}")
    else:
        an = A["analytics"]
        md += [f"- Agent sessions Alike lists: {A['agent_sessions_listed']} ({A['agent_sessions_live']} live) by harness {A['harnesses_listed']}",
               f"- Sessions ingested today: {A['sessions_ingested_today']} {A['ingested_by_harness']}; peak overlap among them {A['alike_peak_concurrent_ingested']} at {A['alike_peak_at_pdt']}",
               f"- Analytics today: {an['live_sessions']} live sessions, {an['live_agent_hours']} agent-hours, {an['human_interventions']} human interventions, context injected {an['context_injected']} / followed {an['context_followed']}, agent-to-agent messages {an['agent_to_agent_messages']}",
               f"- Decisions shared: {len(A['decisions'])}"]
        md += [f"  - {d['title']} ({d['status']}, {d['origin']})" for d in A["decisions"]]
        md.append(f"- Work items: {len(A['tasks'])}; with more than one agent session on them: {len(A['work_items_with_multiple_agent_sessions'])}")
        md += [f"  - {o['task'][:110]}: {o['sessions_on_it']} sessions" for o in A["work_items_with_multiple_agent_sessions"]]
        md.append("- Load-bearing context (served, then acted on by an agent via Alike):")
        md += [f"  - {e['kind']}: {e['title'][:110]} (served {e['injected']}, followed {e['followed']})" for e in A["load_bearing"]]
    S = out["alike_served"]
    md += ["", "## What Alike put into agents' context (ALIKE hook output, local tee)",
           f"- Pointer blocks served: {S['pointer_blocks_served']} to {S['sessions_served']} sessions, {S['distinct_records_served']} distinct records",
           f"- Sponsor-isolation rule served to an agent while it wrote in integrations/: {S['isolation_rule_served_while_writing_in_sponsors']} times"]
    for m in iso[:3]:
        md.append(f"  - {m['at_pdt']} {m['session']} {m['tool']} {m['path']} <- " + "; ".join(p["title"][:70] for p in m["pointers"][:3]))
    (ev / "stats.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
