"""Cycle-time model for the simulator.

Feed and rapid moves use a one-dimensional trapezoidal velocity profile.  The
old model divided distance by commanded speed, which is optimistic for the
short blocks emitted by adaptive toolpaths.  The profile is deliberately
small and deterministic: it captures acceleration/deceleration while keeping
the report schema and the max-axis rapid convention unchanged.
"""
from __future__ import annotations

import numpy as np

from .gcode import DWELL, FEED, RAPID, TOOLCHANGE, Toolpath

RAPID_MM_MIN = 25000.0   # Haas VF-2 class, per axis
TOOL_CHANGE_S = 4.0
FEED_ACCEL_MM_S2 = 12000.0
RAPID_ACCEL_MM_S2 = 25000.0


def _trapezoid_time(distance_mm: float, speed_mm_min: float, accel_mm_s2: float) -> float:
    """Seconds for a rest-to-rest move at ``speed_mm_min``.

    A block is triangular when it is too short to reach the commanded speed;
    otherwise it has equal acceleration and deceleration ramps.  Invalid or
    zero values retain the parser's historic 1e-6 speed guard.
    """
    d = float(max(distance_mm, 0.0))
    if d == 0.0:
        return 0.0
    v = float(max(speed_mm_min, 1e-6)) / 60.0
    a = float(max(accel_mm_s2, 1e-6))
    d_ramps = v * v / a
    if d <= d_ramps:
        return 2.0 * np.sqrt(d / a)
    return 2.0 * v / a + (d - d_ramps) / v


def segment_times(
    tp: Toolpath,
    rapid_mm_min: float = RAPID_MM_MIN,
    tool_change_s: float = TOOL_CHANGE_S,
    feed_accel_mm_s2: float = FEED_ACCEL_MM_S2,
    rapid_accel_mm_s2: float = RAPID_ACCEL_MM_S2,
) -> np.ndarray:
    d = tp.p1 - tp.p0
    t = np.zeros(len(tp))
    feed = tp.kind == FEED
    length = np.linalg.norm(d, axis=1)
    if feed.any():
        t[feed] = np.fromiter(
            (_trapezoid_time(d, f, feed_accel_mm_s2) for d, f in zip(length[feed], tp.feed[feed])),
            dtype=float,
            count=int(feed.sum()),
        )
    rap = tp.kind == RAPID
    if rap.any():
        rlength = np.abs(d[rap]).max(axis=1)
        t[rap] = np.fromiter(
            (_trapezoid_time(dist, rapid_mm_min, rapid_accel_mm_s2) for dist in rlength),
            dtype=float,
            count=int(rap.sum()),
        )
    t[tp.kind == DWELL] = tp.dwell[tp.kind == DWELL]
    t[tp.kind == TOOLCHANGE] = tool_change_s
    return t


def cycle_report(tp: Toolpath, times: np.ndarray) -> dict:
    k = tp.kind
    def s(mask):
        return round(float(times[mask].sum()), 2)
    per_tool = {}
    for tn in sorted(set(tp.tool.tolist())):
        m = tp.tool == tn
        per_tool[f"T{tn}"] = {
            "cutting_s": s(m & (k == FEED)),
            "rapid_s": s(m & (k == RAPID)),
            "dwell_s": s(m & (k == DWELL)),
            "tool_change_s": s(m & (k == TOOLCHANGE)),
            "total_s": s(m),
            "feed_distance_mm": round(float(np.linalg.norm(tp.p1[m & (k == FEED)] - tp.p0[m & (k == FEED)], axis=1).sum()), 1),
        }
    total = float(times.sum())
    return {
        "cutting_s": s(k == FEED),
        "rapid_s": s(k == RAPID),
        "dwell_s": s(k == DWELL),
        "tool_change_s": s(k == TOOLCHANGE),
        "tool_changes": int((k == TOOLCHANGE).sum()),
        "total_s": round(total, 2),
        "total_min": round(total / 60.0, 2),
        "model": {"rapid_mm_min_per_axis": RAPID_MM_MIN, "tool_change_s": TOOL_CHANGE_S,
                  "feed_accel_mm_s2": FEED_ACCEL_MM_S2, "rapid_accel_mm_s2": RAPID_ACCEL_MM_S2,
                  "feed": "programmed F, trapezoidal acceleration profile",
                  "rapid": "max-axis distance, trapezoidal acceleration profile"},
        "per_tool": per_tool,
    }
