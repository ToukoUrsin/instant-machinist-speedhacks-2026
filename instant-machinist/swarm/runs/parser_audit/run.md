# Parser audit run

- Agent: parser_audit
- Scope: implement Haas/Fanuc G52 local work-coordinate offsets in the simulator parser.
- Files: `instant_machinist/sim/gcode.py`, `tests/sim/test_gcode.py`
- Prompt: audit one contained parser dialect gap, add regression tests, and run focused plus simulator tests.
- Change: G52 offsets now translate absolute linear, arc, and canned-cycle coordinates; G52 X0 Y0 Z0 cancels specified axes. Incremental moves and G53 remain unaffected.
- Focused test: `12 passed` (`tests/sim/test_gcode.py`)
- Simulator suite: `17 passed, 1 skipped` (`tests/sim`)
- Duration: ~10 minutes (2026-10-11 UTC)
- Alike: CLI reported this machine is not paired (`npx @alikeai/setup` required), so no Alike record was available.
