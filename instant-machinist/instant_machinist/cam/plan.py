"""Operation planning for one top-side setup: face, rough, finish, spot, peck drill."""
from __future__ import annotations

import math

from .feeds import speeds
from .geom import box, loop_points, offset_rect_loop, rect_polygon, swept_area
from .toolpath import Toolpath

CLEARANCE_Z = 25.0  # after tool change (G43 H.. Z25.)
RETRACT_Z = 5.0     # inter-move safe plane, above stock top

DEFAULT_PARAMS = {
    "name": "adaptive",
    "rough_style": "adaptive",   # adaptive | conventional
    "stepover": 0.30,            # radial, fraction of D
    "ap_max": 2.0,               # axial step, fraction of D
    "leave": 0.2,                # radial + axial stock left for finishing
    "feed_scale": 1.0,
    "thinning": True,            # chip-thinning feed boost for light radial engagement
    "ramp_angle": 3.0,
    "helix_frac": 0.30,          # helix radius, fraction of D
    "floor_stepover": 0.60,
    "face_stepover": 0.70,
    "peck_q_frac": 1.0,          # G83 Q as fraction of drill D
}


# --------------------------------------------------------------------------------------
# tool selection
def _tools_of(tools: dict, kind: str):
    return sorted(((int(k), v) for k, v in tools.items() if v["type"] == kind), key=lambda kv: -kv[1]["diameter"])


def pick_pocket_tool(tools, feat, leave):
    """First flat end mill that fits the pocket corner radius with ``leave`` and reaches its depth."""
    rect = feat["rect"]
    depth = feat["z_top"] - feat["z_bottom"]
    lim = min(rect.get("r", 0.0), rect["w"] / 2, rect["h"] / 2)
    for tn, t in _tools_of(tools, "flat"):
        R = t["diameter"] / 2
        if R < lim and R + leave <= lim and t["flute_length"] >= depth:
            return tn
    raise ValueError(f"no flat end mill fits pocket {feat['id']} (corner r {lim})")


def pick_profile_tool(tools, feat):
    """First flat end mill whose flute length covers the profile depth."""
    depth = feat["z_top"] - feat["z_bottom"]
    for tn, t in _tools_of(tools, "flat"):
        if t["flute_length"] >= depth:
            return tn
    raise ValueError(f"no flat end mill long enough for profile {feat['id']}")


def pick_drill(tools, d):
    """Drill matching hole diameter ``d`` (mm) within 0.01 mm."""
    for tn, t in _tools_of(tools, "drill"):
        if abs(t["diameter"] - d) < 0.01:
            return tn
    raise ValueError(f"no drill for hole d={d}")


# --------------------------------------------------------------------------------------
# helpers
def _leadin(p0, t, n, rl):
    """Quarter-arc lead geometry: centre, start point, end-of-leadout, cw flag."""
    c = (p0[0] + n[0] * rl, p0[1] + n[1] * rl)
    s = (c[0] - t[0] * rl, c[1] - t[1] * rl)
    e = (c[0] + t[0] * rl, c[1] + t[1] * rl)
    ccw_tan = (n[1], -n[0])
    cw = not (abs(ccw_tan[0] - t[0]) < 1e-9 and abs(ccw_tan[1] - t[1]) < 1e-9)
    return c, s, e, cw


def _levels(z_top, z_floor, ap):
    depth = z_top - z_floor
    n = max(1, math.ceil(depth / ap - 1e-9))
    return [z_top - depth * (i + 1) / n for i in range(n)]


def _loop_start(segs):
    p0 = segs[0][1]
    s = segs[0]
    if s[0] == "L":
        dx, dy = s[2][0] - p0[0], s[2][1] - p0[1]
        L = math.hypot(dx, dy)
        return p0, (dx / L, dy / L), L
    # arc start: tangent perpendicular to radius
    cx, cy = s[3]
    rx, ry = p0[0] - cx, p0[1] - cy
    L = math.hypot(rx, ry)
    t = (ry / L, -rx / L) if s[4] else (-ry / L, rx / L)
    return p0, t, 0.0


def _op(opid, name, tool, strategy, features, sp, tp, **extra):
    d = {"id": opid, "name": name, "tool": tool, "strategy": strategy, "features": features,
         "rpm": sp["rpm"], "feed": sp["feed"], "moves": tp.moves}
    d.update(extra)
    return d


# --------------------------------------------------------------------------------------
# operations
def op_face(part, feat, tn, tool, P):
    """Zigzag face-mill operation across the stock to the face feature Z."""
    st = part["stock"]
    D = tool["diameter"]
    R = D / 2
    sp = speeds(tool, scale=P["feed_scale"])
    over = 0.15 * D
    y0, y1 = st["y"][0] + R - over, st["y"][1] - R + over
    n = max(1, math.ceil((y1 - y0) / (P["face_stepover"] * D) - 1e-9)) + 1 if y1 > y0 else 1
    ys = [y0 + (y1 - y0) * i / (n - 1) for i in range(n)] if n > 1 else [(y0 + y1) / 2]
    xa, xb = st["x"][0] - R - 2, st["x"][1] + R + 2
    z = feat["z"]
    tp = Toolpath((0, 0, CLEARANCE_Z))
    tp.comment(f"FACE {feat['id']} TO Z{z:g} ZIGZAG {len(ys)} PASSES")
    tp.rapid(xa, ys[0])
    tp.rapid(z=z + 1.0)
    tp.feed(z=z, f=sp["plunge"])
    left = True
    for i, y in enumerate(ys):
        if i:
            tp.feed(y=y, f=sp["feed"])
        tp.feed(x=xb if left else xa, f=sp["feed"])
        left = not left
    tp.rapid(z=RETRACT_Z)
    return _op("face", f"Face {feat['id']}", tn, "face-zigzag", [feat["id"]], sp, tp,
               stepover_mm=round(ys[1] - ys[0], 2) if len(ys) > 1 else 0.0, ap_mm=st["z"][1] - z)


def _pocket_rings(rect, d0, step, R, stop_r, ccw):
    """Inward offset rings from |d0| towards the centre. Returns list of (segs, W, H, r), outer first."""
    rings = []
    k = 0
    while True:
        res = offset_rect_loop(rect, -(d0 + k * step), ccw, min_corner=min(0.5 * R, 0.5 * step) if k else 0.0)
        if res is None:
            break
        rings.append(res)
        _, W, H, _ = res
        if min(W, H) <= stop_r:
            break
        k += 1
    return rings


def op_rough_pocket(feat, tn, tool, P):
    """Rough a pocket with helical entry and offset rings, leaving ``P['leave']`` mm on walls and floor."""
    rect = feat["rect"]
    D = tool["diameter"]
    R = D / 2
    leave = P["leave"]
    conventional = P["rough_style"] == "conventional"
    s = P["stepover"] * D
    ap = P["ap_max"] * D
    sp = speeds(tool, ae=s, scale=P["feed_scale"], thinning=P["thinning"] and not conventional)
    sp_slot = speeds(tool, slot=True, scale=P["feed_scale"])
    z_floor = feat["z_bottom"] + leave
    rings = _pocket_rings(rect, R + leave, s, R, min(s, 0.9 * R), ccw=True)
    inner = rings[-1]
    W0, H0 = rings[0][1], rings[0][2]
    rh = min(P["helix_frac"] * D, 0.9 * min(W0, H0))
    use_helix = rh >= 0.15 * D
    tp = Toolpath((0, 0, RETRACT_Z))
    tp.comment(f"ROUGH POCKET {feat['id']} {P['rough_style'].upper()} STEPOVER {s:.2f} AP {ap:.2f} LEAVE {leave}")
    top = feat["z_top"]
    for z in _levels(top, z_floor, ap):
        p_in, t_in, L_in = _loop_start(inner[0])
        if use_helix:
            cx, cy = rect["cx"], rect["cy"]
            pitch = 2 * math.pi * rh * math.tan(math.radians(P["ramp_angle"]))
            tp.rapid(cx + rh, cy, RETRACT_Z)
            tp.rapid(z=top + 1.0)
            tp.helix_down(cx, cy, rh, top + 1.0, z, pitch, sp_slot["feed"] * 0.6, ccw=True)
            tp.feed(p_in[0], p_in[1], z, sp_slot["feed"])
        else:
            L = max(L_in, 2.0)
            p1 = (p_in[0] + t_in[0] * L, p_in[1] + t_in[1] * L)
            tp.rapid(p_in[0], p_in[1], RETRACT_Z)
            tp.rapid(z=top + 1.0)
            tp.feed(z=top + 0.2, f=sp_slot["plunge"])
            tp.ramp_line(p_in, p1, top + 0.2, z, P["ramp_angle"], sp_slot["feed"] * 0.6)
        for i in range(len(rings) - 1, -1, -1):
            segs = rings[i][0]
            p0 = segs[0][1]
            if i != len(rings) - 1:
                tp.feed(p0[0], p0[1], z, sp_slot["feed"])  # step out to next ring
                tp.follow(segs, sp["feed"])
            else:
                tp.follow(segs, sp_slot["feed"])  # innermost ring is a full-width cut
        tp.rapid(z=RETRACT_Z)
        top = z
    return _op(f"rough_{feat['id']}", f"Rough pocket {feat['id']}", tn,
               f"{P['rough_style']}-offset", [feat["id"]], sp, tp,
               stepover_mm=round(s, 2), ap_mm=round(min(ap, feat['z_top'] - z_floor), 2), rings=len(rings),
               entry="helix" if use_helix else "ramp")


def op_rough_profile(part, feat, tn, tool, P):
    """Rough the outside profile in offset rings from stock to profile plus ``P['leave']``."""
    rect = feat["rect"]
    D = tool["diameter"]
    R = D / 2
    leave = P["leave"]
    conventional = P["rough_style"] == "conventional"
    s = P["stepover"] * D
    ap = P["ap_max"] * D
    sp = speeds(tool, ae=s, scale=P["feed_scale"], thinning=P["thinning"] and not conventional)
    st = part["stock"]
    stock = box(st["x"][0], st["y"][0], st["x"][1], st["y"][1])
    material = stock.difference(rect_polygon(rect))
    rings = []
    k = 0
    while k < 200:
        res = offset_rect_loop(rect, R + leave + k * s, ccw=False)
        sw = swept_area(loop_points(res[0], 1.0), R)
        if sw.intersection(material).area < 0.05:
            break
        rings.append(res)
        k += 1
    z_floor = feat["z_bottom"] + leave
    tp = Toolpath((0, 0, RETRACT_Z))
    tp.comment(f"ROUGH PROFILE {feat['id']} OUTSIDE {len(rings)} RINGS STEPOVER {s:.2f} AP {ap:.2f}")
    for z in _levels(feat["z_top"], z_floor, ap):
        for segs, W, H, r in reversed(rings):  # outside in
            _profile_pass(tp, segs, stock, R, R * 0.5, z, sp["feed"], sp["plunge"])
    return _op(f"rough_{feat['id']}", f"Rough profile {feat['id']}", tn,
               f"{P['rough_style']}-offset", [feat["id"]], sp, tp,
               stepover_mm=round(s, 2), ap_mm=round(min(ap, feat['z_top'] - z_floor), 2), rings=len(rings))


def _profile_pass(tp, segs, stock, R, rl, z, f, plunge):
    """One closed outside pass entered from outside the stock with a tangent arc."""
    p0, t, _ = _loop_start(segs)
    n = (-t[1], t[0])  # left-hand normal: outward for a CW (climb) outside loop
    c, s, e, cw = _leadin(p0, t, n, rl)
    # extend the approach straight out until the tool clears the stock by 1 mm
    extra = 0.0
    from shapely.geometry import Point
    while Point(s[0] + n[0] * extra, s[1] + n[1] * extra).distance(stock) < R + 1.0:
        extra += 1.0
    a = (s[0] + n[0] * extra, s[1] + n[1] * extra)
    tp.rapid(z=RETRACT_Z)
    tp.rapid(a[0], a[1])
    tp.rapid(z=z + 1.0)
    tp.feed(z=z, f=plunge)
    tp.feed(s[0], s[1], z, f)
    tp.arc(p0[0], p0[1], c[0], c[1], cw, f)
    tp.follow(segs, f)
    tp.arc(e[0], e[1], c[0], c[1], cw, f)
    tp.rapid(z=RETRACT_Z)


def op_finish_pocket(feat, tn, tool, P):
    """Finish a pocket floor with inward rings, then the walls in a final pass."""
    rect = feat["rect"]
    D = tool["diameter"]
    R = D / 2
    sp_floor = speeds(tool, ae=P["floor_stepover"] * D, scale=P["feed_scale"])
    sp_wall = speeds(tool, ae=P["leave"], scale=P["feed_scale"], thinning=False)
    z = feat["z_bottom"]
    tp = Toolpath((0, 0, RETRACT_Z))
    # floor: inward rings leaving 0.1 on the wall, ramped in from the rough floor
    tp.comment(f"FINISH FLOOR {feat['id']} Z{z:g}")
    sf = P["floor_stepover"] * D
    rings = _pocket_rings(rect, R + 0.1, sf, R, 0.9 * R, ccw=True)
    p_in, t_in, L_in = _loop_start(rings[-1][0])
    L = max(L_in, 2.0)
    p1 = (p_in[0] + t_in[0] * L, p_in[1] + t_in[1] * L)
    tp.rapid(p_in[0], p_in[1], RETRACT_Z)
    tp.rapid(z=feat["z_top"] + 1.0)  # rapid only to above the feature; feed the rest (walls carry finish stock)
    tp.feed(z=z + P["leave"] + 0.1, f=sp_floor["plunge"])
    tp.ramp_line(p_in, p1, z + P["leave"] + 0.1, z, P["ramp_angle"], sp_floor["feed"] * 0.5)
    for i in range(len(rings) - 1, -1, -1):
        segs = rings[i][0]
        tp.feed(segs[0][1][0], segs[0][1][1], z, sp_floor["feed"])
        tp.follow(segs, sp_floor["feed"])
    tp.rapid(z=RETRACT_Z)
    # wall: climb (CCW) single pass with quarter-arc lead in/out
    tp.comment(f"FINISH WALLS {feat['id']}")
    segs, W, H, r = offset_rect_loop(rect, -R, ccw=True)
    p0, t, _ = _loop_start(segs)
    n = (-t[1], t[0])  # left-hand normal: into the pocket for a CCW loop
    rl = min(R, 0.9 * H)
    c, s, e, cw = _leadin(p0, t, n, rl)
    tp.rapid(s[0], s[1], RETRACT_Z)
    tp.rapid(z=feat["z_top"] + 1.0)
    tp.feed(z=z, f=sp_wall["plunge"])
    tp.arc(p0[0], p0[1], c[0], c[1], cw, sp_wall["feed"])
    tp.follow(segs, sp_wall["feed"])
    tp.arc(e[0], e[1], c[0], c[1], cw, sp_wall["feed"])
    tp.rapid(z=RETRACT_Z)
    return _op(f"finish_{feat['id']}", f"Finish pocket {feat['id']} floor+walls", tn, "contour-finish",
               [feat["id"]], sp_wall, tp, floor_rings=len(rings), lead_radius=round(rl, 2))


def op_finish_profile(part, feat, tn, tool, P):
    """Single climb-milling finish pass on the outside profile at full depth."""
    rect = feat["rect"]
    D = tool["diameter"]
    R = D / 2
    sp = speeds(tool, ae=P["leave"], scale=P["feed_scale"], thinning=False)
    st = part["stock"]
    stock = box(st["x"][0], st["y"][0], st["x"][1], st["y"][1])
    segs, W, H, r = offset_rect_loop(rect, R, ccw=False)
    tp = Toolpath((0, 0, RETRACT_Z))
    tp.comment(f"FINISH PROFILE {feat['id']} CLIMB Z{feat['z_bottom']:g}")
    _profile_pass(tp, segs, stock, R, R, feat["z_bottom"], sp["feed"], sp["plunge"])
    return _op(f"finish_{feat['id']}", f"Finish profile {feat['id']}", tn, "contour-finish",
               [feat["id"]], sp, tp, lead_radius=R)


def _hole_r(feat):
    return feat["z_top"] + 2.0


def op_spot(holes, tn, tool, P):
    """Spot-drill (G81) all hole positions to a chamfer slightly larger than each hole."""
    sp = speeds(tool, scale=P["feed_scale"])
    tp = Toolpath((0, 0, CLEARANCE_Z))
    half = math.radians(tool.get("tip_angle", 90) / 2)
    first = holes[0]["positions"][0]
    tp.rapid(first[0], first[1])
    for feat in holes:
        dia = min(feat["d"] + 0.4, tool["diameter"])
        zz = feat["z_top"] - (dia / 2) / math.tan(half)
        r = _hole_r(feat)
        pts = feat["positions"]
        tp.rapid(z=RETRACT_Z)
        tp.rapid(pts[0][0], pts[0][1])
        tp.comment(f"SPOT {feat['id']} D{dia:.2f} CHAMFER")
        tp.cycle(81, pts, round(zz, 3), r, sp["feed"], ret=99 if r >= 1.0 else 98)
    tp.rapid(z=RETRACT_Z)
    return _op("spot", "Spot drill " + "+".join(f["id"] for f in holes), tn, "spot-G81",
               [f["id"] for f in holes], sp, tp)


def op_drill(feat, tn, tool, P):
    """Peck-drill (G83) one hole feature; through holes go past the bottom by the tip length + 1 mm."""
    sp = speeds(tool, scale=P["feed_scale"])
    tip = (tool["diameter"] / 2) / math.tan(math.radians(tool.get("tip_angle", 118) / 2))
    zz = feat["z_bottom"] - (tip + 1.0 if feat.get("through") else 0.0)
    r = _hole_r(feat)
    q = round(P["peck_q_frac"] * tool["diameter"], 2)
    tp = Toolpath((0, 0, CLEARANCE_Z))
    pts = feat["positions"]
    tp.rapid(pts[0][0], pts[0][1])
    tp.rapid(z=RETRACT_Z)
    tp.comment(f"PECK DRILL {feat['id']} D{feat['d']} Q{q}")
    tp.cycle(83, pts, round(zz, 3), r, sp["feed"], q=q, ret=99 if r >= 1.0 else 98)
    tp.rapid(z=RETRACT_Z)
    return _op(f"drill_{feat['id']}", f"Peck drill {feat['id']}", tn, "peck-G83", [feat["id"]], sp, tp,
               peck_q=q, z_drill=round(zz, 3))


# --------------------------------------------------------------------------------------
def plan_setup(part: dict, tools_doc: dict, params: dict | None = None) -> list[dict]:
    """Plan the top setup: pick tools and build face, rough, finish, spot and drill ops grouped by tool.

    Returns the ordered operation list; ``params`` override DEFAULT_PARAMS.
    """
    P = dict(DEFAULT_PARAMS, **(params or {}))
    tools = tools_doc["tools"]
    feats = part["features"]
    ops_by_tool: dict[int, list] = {}
    order: list[int] = []

    def add(tn, op):
        """Append an op to its tool's group, recording first-use tool order."""
        if tn not in ops_by_tool:
            ops_by_tool[tn] = []
            order.append(tn)
        ops_by_tool[tn].append(op)

    face_tools = _tools_of(tools, "face_mill")
    for f in feats:
        if f["type"] == "face":
            tn = face_tools[0][0] if face_tools else pick_profile_tool(tools, {"z_top": 0, "z_bottom": 0})
            add(tn, op_face(part, f, tn, tools[str(tn)], P))

    milling = [f for f in feats if f["type"] in ("profile", "pocket")]
    choice = {}
    for f in milling:
        choice[f["id"]] = pick_profile_tool(tools, f) if f["type"] == "profile" else pick_pocket_tool(tools, f, P["leave"])
    # finishing tool must have R strictly below corner radius (checked in pick_pocket_tool)
    for tn in sorted(set(choice.values()), key=lambda t: -tools[str(t)]["diameter"]):
        tool = tools[str(tn)]
        mine = [f for f in milling if choice[f["id"]] == tn]
        for f in mine:  # roughing first: profile then pockets
            if f["type"] == "profile":
                add(tn, op_rough_profile(part, f, tn, tool, P))
        for f in mine:
            if f["type"] == "pocket":
                add(tn, op_rough_pocket(f, tn, tool, P))
        for f in mine:
            if f["type"] == "pocket":
                add(tn, op_finish_pocket(f, tn, tool, P))
        for f in mine:
            if f["type"] == "profile":
                add(tn, op_finish_profile(part, f, tn, tool, P))

    holes = [f for f in feats if f["type"] == "hole"]
    if holes:
        spots = _tools_of(tools, "spot_drill")
        if spots:
            add(spots[0][0], op_spot(holes, spots[0][0], tools[str(spots[0][0])], P))
        for f in sorted(holes, key=lambda f: tools[str(pick_drill(tools, f["d"]))]["diameter"]):
            tn = pick_drill(tools, f["d"])
            add(tn, op_drill(f, tn, tools[str(tn)], P))

    ops = [op for tn in order for op in ops_by_tool[tn]]
    for op in ops:
        op["params"] = P["name"]
    return ops
