"""Haas post-processor (metric) for the toolpath IR, CONTRACTS.md dialect."""
from __future__ import annotations

TOOL_NAMES = {"face_mill": "FACE MILL", "flat": "FLAT END MILL", "ball": "BALL END MILL",
              "spot_drill": "SPOT DRILL", "drill": "DRILL"}


def num(v: float) -> str:
    """Format a coordinate for Haas NC (3 decimals, trailing zeros stripped)."""
    s = f"{v:.3f}".rstrip("0")
    return "0." if s in ("-0.", "0.", ".") else s


def _clean(text: str) -> str:
    return text.upper().replace("(", "[").replace(")", "]")


def post(ops: list[dict], tools_doc: dict, part: dict, program: int = 1001, setup_name: str = "SETUP 1 TOP",
         clearance_z: float = 25.0) -> str:
    """Post operations to a Haas VF-2 NC program (G54 top centre, Z0 finished top); return the NC text."""
    tools = tools_doc["tools"]
    L: list[str] = ["%", f"O{program:05d} ({_clean(part.get('part_number', 'PART'))} {setup_name})"]
    L.append(f"({_clean(part.get('name', ''))} - {_clean(part.get('material', ''))})")
    L.append("(INSTANT MACHINIST NATIVE CAM - HAAS VF-2 - G54 = TOP CENTRE, Z0 = FINISHED TOP)")
    st = part["stock"]
    L.append(f"(STOCK X{num(st['x'][0])}..{num(st['x'][1])} Y{num(st['y'][0])}..{num(st['y'][1])} "
             f"Z{num(st['z'][0])}..{num(st['z'][1])})")
    used = []
    for op in ops:
        if op["tool"] not in used:
            used.append(op["tool"])
    L.append("(TOOL LIST)")
    for tn in used:
        t = tools[str(tn)]
        L.append(f"(T{tn} D{num(t['diameter'])} {TOOL_NAMES.get(t['type'], t['type'].upper())}"
                 f"{' ' + str(t['flutes']) + 'FL' if 'flutes' in t else ''} FLUTE LEN {num(t['flute_length'])})")
    L.append("G21 (METRIC)")
    L.append("G90 G17 G40 G49 G80 G94")
    cur_tool = None
    cur_rpm = None
    modal = {"g": None, "f": None}
    pos = [None, None, None]

    def motion(g: int, x=None, y=None, z=None, f=None):
        """Write a modal G0/G1 line with only changed axes and feed."""
        coords = []
        for i, (k, v) in enumerate((("X", x), ("Y", y), ("Z", z))):
            if v is not None and (pos[i] is None or abs(v - pos[i]) > 5e-4):
                coords.append(f"{k}{num(v)}")
                pos[i] = v
        if not coords:
            return
        words = []
        if modal["g"] != g:
            words.append(f"G{g}")
            modal["g"] = g
        words += coords
        if f is not None and g != 0 and modal["f"] != round(f):
            words.append(f"F{int(round(f))}")
            modal["f"] = round(f)
        L.append(" ".join(words))

    for op in ops:
        tn = op["tool"]
        L.append(f"({_clean(op['name'])} - {_clean(op['strategy'])} - T{tn} S{op['rpm']} F{op['feed']})")
        if tn != cur_tool:
            if cur_tool is not None:
                L.append("M9")
                L.append("G28 G91 Z0.")
                L.append("G90")
            L.append(f"T{tn} M6")
            first = next((m for m in op["moves"] if m["t"] in ("rapid", "feed", "arc", "cycle")), None)
            fx, fy = (first["pts"][0] if first["t"] == "cycle" else (first["x"], first["y"])) if first else (0.0, 0.0)
            L.append(f"G0 G90 G54 X{num(fx)} Y{num(fy)} S{op['rpm']} M3")
            L.append(f"G43 H{tn} Z{num(clearance_z)} M8")
            modal["g"], modal["f"] = 0, None
            pos[:] = [fx, fy, clearance_z]
            cur_tool = tn
        elif op["rpm"] != cur_rpm:
            L.append(f"S{op['rpm']} M3")
        cur_rpm = op["rpm"]
        for m in op["moves"]:
            t = m["t"]
            if t == "comment":
                L.append(f"({_clean(m['text'])})")
            elif t == "rapid":
                motion(0, m["x"], m["y"], m["z"])
            elif t == "feed":
                motion(1, m["x"], m["y"], m["z"], f=m["f"])
            elif t == "arc":
                i = m["cx"] - m["x0"]
                j = m["cy"] - m["y0"]
                g = 2 if m["cw"] else 3
                full = abs(m["x"] - m["x0"]) < 1e-6 and abs(m["y"] - m["y0"]) < 1e-6
                # always emit X Y (and Z if helical) so full circles are unambiguous
                words = [f"G{g}", f"X{num(m['x'])}", f"Y{num(m['y'])}"]
                if abs(m["z"] - m["z0"]) > 5e-4:
                    words.append(f"Z{num(m['z'])}")
                words += [f"I{num(i)}", f"J{num(j)}"]
                if modal["f"] != round(m["f"]):
                    words.append(f"F{int(round(m['f']))}")
                    modal["f"] = round(m["f"])
                modal["g"] = g
                pos[:] = [m["x"], m["y"], m["z"]]
                L.append(" ".join(words) + (" (FULL CIRCLE)" if full else ""))
            elif t == "cycle":
                g = m["g"]
                pts = m["pts"]
                head = [f"G{m['ret']}", f"G{g}", f"X{num(pts[0][0])}", f"Y{num(pts[0][1])}",
                        f"Z{num(m['z'])}", f"R{num(m['r'])}"]
                if m.get("q"):
                    head.append(f"Q{num(m['q'])}")
                if m.get("p"):
                    head.append(f"P{num(m['p'])}")
                head.append(f"F{int(round(m['f']))}")
                L.append(" ".join(head))
                for p in pts[1:]:
                    L.append(f"X{num(p[0])} Y{num(p[1])}")
                L.append("G80")
                modal["g"], modal["f"] = None, None
                z_after = m["init_z"] if m["ret"] == 98 else m["r"]
                pos[:] = [pts[-1][0], pts[-1][1], z_after]
    L.append("M9")
    L.append("M5")
    L.append("G28 G91 Z0.")
    L.append("G28 G91 Y0.")
    L.append("G90")
    L.append("M30")
    L.append("%")
    return "\n".join(L) + "\n"
