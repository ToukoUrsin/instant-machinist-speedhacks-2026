"""Every 60 s, ask Alike which agent sessions are live (list_agent_sessions) and append one line to
evidence/alike_live_samples.jsonl: {at, live, by_harness, active_2m}.
"live" is Alike's own flag; "active_2m" = sessions with an Alike event in the last 2 minutes (stricter "at once"). Counts only. Stops at --until (UTC ISO).

    nohup python3 sample_live.py --until 2026-10-11T23:00:00Z &
"""
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from alike_mcp import Alike

OUT = Path(__file__).resolve().parent / "evidence" / "alike_live_samples.jsonl"


def main():
    until = datetime.fromisoformat(sys.argv[sys.argv.index("--until") + 1].replace("Z", "+00:00"))
    a = None
    while datetime.now(timezone.utc) < until:
        try:
            a = a or Alike()
            own = a.call("list_agent_sessions").get("own_sessions", [])
            now = datetime.now(timezone.utc)
            live = [s for s in own if s.get("live")]
            act = [s for s in own if s.get("last_event_at") and (now - datetime.fromisoformat(
                s["last_event_at"].replace("Z", "+00:00"))).total_seconds() <= 120]
            row = {"at": now.isoformat(timespec="seconds"), "live": len(live), "listed": len(own),
                   "by_harness": dict(Counter(s.get("harness") for s in live)),
                   "active_2m": len(act), "active_2m_by_harness": dict(Counter(s.get("harness") for s in act))}
        except Exception as e:  # keep sampling; record the failure honestly
            a = None
            row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": type(e).__name__}
        with OUT.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        time.sleep(60)


if __name__ == "__main__":
    main()
