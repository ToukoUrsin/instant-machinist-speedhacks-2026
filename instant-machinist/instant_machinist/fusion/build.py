"""Assemble Fusion TypeScript scripts from the shared library plus a call."""
from __future__ import annotations

import json
from pathlib import Path

TS = Path(__file__).parent / "ts"


def script(*modules: str, call: str, **consts) -> str:
    parts = [(TS / "common.ts").read_text()]
    for name, val in consts.items():
        parts.append(f"const {name}: any = {json.dumps(val)};")
    parts += [(TS / f"{m}.ts").read_text() for m in modules]
    parts.append(f"adsk.result = JSON.stringify((() => {{ const r: any = {call}; return {{...r, log: LOG}}; }})());")
    return "\n".join(parts)
