"""Native CAM engine tests: G-code parses, no move below feature floors, every feature machined."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from shapely.geometry import MultiLineString, Point, box
from shapely.prepared import prep

from instant_machinist.cam.gparse import parse
from instant_machinist.cam.optimize import BASELINE_PARAMS, variants
from instant_machinist.cam.plan import DEFAULT_PARAMS, plan_setup
from instant_machinist.cam.post_haas import post
from instant_machinist.cam.geom import rect_polygon

ROOT = Path(__file__).resolve().parents[2]
PART_DIR = ROOT / "parts" / "sm-101"
PART = json.loads((PART_DIR / "features.json").read_text())
TOOLS = json.loads((PART_DIR / "tools.json").read_text())
FEATS = {f["id"]: f for f in PART["features"]}
TOL = 0.005

_PICK = {"adaptive-so35-ap2D", "conventional-so60-ap1D"}  # one adaptive, one conventional, plus the baseline
PARAM_SETS = [dict(DEFAULT_PARAMS, **v) for v in variants() if v["name"] in _PICK] + [dict(DEFAULT_PARAMS, **BASELINE_PARAMS)]


def _program(P):
    ops = plan_setup(PART, TOOLS, P)
    return ops, post(ops, TOOLS, PART)


@pytest.fixture(scope="module", params=PARAM_SETS, ids=[p["name"] for p in PARAM_SETS])
def prog(request):
    ops, nc = _program(request.param)
    return {"ops": ops, "nc": nc, "pts": parse(nc)}


def _tool(tn):
    return TOOLS["tools"][str(tn)]


# ---------------------------------------------------------------------------- z floor model
PROFILE = next(f for f in PART["features"] if f["type"] == "profile")
PART_POLY = prep(rect_polygon(PROFILE["rect"]).buffer(-1e-3))
POCKETS = [(prep(rect_polygon(f["rect"]).buffer(1e-3)), f["z_bottom"]) for f in PART["features"] if f["type"] == "pocket"]
HOLES = [(x, y, f) for f in PART["features"] if f["type"] == "hole" for (x, y) in f["positions"]]
FACE_Z = next(f["z"] for f in PART["features"] if f["type"] == "face")


def z_floor(x, y):
    """Lowest Z a tool may reach at (x, y) given the finished part."""
    for hx, hy, f in HOLES:
        if math.hypot(x - hx, y - hy) <= f["d"] / 2 + 1e-3:
            return f["z_bottom"]
    pt = Point(x, y)
    if not PART_POLY.contains(pt):
        return PROFILE["z_bottom"]
    z = FACE_Z
    for poly, zb in POCKETS:
        if poly.contains(pt):
            z = min(z, zb)
    return z


def _disk_samples(x, y, R):
    yield x, y
    for frac in (0.5, 0.98):
        for k in range(16):
            a = 2 * math.pi * k / 16
            yield x + frac * R * math.cos(a), y + frac * R * math.sin(a)


# ---------------------------------------------------------------------------- tests
def test_gcode_dialect(prog):
    nc = prog["nc"]
    lines = nc.splitlines()
    assert lines[0] == "%" and lines[-1] == "%"
    assert re.match(r"^O01001\b", lines[1])
    for word in ("G21", "G54", "G43 H1", "G43 H2", "M8", "M30", "G83", "G80", "T1 M6", "G28 G91 Z0."):
        assert word in nc, word
    assert re.search(r"^G[23] X\S+ Y\S+( Z\S+)? I\S+ J\S+", nc, re.M), "arcs must be emitted as G2/G3 with I/J"
    assert "(T1 D50." in nc and "(T6 D8." in nc  # tool list comments


def test_parses_with_strict_parser(prog):
    pts = prog["pts"]
    assert len(pts) > 100
    assert {p["tool"] for p in pts if p["tool"]} == {1, 2, 3, 4, 5, 6}


def test_feeds_within_haas_limits(prog):
    for m in re.finditer(r"S(\d+)", prog["nc"]):
        assert int(m.group(1)) <= 8100
    for m in re.finditer(r"F(\d+)", prog["nc"]):
        assert 0 < int(m.group(1)) <= 16500


def test_no_move_below_feature_floor(prog):
    bad = []
    for p in prog["pts"]:
        t = _tool(p["tool"]) if p["tool"] else None
        if t is None:
            continue
        assert p["z"] >= PART["stock"]["z"][0], f"below stock bottom at line {p['line']}"
        if t["type"] in ("flat", "face_mill"):
            for sx, sy in _disk_samples(p["x"], p["y"], t["diameter"] / 2):
                if p["z"] < z_floor(sx, sy) - TOL:
                    bad.append((p["line"], p["tool"], round(sx, 2), round(sy, 2), p["z"]))
                    break
        else:  # drills: tip may pass a through-hole bottom by tip length + 1 mm breakthrough only
            zf = z_floor(p["x"], p["y"])
            hole = next((f for hx, hy, f in HOLES if math.hypot(p["x"] - hx, p["y"] - hy) < 1e-3), None)
            if p["z"] < zf - TOL:
                assert hole is not None and hole.get("through"), f"drill below floor off-hole, line {p['line']}"
                tip = (t["diameter"] / 2) / math.tan(math.radians(t.get("tip_angle", 118) / 2))
                assert p["z"] >= hole["z_bottom"] - tip - 1.0 - TOL, f"over-drilled at line {p['line']}"
    assert not bad, f"{len(bad)} gouging moves, first: {bad[:5]}"


def _cover(pts, zmax, types=("flat",)):
    """Union of flat-tool swept areas for feed moves at or below zmax."""
    by_tool = {}
    for a, b in zip(pts, pts[1:]):
        if b["rapid"] or a["tool"] != b["tool"] or not b["tool"]:
            continue
        if _tool(b["tool"])["type"] not in types:
            continue
        if a["z"] <= zmax + TOL and b["z"] <= zmax + TOL:
            seg = ((a["x"], a["y"]), (b["x"], b["y"]))
            if seg[0] == seg[1]:
                seg = (seg[0], (seg[0][0] + 1e-4, seg[0][1]))
            by_tool.setdefault(b["tool"], []).append(seg)
    cover = None
    for tn, segs in by_tool.items():
        area = MultiLineString(segs).buffer(_tool(tn)["diameter"] / 2, quad_segs=16)
        cover = area if cover is None else cover.union(area)
    return cover


def test_all_features_covered(prog):
    pts = prog["pts"]
    st = PART["stock"]
    stock = box(st["x"][0], st["y"][0], st["x"][1], st["y"][1])
    for f in PART["features"]:
        if f["type"] == "face":
            cov = _cover(pts, f["z"], ("face_mill",))
            assert cov is not None and stock.difference(cov).area < 1e-3, "face not fully covered"
        elif f["type"] in ("pocket", "profile"):
            region = rect_polygon(f["rect"])
            if f["type"] == "profile":
                region = stock.difference(region)
            cov = _cover(pts, f["z_bottom"])
            assert cov is not None, f["id"]
            left = region.difference(cov)
            # anything left must be a numerical sliver (< 0.05 mm thick) along the finished wall
            assert left.area < 0.5 and left.buffer(-0.05).is_empty, (f["id"], left.area)
        elif f["type"] == "hole":
            for x, y in f["positions"]:
                hits = [p for p in pts if p.get("cycle") and math.hypot(p["x"] - x, p["y"] - y) < 1e-3
                        and _tool(p["tool"])["type"] == "drill" and abs(_tool(p["tool"])["diameter"] - f["d"]) < 1e-6
                        and p["z"] <= f["z_bottom"] + TOL]
                assert hits, (f["id"], x, y)
                spots = [p for p in pts if p.get("cycle") and math.hypot(p["x"] - x, p["y"] - y) < 1e-3
                         and _tool(p["tool"])["type"] == "spot_drill"]
                assert spots, ("spot", f["id"], x, y)


def test_finish_tools_respect_corner_radius(prog):
    for op in prog["ops"]:
        if op["strategy"] != "contour-finish":
            continue
        R = _tool(op["tool"])["diameter"] / 2
        for fid in op["features"]:
            f = FEATS[fid]
            if f["type"] == "pocket":
                assert R < f["rect"]["r"], (fid, R)


def test_peck_drilling_uses_g83(prog):
    drills = [op for op in prog["ops"] if _tool(op["tool"])["type"] == "drill"]
    assert drills and all(op["strategy"] == "peck-G83" for op in drills)
    assert re.search(r"G9[89] G83 X\S+ Y\S+ Z\S+ R\S+ Q\S+ F\d+", prog["nc"])


def test_baseline_slower_than_best():
    from instant_machinist.cam.optimize import optimize
    results, baseline = optimize(PART, TOOLS, PART_DIR)
    assert results[0]["time"]["total_s"] < baseline["time"]["total_s"]
    assert results[0]["sim"] is None or results[0]["sim"]["ok"]
