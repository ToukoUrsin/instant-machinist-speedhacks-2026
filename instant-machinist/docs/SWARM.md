# Parallel simulator hardening

The simulator was hardened on build day by running many coding agents in parallel, each with one
narrow goal against the same acceptance bar: safety first, then fidelity, determinism and evidence.
Every change went through the full test suite and the FTC-10 regression gate (all five Fusion programs
must simulate without errors) before it was merged. Coordination (shared decisions, briefs, which agent
was on which work item) ran through Alike; see [integrations/alike](../../integrations/alike/).

What it added to the simulator:

- Fanuc/Haas `M98`/`M99` subprograms with recursion and call-count limits.
- `G52` local offsets and `G54.1 Pn` extended work offsets, applied to lines, arcs and canned cycles.
- Finite-material target masking, so empty space in an STL target is never reported as leftover stock.
- Tapered and bull-nose cutter geometry, Fusion tool-name aliases and inch-to-mm metadata conversion.
- Hard validation of tool metadata before simulation, and shank/holder envelope collision checks.
- Trapezoidal acceleration in the cycle-time model.
- A deterministic benchmark (`swarm/benchmark.py`): parser success rate, seeded-defect precision and
  recall, wall-clock time.

Launcher: [`swarm/launch_100_alike_swarm.py`](../swarm/launch_100_alike_swarm.py). Test suite: `make test`.
