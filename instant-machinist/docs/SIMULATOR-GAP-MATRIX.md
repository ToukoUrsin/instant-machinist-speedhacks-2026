# Simulator quality roadmap

Updated 2026-10-11. This document turns the simulator review into a measurable
sequence of next items. The simulator verifies posted NC by parsing moves,
removing stock, comparing a target, and producing deterministic safety evidence.
Fusion remains the source of posted CAM programs and 3D strategy generation; the
two systems complement each other in the demo.

## Current measured baseline

- **Parser:** Haas/Fanuc linear and arc moves, canned drilling, inch/metric units,
  G52 offsets, and bounded M98/M99 subprograms are covered by simulator tests.
- **Stock and target:** the numpy heightmap supports flat, face, ball, bull,
  drilling, and conical tool profiles used by the current fixtures. Features and
  STL targets are both supported, with finite-material masking for open regions.
- **Safety evidence:** gouge, leftover, rapid-into-stock, flat-plunge,
  fixture, and flute-length checks report stable source location and coordinates.
- **Artifacts and API:** `report.json`, `frames.npz`, and `toolpath.npz` retain the
  documented keys and coordinate convention used by the pipeline and renderer.
- **Real programs:** all five FTC-10 Fusion programs complete without a simulator
  crash. Their current findings are retained as baseline measurements: adaptive
  programs report leftover/flat-plunge findings; the baseline additionally reports
  rapid-into-stock.
- **Benchmark:** the 24-part generated corpus contains 120 labelled programs and
  records precision 1.0 and recall 1.0 (TP96, FP0, FN0, TN24). The corpus and
  manifest are deterministic by seed.

## Next acceptance items

| Area | Next item | Evidence required |
|---|---|---|
| Parser dialects | Model G41/G42 cutter compensation, G68/G69 rotation, G54.1 banks, and remaining R/IJK arc edge cases. | Golden Haas/Fanuc fixtures with transformed endpoints, source-line provenance, and explicit diagnostics for unsupported modes. |
| Subprogram coverage | Extend bounded M98/M99 tests to nested, repeated, missing-label, and recursion cases. | Deterministic call-limit and return-boundary reports. |
| Tool geometry | Add holder/shank envelopes and analytic coupons for ball, bull, chamfer, spot, drill, and taper tools. | Closed-form height references at plunge, ramp, diagonal, and boundary contact. |
| Stock resolution | Measure convergence at 0.25, 0.125, and 0.0625 mm cells. | Runtime, memory, volume, and boundary-error series with unchanged safety verdicts or a documented tolerance update. |
| Safety checks | Add feeds/speeds, chip-load, holder-clearance, and richer fixture-solid checks. | Seeded positive/negative cases with per-check confusion matrices and severity fields. |
| Cycle time | Add acceleration/deceleration and corner blending to the programmed-feed model. | Calibration fixtures against Fusion estimates and documented sensitivity to machine limits. |
| Corpus and fuzzing | Expand generated 2.5D parts and add a fixed-seed parser/property corpus. | Reproducible manifests, minimised failures, finite coordinates, no hangs, and canonical report hashes. |
| Performance | Publish median/p95 runtime and peak memory by segment count, cell size, and frame count. | Repeatable benchmark output with Python/platform metadata. |
| Compatibility | Freeze additive report-key checks and CLI exit semantics. | Pass, finding, warning, malformed-input, and missing-tool contract fixtures. |
| FTC-10 gate | Re-run every Fusion program after each simulator change. | Crash-free reports, inspected findings, and a committed gate JSON; no finding is relabelled as a pass. |

## Review checklist

1. Work in an isolated worktree and rebase on the current lead branch.
2. Add a focused regression test and run `.venv/bin/python -m pytest tests/sim -q`.
3. Run the generated benchmark and save its seed, commit, timings, and confusion
   matrix under `swarm/runs/<agent-id>/`.
4. Run every `out/run3/fusion/*/1001.nc` against `parts/ftc-10 --target auto`
   with its matching `tools.json`; preserve every report and exit code.
5. Confirm `simulate()` and the existing report keys remain backward compatible.
6. Merge only after the full suite and FTC-10 review are green.

This roadmap keeps the demo claim precise: the verifier already provides a fast,
traceable safety pass for posted programs, and each next item has an observable
acceptance test for making that verification broader and more faithful.
