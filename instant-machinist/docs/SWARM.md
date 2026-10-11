# Simulator swarm

On 11 October 2026, the Instant Machinist simulator was reviewed by a 100-worker
GPT-6.1 Sol audit swarm. The launcher gave every worker one narrow goal, limited
concurrency to eight, and kept implementation branches isolated from the lead
checkout. Each worker resolved the shared Alike task, recorded a brief and a
result, and saved its prompt, result summary, commit, tests, and timing under
`swarm/runs/alike-001/` through `swarm/runs/alike-100/`.

The work was coordinated through Alike task
`urn:alike:task:17259fa6f12d09fb9264aa7294a492a0382776d66c392a2b92bc58b76fccf62d`.
The paired Codex and Claude hooks passed the local doctor check and telemetry was
accepted. The latest Alike analytics query shows 167 live sessions and 25 live interventions;
the shared simulator task has 165 task-context injections and 238 follows. The
reflection view records 12 helped moments, 0 noise judgments, and 68 unclear
judgments, so the run receipts remain the authoritative engineering evidence. The shared records contain the
100-goal matrix, the simulator acceptance decision, and a helped-moments document.

## What the swarm built and measured

The main branch now includes bounded Fanuc M98/M99 expansion with recursion and
call limits, G52/G54.1 work offsets, target masking for finite material, deterministic
benchmark reporting, tapered Fusion tool aliases and profiles, hard tool-metadata
diagnostics, holder/shank collision checks, and the FTC-10 flute-length crash guard.
Cycle timing now models trapezoidal feed and rapid acceleration while retaining the
report contract. The simulator contract remains additive: `simulate()` still returns
`ok`, `cycle_time.total_s`, and the existing `checks.*` keys consumed by the
pipeline and renderer. The drawing bridge adds a reviewed drawing/spec ->
`features.json` -> STEP/STL -> native G-code -> simulator path in
`instant_machinist.drawing_cam`.

Evidence is reproducible from the committed run records:

| Measure | Before the swarm | Current evidence |
|---|---:|---:|
| Simulator tests | 19 passed | 87 passed, 1 skipped after cycle, geometry, metadata, and drawing-bridge integration |
| Parser fixture success | 3/3 (1.0) | M98/M99 fixtures pass with bounded-call diagnostics |
| Seeded-defect benchmark | precision 1.0, recall 1.0 (1 TP / 0 FP / 0 FN / 2 TN) | 24 generated parts / 120 programs in an isolated candidate: precision 1.0, recall 1.0 (TP96 / FP0 / FN0 / TN24) |
| Baseline wall clock | 6.49 s including tests | Candidate corpus and per-run timings are recorded in `swarm/runs/corpus_bench/`; the real FTC-10 acceleration benchmark changed 1,586.64 s constant-feed to 1,835.34 s modeled (+15.67%) |
| FTC-10 Fusion programs | one crash in flute-length handling | all five `out/run3/fusion/*/1001.nc` programs complete and produce reports; findings are preserved in `swarm/ftc10-merge-gate-20261011.json` |

The FTC-10 gate is a safety and fidelity measurement, not a cosmetic pass flag.
Its reports identify leftover and flat-plunge findings on the adaptive programs
and those findings plus rapid-into-stock on the baseline program. The refreshed
post-cycle/drawing gate is saved in `swarm/runs/drawing_cli/ftc10-gate.json`;
keeping findings visible makes the evidence useful for the next engineering pass.

## Acceptance bar and workflow

A simulator change is ready for integration when its isolated branch includes a
focused regression test, the simulator suite, a reproducible benchmark record,
and a fresh run of every FTC-10 Fusion program with its matching `tools.json`.
A crash is a release blocker; a reported safety finding is retained with its NC
line, block, tool, and coordinates for review. Branches are rebased on the lead
branch before review, and only the lead thread merges after the full suite and
FTC-10 gate are green.

The swarm's next work is organized in [`SIMULATOR-GAP-MATRIX.md`](SIMULATOR-GAP-MATRIX.md).
It turns the historical Fusion and machinist checklists into measurable next
items while keeping the current verifier's scope and report contract explicit.
