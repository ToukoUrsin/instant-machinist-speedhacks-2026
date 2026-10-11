"""Generate a hand-planned, correct SM-101 program (parts/sm-101 tools) for sim tests.

    .venv/bin/python tests/sim/fixtures/make_sm101.py  -> tests/sim/fixtures/sm101_good.nc
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent


def f(v: float) -> str:
    return f"{v:.3f}"


def rrect(cx, cy, w, h, r, out, ccw=True):
    """Rounded-rect contour starting/ending at the middle of the +X side."""
    hw, hh = w / 2, h / 2
    r = max(0.0, min(r, hw, hh))
    if ccw:
        pts = [
            ("G1", cx + hw, cy + hh - r, None),
            ("G3", cx + hw - r, cy + hh, (cx + hw - r, cy + hh - r)),
            ("G1", cx - hw + r, cy + hh, None),
            ("G3", cx - hw, cy + hh - r, (cx - hw + r, cy + hh - r)),
            ("G1", cx - hw, cy - hh + r, None),
            ("G3", cx - hw + r, cy - hh, (cx - hw + r, cy - hh + r)),
            ("G1", cx + hw - r, cy - hh, None),
            ("G3", cx + hw, cy - hh + r, (cx + hw - r, cy - hh + r)),
            ("G1", cx + hw, cy, None),
        ]
    else:
        pts = [
            ("G1", cx + hw, cy - hh + r, None),
            ("G2", cx + hw - r, cy - hh, (cx + hw - r, cy - hh + r)),
            ("G1", cx - hw + r, cy - hh, None),
            ("G2", cx - hw, cy - hh + r, (cx - hw + r, cy - hh + r)),
            ("G1", cx - hw, cy + hh - r, None),
            ("G2", cx - hw + r, cy + hh, (cx - hw + r, cy + hh - r)),
            ("G1", cx + hw - r, cy + hh, None),
            ("G2", cx + hw, cy + hh - r, (cx + hw - r, cy + hh - r)),
            ("G1", cx + hw, cy, None),
        ]
    px, py = cx + hw, cy
    for g, x, y, c in pts:
        if c is None:
            out.append(f"{g} X{f(x)} Y{f(y)}")
        elif r > 0:
            out.append(f"{g} X{f(x)} Y{f(y)} I{f(c[0] - px)} J{f(c[1] - py)}")
        else:
            continue
        px, py = x, y


def build() -> str:
    o = ["%", "O1101 (SM-101 HAND PLANNED)", "G90 G17 G21 G94 G40 G49 G80", "G53 G0 Z0."]
    # ---- T1 face
    o += ["(FACE TOP)", "T1 M6", "S6000 M3", "G54 G0 X-95. Y-20.", "G43 H1 Z5. M8", "G1 Z0. F800",
          "G1 X95. F1500", "G0 Y20.", "G1 X-95.", "G0 Z5.", "M9", "G53 G0 Z0."]
    # ---- T2 outside profile
    o += ["(PROFILE OUTSIDE)", "T2 M6", "S8000 M3", "G0 X-75. Y0.", "G43 H2 Z5. M8", "G1 Z0. F600"]
    z = 0.0
    while z > -20 + 1e-9:
        z = max(z - 2.5, -20.0)
        o += [f"G1 Z{f(z)} F600", "G1 X-65. F1000"]
        # climb on an outside contour = clockwise; start at middle of -X side
        o += ["G1 Y32.", "G2 X-52. Y45. I13. J0.", "G1 X52.", "G2 X65. Y32. I0. J-13.", "G1 Y-32.",
              "G2 X52. Y-45. I-13. J0.", "G1 X-52.", "G2 X-65. Y-32. I0. J13.", "G1 Y0.", "G1 X-75."]
    o += ["G0 Z5."]
    # ---- T2 pocket F3 64x36 r6 depth 8: helix entry + offset contours
    o += ["(POCKET F3)", "G0 X2. Y0.", "G0 Z1."]
    z = 0.5
    o += [f"G1 Z{f(z)} F600"]
    for level in (-2.0, -4.0, -6.0, -8.0):
        o += ["G1 X2. Y0. F1200"]
        while z > level + 1e-9:
            z = max(z - 1.0, level)
            o.append(f"G3 X2. Y0. Z{f(z)} I-2. J0. F900")
        o.append("G3 X2. Y0. I-2. J0.")
        for w, h, r in ((30, 2, 0), (38, 10, 0), (46, 18, 0), (54, 26, 1)):
            o.append(f"G1 X{f(w / 2)} Y0. F1200")
            rrect(0, 0, w, h, r, o, ccw=True)
        o.append("G1 X2. Y0.")
    o += ["G0 Z5.", "M9", "G53 G0 Z0."]
    # ---- T3 slot pocket F4 40x8 r4 at y=-30, depth 4: ramp entry + contour
    o += ["(POCKET F4)", "T3 M6", "S10000 M3", "G0 X-16. Y-30.", "G43 H3 Z5. M8", "G1 Z0.5 F500"]
    z = 0.5
    for level in (-1.0, -2.0, -3.0, -4.0):
        o += [f"G1 X16. Z{f(level)} F600", "G1 X-16. F800", "G1 X17."]
        rrect(0, -30, 34, 2, 1, o, ccw=True)
        o += ["G1 X-16. Y-30."]
    o += ["G0 Z5.", "M9", "G53 G0 Z0."]
    # ---- T4 spot drill
    o += ["(SPOT)", "T4 M6", "S5000 M3", "G0 X-50. Y-30.", "G43 H4 Z10. M8",
          "G98 G82 X-50. Y-30. Z-2. R2. P300 F250", "X50.", "Y30.", "X-50.", "G80",
          "G0 X-20. Y0.", "G99 G82 X-20. Y0. Z-10. R-6. P0.3 F250", "G98 X20.", "G80", "M9", "G53 G0 Z0."]
    # ---- T5 drill 6.6 thru (peck)
    o += ["(DRILL 6.6)", "T5 M6", "S4000 M3", "G0 X-50. Y-30.", "G43 H5 Z10. M8",
          "G98 G83 X-50. Y-30. Z-22.5 R2. Q5. F300", "X50.", "Y30.", "X-50.", "G80", "M9", "G53 G0 Z0."]
    # ---- T6 drill 8 thru from pocket floor (G73 chip break)
    o += ["(DRILL 8.0)", "T6 M6", "S3500 M3", "G0 X-20. Y0.", "G43 H6 Z10. M8",
          "G98 G73 X-20. Y0. Z-23. R-6. Q3. F280", "X20.", "G80", "M9", "M5",
          "G28 G91 Z0.", "G90", "M30", "%"]
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    p = HERE / "sm101_good.nc"
    p.write_text(build())
    print(p)
