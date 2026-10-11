"""Feeds and speeds for 6061-T6 aluminium with carbide tooling, clamped to a Haas VF-2."""
from __future__ import annotations

import math

MACHINE = {
    "name": "Haas VF-2",
    "max_rpm": 8100,
    "max_feed_mm_min": 16500.0,
    "rapid_mm_min": 25400.0,       # 1000 ipm XYZ rapids
    "tool_change_s": 4.2,           # chip-to-chip
    "spindle_start_s": 1.0,
}

MM_PER_FT = 304.8

# 6061-T6, carbide. SFM and chipload (mm/tooth) or feed/rev (mm/rev for drills) by tool type.
# Chipload rows: (max diameter mm, chipload). First row whose diameter >= tool diameter wins.
TABLE_6061_CARBIDE = {
    "face_mill": {"sfm": 2000, "chipload": [(999, 0.10)]},
    "flat": {"sfm": 1000, "chipload": [(3, 0.013), (6, 0.050), (10, 0.080), (16, 0.090), (999, 0.11)]},
    "ball": {"sfm": 900, "chipload": [(6, 0.030), (999, 0.06)]},
    "spot_drill": {"sfm": 400, "feed_per_rev": [(999, 0.06)]},
    "drill": {"sfm": 400, "feed_per_rev": [(4, 0.08), (8, 0.15), (12, 0.20), (999, 0.25)]},
}


def _row(rows, d):
    for dmax, v in rows:
        if d <= dmax:
            return v
    return rows[-1][1]


def chip_thinning_factor(ae: float, d: float) -> float:
    """Radial chip thinning: feed multiplier keeping the actual max chip at the table chipload."""
    x = max(min(ae / d, 1.0), 1e-3)
    if x >= 0.5:
        return 1.0
    return min(1.0 / math.sqrt(1 - (1 - 2 * x) ** 2), 2.0)


def speeds(tool: dict, *, ae: float | None = None, scale: float = 1.0, slot: bool = False,
           thinning: bool = True, machine: dict = MACHINE) -> dict:
    """Return rpm, cutting feed (mm/min), plunge/ramp feed for a tool.

    ae: radial engagement mm (chip-thinning applied when < D/2); slot: full-width cut.
    scale: global aggressiveness multiplier on surface speed and chipload (baseline < 1).
    """
    t = TABLE_6061_CARBIDE[tool["type"]]
    d = tool["diameter"]
    vc = t["sfm"] * MM_PER_FT / 1000.0 * scale  # m/min
    rpm_raw = vc * 1000.0 / (math.pi * d)
    rpm = min(rpm_raw, machine["max_rpm"])
    if "chipload" in t:
        fz = _row(t["chipload"], d) * scale
        if slot:
            fz *= 0.6
        elif ae is not None and thinning:
            fz *= chip_thinning_factor(ae, d)
        feed = rpm * tool.get("flutes", 2) * fz
        plunge = feed * 0.3
    else:
        fr = _row(t["feed_per_rev"], d) * scale
        feed = rpm * fr
        plunge = feed
        fz = fr
    feed = min(feed, machine["max_feed_mm_min"])
    plunge = min(plunge, machine["max_feed_mm_min"])
    return {
        "rpm": int(round(rpm)),
        "feed": round(feed),
        "plunge": round(plunge),
        "vc_m_min": round(rpm * math.pi * d / 1000.0, 1),
        "chip_mm": round(fz, 4),
        "rpm_clamped": rpm_raw > machine["max_rpm"],
    }
