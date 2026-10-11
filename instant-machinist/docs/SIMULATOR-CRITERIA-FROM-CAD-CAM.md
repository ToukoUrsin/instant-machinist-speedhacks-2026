# Simulator criteria derived from the CAD/CAM programming review

Updated 2026-10-11. This checklist translates the local CAD/CAM engine roadmap and
machinist review checklist into simulator work. The source material is used as
requirements and review guidance only; no implementation code is copied from that
repository.

The simulator's job is to verify posted three-axis milling programs: parse NC,
model stock and tools, compare the result with a target, detect unsafe motion, and
produce traceable evidence. CAM planning, post generation, setup-sheet authoring,
and 3D strategy generation remain neighboring capabilities. A criterion is marked
**measured** only when a reproducible fixture and report demonstrate it.

## M1: program and geometry verification

- [x] Linear and circular Haas/Fanuc moves, modal units, planes, feeds, spindle,
  tool changes, and canned drilling have regression coverage.
- [x] Bounded M98/M99 subprogram calls preserve source provenance and cannot recurse
  without a deterministic limit.
- [x] G52 local offsets and finite-material target masks are represented in reports.
- [x] Flat, face, ball, bull, drill, spot, chamfer, and tapered tool profiles have
  an explicit model or diagnostic path.
- [ ] Cutter compensation G41/G42/G40 and D wear offsets are geometrically applied
  and tested on inside/outside contours.
- [ ] G68/G69 rotation and G54.1 extended work-offset banks are transformed and
  reported for linear, arc, and cycle moves.
- [ ] R and IJK arc edge cases cover minor/major/full/helical and impossible arcs
  with deterministic diagnostics.
- [ ] The verifier distinguishes unsupported NC from accepted NC in a stable,
  machine-readable warning/error contract.

## M2: shop safety and machine behavior

- [x] Gouge, leftover, rapid-into-stock, flat-plunge, fixture, and flute-length
  checks emit NC line, block, tool, coordinates, and stable JSON.
- [x] Invalid and missing tool metadata is surfaced as a blocking report check.
- [ ] Holder and shank envelopes are swept with the cutter and report first contact.
- [ ] Fixture solids cover jaws, parallels, plates, clamps, and multi-setup stock
  carry instead of relying only on simplified jaw bands.
- [ ] Feeds/speeds sanity, chip load, flute count, material, spindle limits, and
  machine power are checked with explicit severity.
- [ ] Cycle time includes acceleration/deceleration, axis limits, corner blending,
  dwell, and tool changes, calibrated against Fusion estimates and published
  machine assumptions.
- [ ] Each safety check has seeded positive/negative fixtures, with precision,
  recall, false-positive examples, and documented severity.

## Machinist process review translated to simulator evidence

- [ ] Every referenced tool exists, has valid geometry, reaches the feature, and
  records diameter, flute count, stickout, holder, and flute length.
- [ ] Hole operations identify spot, drill, peck, ream, bore, tap, counterbore, and
  thread-mill intent; tool choice and cycle semantics are validated.
- [ ] Entries are helix/ramp/pre-drilled where a straight plunge is unsafe; the
  exception is explicit for drills and spot tools.
- [ ] Roughing leaves documented wall/floor stock and finishing uses the selected
  cutter compensation and tolerance band.
- [ ] Thin walls, ribs, deep features, and breakthrough moves receive deflection,
  flute-engagement, and support checks.
- [ ] Workholding records setup, grip height, locating surfaces, offset, jaw/plate
  clearance, and stock allowances.
- [ ] Sequence evidence covers face, rough, semi-finish, finish, holes, and
  chamfer/deburr, with warnings tied to operation and source line.
- [ ] Setup and assumption metadata are serialized beside the report so a
  machinist can review material, tolerances, fixtures, and intended exceptions.

## M3-M8 breadth checks

- [ ] Engagement and chip-thickness metrics are available per move, with load-spike
  thresholds and a deterministic report.
- [ ] Rest stock and adaptive linking can be checked for air-time and stay-down
  quality without changing the existing report contract.
- [ ] Browser playback exposes per-operation toolpaths, stock removal, and maps for
  every finding; frame arrays remain backward compatible.
- [ ] Posts and controller dialects have golden fixtures for Haas, Fanuc, Mazak,
  Okuma, Siemens, and Heidenhain input conventions.
- [ ] Ball/bull finishing is evaluated on mesh/3D coupons with scallop and surface
  deviation measurements.
- [ ] Drawing/PMI requirements, GD&T, tolerances, inspection points, and conflicts
  can be attached to target features and checked against the NC result.
- [ ] Multi-part, soft-jaw, fixture-plate, and batch setup metadata are checked for
  clearance and operation order.
- [ ] Physics extensions report force, torque, chatter risk, tool life, and the
  sensitivity of cycle-time optimization to assumptions.

## Evidence gate for each implementation wave

1. Convert one or more unchecked rows into a focused implementation and a
   regression fixture; keep API/report keys additive.
2. Run the full simulator suite and the deterministic generated corpus; record
   precision/recall, runtime, memory, seed, and commit under `swarm/runs/`.
3. Run all five `out/run3/fusion/*/1001.nc` programs against FTC-10 with matching
   `tools.json`; preserve every report and inspect every finding.
4. Compare behavior at 0.25, 0.125, and 0.0625 mm where stock resolution affects a
   safety result, and explain any changed verdict.
5. Merge only isolated, reviewed changes with reproducible evidence. A completed
   run means a report was produced; it does not turn a reported safety finding into
   a pass.

This checklist is the work queue for the next simulator waves. The existing
verifier already covers the core M1 path and produces useful FTC-10 evidence; the
unchecked rows define concrete engineering work for broader Fusion-compatible
verification.
