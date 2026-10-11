"""Smoke tests: every pipeline module imports, the drawing spec cross-check works, and the native engine
runs drawing spec -> verified G-code end to end. No network: Anthropic and Fusion Compute are never called."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "parts" / "sm-101"
TRUTH = json.loads((PART / "features.json").read_text())

MODULES = [
    "instant_machinist.pipeline", "instant_machinist.events", "instant_machinist.drawing",
    "instant_machinist.fusion.mcp_client", "instant_machinist.fusion.session", "instant_machinist.fusion.build",
    "instant_machinist.fusion.program", "instant_machinist.fusion.strategies",
    "instant_machinist.cam.plan", "instant_machinist.cam.optimize", "instant_machinist.cam.post_haas",
    "instant_machinist.cam.feeds", "instant_machinist.cam.run",
    "instant_machinist.sim.run", "instant_machinist.sim.gcode", "instant_machinist.sim.checks",
    "instant_machinist.render.video",
]


@pytest.mark.parametrize("name", MODULES)
def test_imports(name):
    importlib.import_module(name)


def _spec(truth: dict):
    from instant_machinist.drawing import Spec
    return Spec.model_validate({**truth, "notes": [], "questions_for_customer": []})


def test_drawing_compare_matches_reference_spec():
    from instant_machinist.drawing import compare
    assert compare(_spec(TRUTH), TRUTH) == []


def test_drawing_compare_flags_a_wrong_hole():
    from instant_machinist.drawing import compare
    bad = copy.deepcopy(TRUTH)
    f6 = next(f for f in bad["features"] if f["id"] == "F6")
    f6["d"] = 8.5                      # misread diameter
    assert compare(_spec(bad), TRUTH) == ["missing or different: F6 hole"]


def test_drawing_normalize_fills_implied_hole_depths():
    from instant_machinist.drawing import compare, normalize
    read = copy.deepcopy(TRUTH)
    for f in read["features"]:
        if f["type"] == "hole":        # the drawing says "THRU" and shows the holes on the pocket floor, no Z values
            f.pop("z_top"), f.pop("z_bottom")
    spec = normalize(_spec(read))
    holes = {f.id: f for f in spec.features if f.type == "hole"}
    assert (holes["F5"].z_top, holes["F5"].z_bottom) == (0.0, -20)
    assert (holes["F6"].z_top, holes["F6"].z_bottom) == (-8, -20)
    assert compare(spec, TRUTH) == []


def test_fusion_script_assembly_injects_spec():
    from instant_machinist.fusion.build import script
    ts = script("model", call="buildPart(FEATURES)", FEATURES=TRUTH)
    assert ts.startswith("// Shared helpers")
    assert "const FEATURES: any = " in ts and '"SM-101"' in ts
    assert "function buildPart(" in ts and ts.rstrip().endswith("})());")


def test_fusion_strategies_have_a_baseline_and_variants():
    from instant_machinist.fusion.strategies import BASELINE, VARIANTS
    names = [BASELINE["name"]] + [v["name"] for v in VARIANTS]
    assert len(set(names)) == len(names) == 5
    assert all(v["rough"] == "adaptive" for v in VARIANTS) and BASELINE["rough"] == "pocket2d"


def test_mmss():
    from instant_machinist.pipeline import mmss
    assert mmss(388.46) == "6:28" and mmss(154.4) == "2:34"


def test_native_pipeline_end_to_end(tmp_path):
    from instant_machinist.pipeline import run
    s = run(PART, tmp_path / "job", engine="native", read=False, video=False)
    assert s["part"] == "SM-101" and s["engine"] == "native"
    assert s["baseline"]["pass"] and s["best"]["pass"]
    assert s["best"]["cycle_s"] < s["baseline"]["cycle_s"]
    assert 0 < s["machining_saved_pct"] < 100
    best = Path(s["best"]["dir"])
    rep = json.loads((best / "sim" / "report.json").read_text())
    assert rep["ok"] and all(v["ok"] for k, v in rep["checks"].items() if isinstance(v, dict))
    nc = (best / "1001.nc").read_text()
    assert nc.lstrip().startswith("%") and "O01001" in nc and "M30" in nc
    events = [json.loads(line)["step"] for line in (tmp_path / "job" / "events.jsonl").read_text().splitlines()]
    assert events[-1] == "done" and "result" in events


def test_op1_pass_rule_reports_leftover_but_fails_safety():
    from instant_machinist.pipeline import SAFETY, passed
    ok = {"ok": True, "count": 0}
    checks = {k: dict(ok) for k in ("gouge", "leftover", "rapid_into_stock", "flat_plunge", "below_fixture", "flute_length")}
    checks["leftover"] = {"ok": False, "count": 61, "area_mm2": 469.38}      # stock for later setups
    rep = {"ok": False, "checks": checks}
    assert not passed(rep, whole_job=True)                                     # a complete job must finish the part
    assert passed(rep, whole_job=False)                                        # an OP1 reports it as next-setup work
    assert set(SAFETY) == {"gouge", "rapid_into_stock", "below_fixture", "flute_length"}
    checks["rapid_into_stock"] = {"ok": False, "count": 6}
    assert not passed(rep, whole_job=False)                                    # safety checks always fail the program


def test_drawing_spec_exports_native_cad_feature_model(tmp_path):
    """A validated drawing spec becomes the same feature contract used by CAD/CAM."""
    from instant_machinist.drawing import spec_to_features, validate_spec, write_feature_model
    from instant_machinist.parts.build_part import build_model

    spec = _spec(TRUTH)
    assert validate_spec(spec) == []
    model = spec_to_features(spec)
    assert model["source"] == "drawing_spec"
    assert model["units"] == "mm"
    assert model["part_bbox"]["z"] == [-20.0, 0.0]
    assert len(model["features"]) == len(TRUTH["features"])
    out = tmp_path / "features.json"
    assert write_feature_model(spec, out)["part_number"] == "SM-101"
    assert json.loads(out.read_text()) == model
    # This is the actual CAD handoff: CadQuery can build a solid from the exported model.
    solid = build_model(model).val()
    assert solid.Volume() > 0


def test_drawing_spec_inch_dimensions_are_normalized_to_mm():
    from instant_machinist.drawing import Spec, spec_to_features

    spec = Spec.model_validate({
        "part_number": "INCH-1", "name": "inch plate", "material": "6061",
        "quantity": 1, "units": "in", "general_tolerance_mm": 0.004,
        "features": [
            {"id": "F1", "type": "face", "z": 0},
            {"id": "F2", "type": "profile", "side": "outside",
             "rect": {"cx": 0, "cy": 0, "w": 2, "h": 1, "r": 0.1},
             "z_top": 0, "z_bottom": -0.5},
        ], "notes": [], "questions_for_customer": [],
    })
    model = spec_to_features(spec)
    p = next(f for f in model["features"] if f["type"] == "profile")
    assert p["rect"]["w"] == pytest.approx(50.8)
    assert p["z_bottom"] == pytest.approx(-12.7)
    assert model["general_tolerance_mm"] == pytest.approx(0.1016)
