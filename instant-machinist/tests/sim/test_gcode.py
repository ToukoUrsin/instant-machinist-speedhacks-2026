import math
from pathlib import Path

import numpy as np
import pytest

from instant_machinist.sim.gcode import DWELL, FEED, RAPID, TOOLCHANGE, GCodeError, parse_programs

FUSION_COVER = Path("~/work/cad-cam-pion/runs/fusion-compute-2026-10-08/t1-03-cover-plate/1001.nc")


def P(text, **kw):
    return parse_programs(text if "\n" in text else text + "\n", **kw)


def arc_pts(tp):
    m = tp.kind == FEED
    return np.vstack([tp.p0[m][:1], tp.p1[m]])


def test_quarter_arc_ij_on_radius_and_chord_tol():
    tp = P("G21 G90 G17\nG0 X10 Y0 Z0\nG3 X0 Y10 I-10 J0 F500\n")
    pts = arc_pts(tp)
    r = np.hypot(pts[:, 0], pts[:, 1])
    assert np.allclose(r, 10, atol=1e-9)
    assert np.allclose(pts[-1], [0, 10, 0])
    # chord sagitta within 0.01 mm
    seg = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1).max()
    assert 10 - math.sqrt(100 - (seg / 2) ** 2) <= 0.0100001
    # CCW: all points in first quadrant
    assert (pts[:, 0] >= -1e-9).all() and (pts[:, 1] >= -1e-9).all()


def test_cw_vs_ccw_and_full_circle():
    tp = P("G0 X10 Y0 Z0\nG2 X0 Y10 I-10 J0 F500\n")  # CW the long way (270 deg)
    pts = arc_pts(tp)
    assert pts[:, 1].min() < -9.9 and pts[:, 0].min() < -9.9
    tp = P("G0 X10 Y0 Z0\nG3 X10 Y0 I-10 J0 Z-2 F500\n")  # full helical circle
    pts = arc_pts(tp)
    assert pts[:, 0].min() < -9.99 and np.isclose(pts[-1, 2], -2)
    assert np.allclose(np.hypot(pts[:, 0], pts[:, 1]), 10)


def test_r_format_minor_and_major():
    tp = P("G0 X10 Y0 Z0\nG3 X0 Y10 R10 F500\n")
    pts = arc_pts(tp)
    assert np.allclose(np.hypot(pts[:, 0], pts[:, 1]), 10, atol=1e-6)  # centre at origin
    tp = P("G0 X10 Y0 Z0\nG3 X0 Y10 R-10 F500\n")  # major arc: centre at (10,10)
    pts = arc_pts(tp)
    assert np.allclose(np.hypot(pts[:, 0] - 10, pts[:, 1] - 10), 10, atol=1e-6)


def test_g18_lead_in_is_tangent():
    # Fusion-style lead-in: G18 G3 from X94.5 Z5 to X89.5 Z0, centre X89.5 Z5
    tp = P("G21\nG0 X94.5 Y0 Z5\nG18 G3 X89.5 Z0 I-5 K0 F1000\n")
    pts = arc_pts(tp)
    assert np.allclose(np.hypot(pts[:, 0] - 89.5, pts[:, 2] - 5), 5, atol=1e-6)
    assert (pts[:, 0] >= 89.5 - 1e-9).all() and (pts[:, 2] <= 5 + 1e-9).all()  # short quarter arc
    # G19 J/K arc
    tp = P("G0 X0 Y26 Z-7\nG19 G2 Y25 Z-8 J-1 K0 F500\n")
    pts = arc_pts(tp)
    assert np.allclose(pts[-1], [0, 25, -8])
    assert np.allclose(np.hypot(pts[:, 1] - 25, pts[:, 2] + 7), 1, atol=1e-6)
    assert (pts[:, 1] >= 25 - 1e-9).all() and (pts[:, 2] <= -7 + 1e-9).all()  # CW short arc, going down


def test_inch_and_incremental():
    tp = P("G20 G90\nG0 X1. Y0 Z1.\nG1 X2. F10.\nG91 G1 Y1.\nG90\n")
    assert np.allclose(tp.p1[-1], [50.8, 25.4, 25.4])
    assert np.isclose(tp.feed[tp.kind == FEED][0], 254.0)


def test_g52_local_work_offset_translates_absolute_moves_and_arcs():
    tp = P("G90 G21 G0 X0 Y0 Z0\nG52 X100 Y-20\nG1 X5 Y2 F100\nG3 X5 Y12 I0 J5 F100\nG52 X0 Y0\nG1 X1 Y1 F100\n")
    # The local frame shifts both linear and arc endpoints; G52 X0 Y0 cancels it.
    assert np.allclose(tp.p1[0], [0, 0, 0])
    assert np.allclose(tp.p1[1], [105, -18, 0])
    assert np.allclose(tp.p1[tp.nc_line == 4][-1], [105, -8, 0])
    assert np.allclose(tp.p1[ -1], [1, 1, 0])


def test_standard_work_coordinate_selection_uses_configured_offsets():
    tp = P("G90 G21 G54 G0 X1 Y2 Z3\nG55 G1 X4 Y5 F100\nG54 G1 X6 Y7 F100\n",
            work_offsets={55: (100.0, -20.0, 3.0)})
    assert np.allclose(tp.p1[0], [1, 2, 3])
    assert np.allclose(tp.p1[1], [104, -15, 3])
    assert np.allclose(tp.p1[2], [6, 7, 3])
    assert not any("not supported" in w for w in tp.warnings)


def test_g54_1_extended_offset_and_missing_datum_diagnostic():
    tp = P("G90 G54.1 P7 G0 X1 Y2 Z3\nG1 X2 F100\n",
            work_offsets={(54.1, 7): (10.0, 20.0, -2.0)})
    assert np.allclose(tp.p1[0], [11, 22, 1])
    assert np.allclose(tp.p1[1], [12, 22, 1])
    assert not any("no configured work offset" in w for w in tp.warnings)
    missing = P("G90 G54.1 P99 G0 X1 Y2 Z3\n")
    assert np.allclose(missing.p1[0], [1, 2, 3])
    assert any("G54.1 P99" in w for w in missing.warnings)


def test_tool_change_and_g53_g28():
    tp = P("G53 G0 Z0.\nT3 M6\nG0 X1 Y2\nZ5\nT4\nG28 G91 Z0.\nG90\nM6\n", home_z=50.0)
    tc = np.where(tp.kind == TOOLCHANGE)[0]
    assert len(tc) == 2
    assert tp.tool[tc[0]] == 3 and tp.tool[tc[1]] == 4
    assert np.isclose(tp.p1[-1, 2], 50.0)


def test_canned_g81_g98_g99():
    tp = P("G90 G21\nT1 M6\nG0 X0 Y0 Z10\nG99 G81 X5 Y5 Z-3 R2 F100\nG98 X10\nG80\n", home_z=50)
    m = tp.kind != TOOLCHANGE
    p1, kind = tp.p1[m], tp.kind[m]
    zs = [round(float(z), 3) for z in p1[:, 2]]
    # hole 1: xy rapid at Z10, rapid R2, feed -3, rapid back to R (G99)
    i = zs.index(-3.0)
    assert kind[i] == FEED and zs[i - 1] == 2.0 and zs[i + 1] == 2.0
    # hole 2 retracts to initial Z10 (G98)
    j = len(zs) - 1 - zs[::-1].index(-3.0)
    assert np.allclose(p1[j], [10, 5, -3]) and zs[j + 1] == 10.0


def test_canned_g83_pecks_and_g82_dwell_and_g73():
    tp = P("G90\nT1 M6\nG0 X0 Y0 Z10\nG98 G83 X0 Y0 Z-10 R1 Q3 F100\nG80\n")
    feeds = tp.p1[tp.kind == FEED]
    assert np.allclose(sorted(set(np.round(feeds[:, 2], 3))), [-10, -8, -5, -2])
    assert np.isclose(tp.p1[-1, 2], 10)
    tp = P("G90\nT1 M6\nG0 X0 Y0 Z10\nG82 X0 Y0 Z-2 R1 P500 F100\nG82 X1 Z-2 R1 P0.25\nG80\n")
    dw = tp.dwell[tp.kind == DWELL]
    assert np.allclose(dw, [0.5, 0.25])
    tp = P("G90\nT1 M6\nG0 X0 Y0 Z10\nG73 X0 Y0 Z-4 R1 Q2 F100\nG80\n")
    assert np.isclose(tp.p1[tp.kind == FEED][:, 2].min(), -4)
    assert (tp.kind == RAPID).sum() >= 4


def test_comments_n_numbers_and_end():
    tp = P("%\nO1234 (HELLO G0 X99)\nN10 G0 X1 Y1 Z1 ; trailing\nN20 M30\nG0 X50\n%\n")
    assert np.allclose(tp.p1[-1], [1, 1, 1])


def test_r_arc_without_motion_error():
    with pytest.raises(GCodeError):
        P("G0 X0 Y0 Z0\nG2 X0 Y0 R5 F100\n")


@pytest.mark.skipif(not FUSION_COVER.exists(), reason="Fusion sample not present")
def test_fusion_inch_program_parses():
    tp = parse_programs(FUSION_COVER, home_z=50)
    assert len(tp) > 5000
    assert (tp.kind == TOOLCHANGE).sum() == 7
    # cover plate is a few inches: everything within +-300 mm
    assert np.abs(tp.p1[:, :2]).max() < 300
    canned = [w for w in tp.warnings if "not supported" in w]
    assert not canned


def test_m98_subprogram_expansion_with_repeats_and_source_lines():
    tp = P("""%
O1
G90 G0 X0 Y0 Z5
M98 P1000 L2
G90 G0 X10
M30
O1000
G91 G1 X1 F120
M99
%
""")
    feeds = tp.kind == FEED
    assert feeds.sum() == 2
    assert np.allclose(tp.p1[feeds, 0], [1, 2])
    assert np.all(tp.nc_line[feeds] == 8)
    assert not any("not supported" in w for w in tp.warnings)


def test_missing_subprogram_call_warns_without_motion():
    tp = P("""O1
G0 X0
M98 P9999
M30
O1000
G1 X100 F100
M99
G1 X200 F100
""")
    assert len(tp) == 0
    assert any("target not found" in w for w in tp.warnings)


def test_m98_call_is_bounded_for_recursive_subprogram():
    tp = P("""O1
M98 P1000
M30
O1000
M98 P1000
M99
""")
    assert len(tp) == 0
    assert any("recursive" in w for w in tp.warnings)


def test_m99_returns_without_executing_subprogram_tail():
    tp = P("""O1
G0 X0
M98 P1000
M30
O1000
G1 X1 F100
M99
G1 X99 F100
""")
    assert np.allclose(tp.p1[tp.kind == FEED, 0], [1.0])
