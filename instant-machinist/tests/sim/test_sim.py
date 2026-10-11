import json
import time
from pathlib import Path

import numpy as np
import pytest

from instant_machinist.sim.run import main, simulate

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
TINY = FIX / "tiny_block"
SM101 = ROOT / "parts" / "sm-101"
FUSION_SM101 = ROOT / "out" / "sm-101" / "fusion" / "1001.nc"
FUSION_TOOLS = {"units": "mm", "tools": {
    "1": {"type": "face_mill", "diameter": 50.0, "flute_length": 6},
    "2": {"type": "flat", "diameter": 10.0, "flute_length": 25},
    "3": {"type": "flat", "diameter": 6.0, "flute_length": 16},
    "4": {"type": "flat", "diameter": 5.0, "flute_length": 22}}}


def test_tiny_good_passes(tmp_path):
    r = simulate(TINY, [FIX / "tiny_good.nc"], tmp_path, frames=60)
    c = r["checks"]
    assert r["ok"], json.dumps(c, indent=1)[:3000]
    assert c["leftover"]["area_mm2"] == 0 and c["gouge"]["area_mm2"] == 0
    ct = r["cycle_time"]
    assert ct["tool_changes"] == 2 and ct["tool_change_s"] == 8.0
    assert ct["total_s"] > ct["cutting_s"] > 0
    # outputs per contract
    f = np.load(tmp_path / "frames.npz")
    F = 60
    assert f["heights"].shape[0] == F and f["heights"].dtype == np.float32
    for k, shp in (("tool_pos", (F, 3)), ("tool_id", (F,)), ("tool_diam", (F,)), ("nc_line", (F,)), ("t_sec", (F,))):
        assert f[k].shape == shp, k
    assert f["final_gouge"].shape == f["heights"].shape[1:] and f["final_gouge"].dtype == bool
    assert np.allclose(np.diff(f["t_sec"]), f["t_sec"][-1] / (F - 1))   # uniform machine time
    assert np.nanmax(f["heights"][0]) == pytest.approx(1.0) and np.nanmax(f["heights"][-1]) <= 0.01
    tp = np.load(tmp_path / "toolpath.npz")
    assert tp["points"].shape[1] == 3 and len(tp["rapid"]) == len(tp["points"]) == len(tp["nc_line"])
    for name in ("report.json", "report.md", "final_maps.png"):
        assert (tmp_path / name).stat().st_size > 100


def test_tiny_gouge_caught_with_nc_line(tmp_path):
    r = simulate(TINY, [FIX / "tiny_gouge.nc"], tmp_path, frames=20, write_png=False)
    g = r["checks"]["gouge"]
    assert not r["ok"] and not g["ok"]
    ev = g["events"][0]
    assert ev["nc_line"] == 28 and "X8." in ev["block"]
    assert 9.75 <= ev["x"] <= 11.0 and abs(ev["y"]) <= 5
    assert g["max_depth_mm"] == pytest.approx(3.0, abs=0.05)


def test_flat_plunge_rapid_and_fixture(tmp_path):
    nc = tmp_path / "bad.nc"
    nc.write_text("\n".join([
        "G90 G21", "T2 M6", "G0 X0 Y0 Z5", "G1 Z-2. F200",          # line 4: straight plunge 2 mm into solid
        "G0 Z5", "G0 X5 Y0", "G0 Z-1.",                              # line 7: rapid into stock
        "G0 Z5", "G0 X0 Y-20", "G1 Z-5. F300", "G1 X10",             # line 11: in jaw (y face) below vise top Z-4
        "G0 Z5", "M30"]) + "\n")
    r = simulate(TINY, [nc], tmp_path, frames=10, write_png=False)
    c = r["checks"]
    assert [e["nc_line"] for e in c["flat_plunge"]["events"]] == [4]
    assert [e["nc_line"] for e in c["rapid_into_stock"]["events"]] == [7]
    assert c["below_fixture"]["events"][0]["nc_line"] in (10, 11)


def test_sm101_hand_program_passes_and_is_fast(tmp_path):
    t = time.perf_counter()
    r = simulate(SM101, [FIX / "sm101_good.nc"], tmp_path, frames=360)
    dt = time.perf_counter() - t
    assert r["ok"], json.dumps(r["checks"], indent=1)[:3000]
    assert dt < 60
    assert set(r["cycle_time"]["per_tool"]) == {f"T{i}" for i in range(1, 7)}


@pytest.mark.skipif(not FUSION_SM101.exists(), reason="Fusion SM-101 program not present")
def test_fusion_sm101_cli(tmp_path):
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps(FUSION_TOOLS))
    out = tmp_path / "sim"
    t = time.perf_counter()
    rc = main(["--part", str(SM101), "--nc", str(FUSION_SM101), "--tools", str(tools), "--out", str(out), "--quiet"])
    assert time.perf_counter() - t < 60
    r = json.loads((out / "report.json").read_text())
    assert rc == (0 if r["ok"] else 1)
    assert r["summary"]["segments"] > 5000 and r["cycle_time"]["total_s"] > 60
    assert r["checks"]["below_fixture"]["ok"] and r["checks"]["rapid_into_stock"]["ok"]


@pytest.mark.skipif(not (SM101 / "part.stl").exists(), reason="part.stl not generated")
def test_stl_target_matches_features():
    from instant_machinist.sim.stock import Stock
    from instant_machinist.sim.target import from_features, from_stl
    feats = json.loads((SM101 / "features.json").read_text())
    g = Stock.from_features(feats, 0.5).grid
    a, b = from_features(feats, g), from_stl(SM101 / "part.stl", feats, g)
    assert (np.abs(a.top - b.top) > 0.05).mean() < 0.002
    assert (np.isinf(a.floor) != np.isinf(b.floor)).mean() < 0.002


def test_diagonal_path_crossing_jaw_is_detected(tmp_path):
    # Both endpoints are beyond the jaw's lateral extent, but the diagonal
    # traverses the jaw while below its top. Endpoint-only checks miss this.
    nc = tmp_path / "jaw_cross.nc"
    nc.write_text("\n".join([
        "G90 G21", "T2 M6", "G0 X-100 Y-20 Z5", "G1 Z-5. F200",
        "G1 X0 Y0", "G1 X100 Y20", "G0 Z5", "M30", ""]))
    r = simulate(TINY, [nc], tmp_path, frames=8, write_png=False)
    ev = r["checks"]["below_fixture"]["events"]
    assert ev and ev[0]["nc_line"] in (5, 6)


def test_leftover_ignores_no_material_target_cells():
    """Waste and through holes must not be reported as finished-part leftover.

    STL targets use ``floor = -inf`` for rays that miss the mesh.  Their
    ``top`` value is still a finite sentinel (the part Z minimum), so a plain
    ``stock > top`` test would incorrectly mark all uncut waste as leftover.
    """
    from instant_machinist.sim.checks import Checker
    from instant_machinist.sim.gcode import parse_programs
    from instant_machinist.sim.stock import Grid, Stock
    from instant_machinist.sim.target import Target

    grid = Grid.for_box((-2, 2), (-2, 2), 1.0)
    stock = Stock(grid, z_top=1.0, z_bottom=-5.0)
    top = np.full((grid.ny, grid.nx), -4.0)
    floor = np.full((grid.ny, grid.nx), -np.inf)
    # One actual part cell remains 1 mm above its target and must be caught.
    iy, ix = grid.ny // 2, grid.nx // 2
    floor[iy, ix] = -4.0
    target = Target(top=top, floor=floor, source="synthetic")
    tp = parse_programs("G90 G21\n")
    feats = {"stock": {"x": [-2, 2], "y": [-2, 2], "z": [-5, 1]}}
    checks, _, leftover = Checker(feats, stock, target, {}, tp).finalize()
    assert checks["leftover"]["ok"] is False
    assert checks["leftover"]["area_mm2"] == pytest.approx(1.0)
    assert leftover.sum() == 1


def test_tool_profiles_match_analytic_bull_and_taper_surfaces():
    """Bull corner and tapered cutter profiles stay physically bounded."""
    from instant_machinist.sim.stock import Tool

    bull = Tool(number=7, type="bull", diameter=10.0, corner_radius=2.0)
    # Flat centre, tangent corner, and the outer edge of a radius-2 corner.
    assert np.asarray(bull.height(np.array([0.0, 3.0, 5.0]))).tolist() == pytest.approx([0.0, 0.0, 2.0])

    taper = Tool(number=8, type="taper", diameter=10.0, tip_diameter=4.0, taper_angle=30.0)
    h = taper.height(np.array([0.0, 2.0, 5.0]))
    assert h[0] == pytest.approx(0.0)
    assert h[1] == pytest.approx(0.0)  # radius at the cutting tip
    assert h[2] == pytest.approx(3.0 / np.tan(np.deg2rad(30.0)))


def test_load_tools_maps_fusion_aliases_and_inches(tmp_path):
    from instant_machinist.sim.stock import load_tools_diagnostics

    p = tmp_path / "tools.json"
    p.write_text(json.dumps({"units": "inch", "tools": {
        "1": {"fusion_type": "tapered_endmill", "diameter": 0.4,
               "tip_diameter": 0.2, "tip_angle": 15, "flute_length": 1.0},
        "2": {"type": "flat", "diameter": 0.25, "tip_angle": 0},
    }}))
    tools, events = load_tools_diagnostics(p)
    assert all(e["severity"] != "error" for e in events)
    assert tools[1].type == "taper"
    assert tools[1].diameter == pytest.approx(10.16)
    assert tools[1].tip_diameter == pytest.approx(5.08)
    assert tools[1].flute_length == pytest.approx(25.4)
    assert tools[2].type == "flat" and tools[2].diameter == pytest.approx(6.35)


def test_invalid_tool_metadata_is_reported_and_not_simulated(tmp_path):
    tools = tmp_path / "bad-tools.json"
    tools.write_text(json.dumps({"tools": {
        "1": {"type": "flat", "diameter": 0},
        "2": {"type": "mystery", "diameter": 6},
        "3": {"type": "flat", "diameter": 6, "flute_length": -1},
    }}))
    nc = tmp_path / "bad-meta.nc"
    nc.write_text("G90 G21\nT1 M6\nG0 X0 Y0 Z5\nG1 Z0 F100\nM30\n")
    r = simulate(TINY, [nc], tmp_path / "out", tools=tools, frames=4, write_png=False)
    md = r["checks"]["tool_metadata"]
    assert not md["ok"]
    assert any(e["tool"] == 1 and "diameter" in e["issue"] for e in md["errors"])
    assert r["ok"] is False


def test_missing_referenced_tool_is_reported(tmp_path):
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps({"tools": {"1": {"type": "flat", "diameter": 6}}}))
    nc = tmp_path / "missing.nc"
    nc.write_text("G90 G21\nT9 M6\nG0 X0 Y0 Z5\nG1 Z0 F100\nM30\n")
    r = simulate(TINY, [nc], tmp_path / "out", tools=tools, frames=4, write_png=False)
    md = r["checks"]["tool_metadata"]
    assert not md["ok"]
    assert any(e["tool"] == 9 and "missing" in e["issue"] for e in md["errors"])


def test_non_cutting_tool_envelopes_detect_shank_and_holder_stock_collision(tmp_path):
    """Crib envelope dimensions make holder/shank contact an auditable check."""
    tools = tmp_path / "envelopes.json"
    tools.write_text(json.dumps({"tools": {
        "2": {"type": "drill", "diameter": 4, "tip_angle": 118,
              "flute_length": 0.5, "shank_diameter": 8, "shank_length": 6},
        "3": {"type": "drill", "diameter": 4, "tip_angle": 118,
              "flute_length": 0.5, "holder_diameter": 20, "holder_length": 5},
    }}))
    nc = tmp_path / "envelopes.nc"
    nc.write_text("\n".join([
        "G90 G21", "T2 M6", "G0 X-15 Y0 Z5", "G1 X-10 Y0 Z0 F100",
        "G1 X10 Y0 Z0 F100", "T3 M6", "G0 X-15 Y5 Z5",
        "G1 X-10 Y5 Z0 F100", "G1 X10 Y5 Z0 F100", "M30", ""]))
    r = simulate(TINY, [nc], tmp_path / "out", tools=tools, frames=12, write_png=False)
    c = r["checks"]
    assert c["shank_collision"]["count"] >= 1
    assert c["holder_collision"]["count"] >= 1
    assert not c["shank_collision"]["ok"] and not c["holder_collision"]["ok"]
    assert r["ok"] is False


def test_tool_envelope_metadata_is_scaled_with_inches(tmp_path):
    from instant_machinist.sim.stock import load_tools_diagnostics

    p = tmp_path / "inch-tools.json"
    p.write_text(json.dumps({"units": "inch", "tools": {
        "1": {"type": "flat", "diameter": 0.25, "flute_length": 0.5,
               "shank_diameter": 0.3, "shank_length": 1, "holder_diameter": 1,
               "holder_length": 2}}}))
    tools, errors = load_tools_diagnostics(p)
    assert not [e for e in errors if e["severity"] == "error"]
    assert tools[1].shank_diameter == pytest.approx(7.62)
    assert tools[1].shank_length == pytest.approx(25.4)
    assert tools[1].holder_diameter == pytest.approx(25.4)


def test_invalid_tool_metadata_is_reported_and_not_simulated(tmp_path):
    tools = tmp_path / "bad-tools.json"
    tools.write_text(json.dumps({"tools": {
        "1": {"type": "flat", "diameter": 0},
        "2": {"type": "mystery", "diameter": 6},
        "3": {"type": "flat", "diameter": 6, "flute_length": -1},
    }}))
    nc = tmp_path / "bad-meta.nc"
    nc.write_text("G90 G21\nT1 M6\nG0 X0 Y0 Z5\nG1 Z0 F100\nM30\n")
    r = simulate(TINY, [nc], tmp_path / "out", tools=tools, frames=4, write_png=False)
    md = r["checks"]["tool_metadata"]
    assert not md["ok"]
    assert any(e["tool"] == 1 and "diameter" in e["issue"] for e in md["errors"])
    assert r["ok"] is False


def test_missing_referenced_tool_is_reported(tmp_path):
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps({"tools": {"1": {"type": "flat", "diameter": 6}}}))
    nc = tmp_path / "missing.nc"
    nc.write_text("G90 G21\nT9 M6\nG0 X0 Y0 Z5\nG1 Z0 F100\nM30\n")
    r = simulate(TINY, [nc], tmp_path / "out", tools=tools, frames=4, write_png=False)
    md = r["checks"]["tool_metadata"]
    assert not md["ok"]
    assert any(e["tool"] == 9 and "missing" in e["issue"] for e in md["errors"])
