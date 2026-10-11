"""Minimal Haas G-code parser used for self-checks and tests (not the simulator)."""
from __future__ import annotations

import math
import re

WORD = re.compile(r"([A-Z])([-+]?\d*\.?\d*)")
VALID_LINE = re.compile(r"^(%|O\d{1,5}|([A-Z][-+]?\d*\.?\d*\s*)+)$")
HOME_Z = 200.0


class ParseError(ValueError):
    pass


def parse(text: str, tools: dict | None = None, step: float = 0.5):
    """Return list of points dicts: x, y, z, rapid, tool, line (arcs sampled, cycles expanded)."""
    pts = []
    pos = [0.0, 0.0, HOME_Z]
    modal_g = 0
    absolute = True
    tool = None
    pending_tool = None
    cyc = None  # active canned cycle params
    ret = 98
    init_z = pos[2]
    feed = None
    for ln, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"\([^)]*\)", "", raw).strip().upper()
        if not line:
            continue
        if not VALID_LINE.match(line):
            raise ParseError(f"line {ln}: bad syntax: {raw!r}")
        if line == "%" or line.startswith("O"):
            continue
        words = [(m.group(1), m.group(2)) for m in WORD.finditer(line.replace(" ", ""))]
        g_codes, vals, m_codes = [], {}, []
        for k, v in words:
            if v in ("", "+", "-"):
                raise ParseError(f"line {ln}: word {k} without value")
            if k == "G":
                g_codes.append(float(v))
            elif k == "M":
                m_codes.append(int(float(v)))
            else:
                if k in vals:
                    raise ParseError(f"line {ln}: duplicate {k}")
                vals[k] = float(v)
        if "T" in vals:
            pending_tool = int(vals["T"])
        if 6 in m_codes:
            tool = pending_tool
        if "F" in vals:
            feed = vals["F"]
        motion = None
        for g in g_codes:
            if g in (90,):
                absolute = True
            elif g == 91:
                absolute = False
            elif g in (98, 99):
                ret = int(g)
            elif g in (0, 1, 2, 3):
                motion = int(g)
                cyc = None
            elif g in (81, 82, 83, 73):
                motion = int(g)
                init_z = pos[2]
                cyc = {"g": int(g), "z": vals.get("Z"), "r": vals.get("R"), "q": vals.get("Q")}
            elif g == 80:
                cyc = None
                motion = None
            elif g == 28:
                motion = 28
        if motion == 28:
            if "Z" in vals:
                pos[2] = HOME_Z
                pts.append({"x": pos[0], "y": pos[1], "z": pos[2], "rapid": True, "tool": tool, "line": ln})
            continue
        if not absolute:
            continue
        if cyc is not None and (motion in (81, 82, 83, 73) or ("X" in vals or "Y" in vals)):
            if motion in (81, 82, 83, 73):
                if cyc["z"] is None or cyc["r"] is None:
                    raise ParseError(f"line {ln}: canned cycle without Z/R")
                if feed is None:
                    raise ParseError(f"line {ln}: canned cycle without feed")
            x, y = vals.get("X", pos[0]), vals.get("Y", pos[1])
            pts.append({"x": x, "y": y, "z": pos[2], "rapid": True, "tool": tool, "line": ln})
            pts.append({"x": x, "y": y, "z": cyc["r"], "rapid": True, "tool": tool, "line": ln})
            pts.append({"x": x, "y": y, "z": cyc["z"], "rapid": False, "tool": tool, "line": ln, "cycle": cyc["g"]})
            back = init_z if ret == 98 else cyc["r"]
            pts.append({"x": x, "y": y, "z": back, "rapid": True, "tool": tool, "line": ln})
            pos = [x, y, back]
            continue
        if motion is None:
            motion = modal_g
        else:
            modal_g = motion
        if not any(k in vals for k in "XYZ"):
            continue
        tgt = [vals.get("X", pos[0]), vals.get("Y", pos[1]), vals.get("Z", pos[2])]
        if motion in (1, 2, 3) and feed is None:
            raise ParseError(f"line {ln}: feed move without F")
        if motion in (0, 1):
            pts.append({"x": tgt[0], "y": tgt[1], "z": tgt[2], "rapid": motion == 0, "tool": tool, "line": ln})
        elif motion in (2, 3):
            if "I" not in vals and "J" not in vals:
                raise ParseError(f"line {ln}: arc without I/J")
            cx, cy = pos[0] + vals.get("I", 0.0), pos[1] + vals.get("J", 0.0)
            r0 = math.hypot(pos[0] - cx, pos[1] - cy)
            r1 = math.hypot(tgt[0] - cx, tgt[1] - cy)
            if abs(r0 - r1) > 0.01:
                raise ParseError(f"line {ln}: arc radius mismatch {r0:.4f} vs {r1:.4f}")
            a0 = math.atan2(pos[1] - cy, pos[0] - cx)
            a1 = math.atan2(tgt[1] - cy, tgt[0] - cx)
            sweep = a1 - a0
            if motion == 2:
                while sweep >= -1e-9:
                    sweep -= 2 * math.pi
            else:
                while sweep <= 1e-9:
                    sweep += 2 * math.pi
            n = max(2, int(abs(sweep) * r0 / step) + 1)
            for i in range(1, n + 1):
                a = a0 + sweep * i / n
                pts.append({"x": cx + r0 * math.cos(a), "y": cy + r0 * math.sin(a),
                            "z": pos[2] + (tgt[2] - pos[2]) * i / n, "rapid": False, "tool": tool, "line": ln})
        pos = tgt
    return pts
