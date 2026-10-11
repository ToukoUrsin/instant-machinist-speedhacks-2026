"""Job event log: every pipeline step is appended to out/<job>/events.jsonl (drives the UI and the timing report)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


class Events:
    def __init__(self, out: Path) -> None:
        self.path = Path(out) / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()

    def emit(self, step: str, msg: str, **data) -> None:
        ev = {"t": round(time.time() - self.t0, 2), "ts": time.time(), "step": step, "msg": msg, **data}
        with self.path.open("a") as f:
            f.write(json.dumps(ev) + "\n")
        print(f"[{ev['t']:7.1f}s] {step:10s} {msg}", file=sys.stderr, flush=True)
