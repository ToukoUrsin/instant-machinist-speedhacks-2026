"""Machine-neutral toolpath IR, builder and own cycle-time estimate."""
from __future__ import annotations

import math

from .feeds import MACHINE
from .geom import arc_sweep, sample_arc

PECK_CLEAR = 0.5  # G83 rapid-down clearance above previous peck depth (mm)


class Toolpath:
    """Accumulates moves with absolute positions. Every move stores the full end point."""

    def __init__(self, start=(0.0, 0.0, 25.0)):
        self.moves: list[dict] = []
        self.pos = list(start)

    # -- primitives -------------------------------------------------------
    def comment(self, text: str):
        self.moves.append({"t": "comment", "text": text})

    def rapid(self, x=None, y=None, z=None):
        p = [self.pos[0] if x is None else x, self.pos[1] if y is None else y, self.pos[2] if z is None else z]
        if math.dist(p, self.pos) < 1e-9:
            return
        self.moves.append({"t": "rapid", "x": p[0], "y": p[1], "z": p[2]})
        self.pos = p

    def feed(self, x=None, y=None, z=None, f=1000.0):
        p = [self.pos[0] if x is None else x, self.pos[1] if y is None else y, self.pos[2] if z is None else z]
        if math.dist(p, self.pos) < 1e-9:
            return
        self.moves.append({"t": "feed", "x": p[0], "y": p[1], "z": p[2], "f": f})
        self.pos = p

    def arc(self, x, y, cx, cy, cw, f, z=None):
        z = self.pos[2] if z is None else z
        self.moves.append({"t": "arc", "x": x, "y": y, "z": z, "cx": cx, "cy": cy, "cw": cw, "f": f,
                           "x0": self.pos[0], "y0": self.pos[1], "z0": self.pos[2]})
        self.pos = [x, y, z]

    def cycle(self, g: int, pts, z: float, r: float, f: float, q: float | None = None,
              p: float | None = None, ret: int = 98):
        init_z = self.pos[2]
        self.moves.append({"t": "cycle", "g": g, "pts": [list(map(float, pt)) for pt in pts], "z": z, "r": r,
                           "f": f, "q": q, "p": p, "ret": ret, "init_z": init_z})
        last = pts[-1]
        self.pos = [float(last[0]), float(last[1]), init_z if ret == 98 else r]

    # -- composite --------------------------------------------------------
    def follow(self, segs, f: float, z: float | None = None):
        for s in segs:
            if s[0] == "L":
                self.feed(s[2][0], s[2][1], z, f)
            else:
                self.arc(s[2][0], s[2][1], s[3][0], s[3][1], s[4], f, z)

    def helix_down(self, cx, cy, rh, z_from, z_to, pitch, f, ccw=True):
        """Helical ramp from current point (must be at (cx+rh, cy, z_from)) down to z_to, plus a flat full turn."""
        z = z_from
        while z - z_to > 1e-6:
            nz = max(z - pitch, z_to)
            self.arc(cx + rh, cy, cx, cy, not ccw, f, nz)
            z = nz
        self.arc(cx + rh, cy, cx, cy, not ccw, f, z_to)

    def ramp_line(self, p0, p1, z_from, z_to, angle_deg, f):
        """Zig-zag linear ramp between p0 and p1 (tool at p0, z_from), ending at p0 at z_to."""
        L = math.dist(p0, p1)
        dz_leg = max(L * math.tan(math.radians(angle_deg)), 1e-3)
        z, at_p0 = z_from, True
        while z > z_to + 1e-9:
            z = max(z - dz_leg, z_to)
            tgt = p1 if at_p0 else p0
            self.feed(tgt[0], tgt[1], z, f)
            at_p0 = not at_p0
        if not at_p0:
            self.feed(p0[0], p0[1], z_to, f)


# -- estimation -------------------------------------------------------------
def move_time(m: dict, prev: list, machine=MACHINE) -> float:
    rapid = machine["rapid_mm_min"] / 60.0
    if m["t"] == "rapid":
        return max(abs(m["x"] - prev[0]), abs(m["y"] - prev[1]), abs(m["z"] - prev[2])) / rapid
    if m["t"] == "feed":
        return math.dist((m["x"], m["y"], m["z"]), prev) / (m["f"] / 60.0)
    if m["t"] == "arc":
        sweep = arc_sweep(("A", (m["x0"], m["y0"]), (m["x"], m["y"]), (m["cx"], m["cy"]), m["cw"]))
        rad = math.dist((m["x0"], m["y0"]), (m["cx"], m["cy"]))
        L = math.hypot(abs(sweep) * rad, m["z"] - m["z0"])
        return L / (m["f"] / 60.0)
    if m["t"] == "cycle":
        t = 0.0
        x, y = prev[0], prev[1]
        init_z = m["init_z"]
        cur_z = prev[2]
        for (px, py) in m["pts"]:
            t += max(abs(px - x), abs(py - y)) / rapid
            t += abs(cur_z - m["r"]) / rapid
            depth = m["r"] - m["z"]
            fv = m["f"] / 60.0
            if m["g"] == 83 and m["q"]:
                done = 0.0
                while done < depth - 1e-9:
                    start = max(done - PECK_CLEAR, 0.0)
                    nxt = min(done + m["q"], depth)
                    t += (done - start) / rapid if done > 0 else 0.0
                    t += (nxt - start) / fv
                    t += nxt / rapid  # retract to R
                    done = nxt
            else:
                t += depth / fv + depth / rapid
            if m.get("p"):
                t += m["p"]
            cur_z = init_z if m["ret"] == 98 else m["r"]
            t += abs(cur_z - m["r"]) / rapid
            x, y = px, py
        return t
    return 0.0


def estimate_ops(ops: list[dict], machine=MACHINE) -> dict:
    """Own cycle-time estimate (no acceleration model). Annotates each op with est_time_s."""
    total = cutting = rapid_t = 0.0
    prev = [0.0, 0.0, 25.0]
    last_tool = None
    tc = 0.0
    for op in ops:
        t_op = 0.0
        if op["tool"] != last_tool:
            tc += machine["tool_change_s"] + machine["spindle_start_s"]
            t_op += machine["tool_change_s"] + machine["spindle_start_s"]
            last_tool = op["tool"]
        for m in op["moves"]:
            dt = move_time(m, prev, machine)
            if m["t"] == "rapid":
                rapid_t += dt
            elif m["t"] != "comment":
                cutting += dt
            t_op += dt
            if m["t"] == "cycle":
                prev = [m["pts"][-1][0], m["pts"][-1][1], m["init_z"] if m["ret"] == 98 else m["r"]]
            elif m["t"] != "comment":
                prev = [m["x"], m["y"], m["z"]]
        op["est_time_s"] = round(t_op, 1)
        total += t_op
    return {"total_s": round(total, 1), "cutting_s": round(cutting, 1), "rapid_s": round(rapid_t, 1),
            "tool_change_s": round(tc, 1), "source": "native-estimate"}


def polyline(moves, start=(0.0, 0.0, 25.0), step=0.5):
    """Expand moves to (x, y, z, is_rapid) points (cycles expanded to plunges)."""
    out = [(*start, True)]
    pos = list(start)
    for m in moves:
        if m["t"] in ("rapid", "feed"):
            out.append((m["x"], m["y"], m["z"], m["t"] == "rapid"))
            pos = [m["x"], m["y"], m["z"]]
        elif m["t"] == "arc":
            pts = sample_arc((m["x0"], m["y0"]), (m["x"], m["y"]), (m["cx"], m["cy"]), m["cw"], step)
            n = len(pts) - 1
            for i, (x, y) in enumerate(pts[1:], 1):
                out.append((x, y, m["z0"] + (m["z"] - m["z0"]) * i / n, False))
            pos = [m["x"], m["y"], m["z"]]
        elif m["t"] == "cycle":
            for (px, py) in m["pts"]:
                out.append((px, py, pos[2], True))
                out.append((px, py, m["r"], True))
                out.append((px, py, m["z"], False))
                rz = m["init_z"] if m["ret"] == 98 else m["r"]
                out.append((px, py, rz, True))
                pos = [px, py, rz]
    return out
