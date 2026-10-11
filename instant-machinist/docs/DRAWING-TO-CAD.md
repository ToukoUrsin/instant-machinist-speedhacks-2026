# Drawing to CAD to CAM handoff

A drawing can now be treated as the first input to the native geometry path. The
vision adapter returns a typed `Spec`; `instant_machinist.drawing.spec_to_features`
validates that spec, normalizes inch dimensions to millimetres, computes a stock
and finished-part envelope, and emits the repository's `features.json` contract.
`write_feature_model` persists that model for review.

The handoff is deterministic after drawing extraction:

1. `read_drawing(PDF|PNG|JPEG|WEBP)` extracts typed dimensions, features, notes,
   and questions.
2. `validate_spec` reports missing profiles, invalid depths, bad radii, missing
   hole positions, and unsupported feature data before any solid is created.
3. `spec_to_features` produces a millimetre feature model with explicit stock,
   part bounds, tolerances, notes, and customer questions.
4. `parts.build_part.build_model` can create the CAD solid and export STEP/STL.
5. Native CAM consumes the same model and emits `1001.nc`; the simulator verifies
   that program with the existing report contract.

The lead-owned `pipeline.py` remains unchanged. Its integration seam is to call
`spec_to_features` after `read_drawing`, write `features.json` into a job-local
part directory, invoke the existing CAD builder, and then run native or Fusion
CAM. A model with unresolved questions should stay in review until the caller
resolves them; the converter never guesses a solid from incomplete geometry.

The current schema covers the supported 2.5D primitives: outside profile,
rounded-rectangle pocket, and drilled holes. Expanding to slots, counterbores,
threads, GD&T, and 3D surfaces follows the same typed-feature contract and is
tracked in `SIMULATOR-CRITERIA-FROM-CAD-CAM.md`.
