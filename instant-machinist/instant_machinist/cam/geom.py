"""2D geometry for the native 2.5D CAM engine.

Loops are lists of segments, each either
  ("L", (x0, y0), (x1, y1))
  ("A", (x0, y0), (x1, y1), (cx, cy), cw)
All features in the current parts are rounded rectangles, so offsets are computed
analytically (exact G2/G3 arcs); shapely is used for areas, engagement and checks.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

EPS = 1e-6


def rect_polygon(rect: dict, offset: float = 0.0, res: int = 32) -> Polygon:
    """Rounded rectangle (cx, cy, w, h, r) grown by offset (negative = shrink)."""
    cx, cy, w, h, r = rect["cx"], rect["cy"], rect["w"], rect["h"], rect.get("r", 0.0)
    core = box(cx - w / 2 + r, cy - h / 2 + r, cx + w / 2 - r, cy + h / 2 - r)
    if r > 0:
        core = core.buffer(r, quad_segs=res)
    if abs(offset) > EPS:
        core = core.buffer(offset, quad_segs=res)
    return core


def rounded_rect_loop(cx: float, cy: float, W: float, H: float, r: float, ccw: bool):
    """Closed loop around a rounded rect with half sizes W, H and corner radius r.

    Starts and ends at the bottom-side midpoint (cx, cy - H). ccw=True travels
    counter-clockwise (climb inside pockets with M3), ccw=False clockwise (climb
    on outside profiles).
    """
    r = max(0.0, min(r, W, H))
    a, b = W - r, H - r
    pts = []  # sequence of (kind, end, center) for a CCW traversal
    # CCW: bottom-mid -> bottom-right corner -> right side -> top -> left -> bottom-mid
    pts.append(("L", (cx + a, cy - H), None))
    pts.append(("A", (cx + W, cy - b), (cx + a, cy - b)))
    pts.append(("L", (cx + W, cy + b), None))
    pts.append(("A", (cx + a, cy + H), (cx + a, cy + b)))
    pts.append(("L", (cx - a, cy + H), None))
    pts.append(("A", (cx - W, cy + b), (cx - a, cy + b)))
    pts.append(("L", (cx - W, cy - b), None))
    pts.append(("A", (cx - a, cy - H), (cx - a, cy - b)))
    pts.append(("L", (cx, cy - H), None))
    segs = []
    cur = (cx, cy - H)
    for kind, end, cen in pts:
        if math.dist(cur, end) < 1e-9:
            continue
        if kind == "A" and r < 1e-9:
            kind = "L"
        if kind == "L":
            segs.append(("L", cur, end))
        else:
            segs.append(("A", cur, end, cen, False))
        cur = end
    if not ccw:
        segs = reverse_loop(segs)
    return segs


def reverse_loop(segs):
    """Reverse a loop of ``('L', p0, p1)`` / ``('A', p0, p1, c, cw)`` segments, flipping arc direction."""
    out = []
    for s in reversed(segs):
        if s[0] == "L":
            out.append(("L", s[2], s[1]))
        else:
            out.append(("A", s[2], s[1], s[3], not s[4]))
    return out


def offset_rect_loop(rect: dict, d: float, ccw: bool, min_corner: float = 0.0):
    """Tool-centre loop at distance d from a rounded-rect boundary.

    d > 0 grows (outside profile), d < 0 shrinks (pocket). Returns (segs, W, H, r)
    or None if the offset collapses.
    """
    W = rect["w"] / 2 + d
    H = rect["h"] / 2 + d
    if W < -EPS or H < -EPS:
        return None
    W, H = max(W, 0.0), max(H, 0.0)
    r = rect.get("r", 0.0) + d
    r = max(r, min_corner, 0.0)
    r = min(r, W, H)
    return rounded_rect_loop(rect["cx"], rect["cy"], W, H, r, ccw), W, H, r


def seg_length(s) -> float:
    """Length of a line or arc segment in mm."""
    if s[0] == "L":
        return math.dist(s[1], s[2])
    sweep = arc_sweep(s)
    rad = math.dist(s[1], s[3])
    return abs(sweep) * rad


def arc_sweep(s) -> float:
    """Signed sweep angle (CCW positive) of an arc segment; full circle if start == end."""
    (x0, y0), (x1, y1), (cx, cy), cw = s[1], s[2], s[3], s[4]
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw:
        while sweep >= -1e-12:
            sweep -= 2 * math.pi
        if sweep < -2 * math.pi + 1e-12:
            sweep += 2 * math.pi
    else:
        while sweep <= 1e-12:
            sweep += 2 * math.pi
        if sweep > 2 * math.pi - 1e-12:
            sweep -= 2 * math.pi
    if math.dist((x0, y0), (x1, y1)) < 1e-9:
        sweep = -2 * math.pi if cw else 2 * math.pi
    return sweep


def sample_arc(p0, p1, c, cw, step: float = 0.5):
    """Points along the arc ``p0`` -> ``p1`` about ``c`` at roughly ``step`` mm spacing (endpoints included)."""
    s = ("A", p0, p1, c, cw)
    sweep = arc_sweep(s)
    rad = math.dist(p0, c)
    n = max(2, int(abs(sweep) * rad / step) + 1)
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    return [(c[0] + rad * math.cos(a0 + sweep * i / n), c[1] + rad * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]


def loop_points(segs, step: float = 0.5):
    """Polyline points of a segment loop, arcs sampled at ``step`` mm."""
    pts = [segs[0][1]]
    for s in segs:
        if s[0] == "L":
            pts.append(s[2])
        else:
            pts.extend(sample_arc(s[1], s[2], s[3], s[4], step)[1:])
    return pts


def swept_area(points, radius: float):
    """Area swept by a flat tool of given radius along a 2D polyline."""
    if len(points) == 1 or all(math.dist(points[0], p) < 1e-9 for p in points):
        return Point(points[0]).buffer(radius, quad_segs=16)
    return LineString(points).buffer(radius, quad_segs=16)


__all__ = [
    "rect_polygon", "rounded_rect_loop", "reverse_loop", "offset_rect_loop", "seg_length",
    "arc_sweep", "sample_arc", "loop_points", "swept_area", "unary_union", "box", "Point", "Polygon",
]
