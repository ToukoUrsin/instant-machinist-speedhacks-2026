"""Haas-style ISO G-code parser/interpreter for the Instant Machinist simulator.

Turns one or more NC programs into a flat list of linear segments (arcs and
canned cycles are expanded).  All output is in millimetres and mm/min, in the
work coordinate system (G54); positions are the tool tip.

Supported: G0/G1/G2/G3 (I/J/K or R, planes G17/G18/G19, helical), G4, G20/G21,
G28, G40-G43/G49 (comp/length offsets accepted, not modelled), G52, G53, G54-G59,
G54.1 Pn work offsets,
G73/G81/G82/G83/G84/G85/G86/G89 + G80, G90/G91, G90.1/G91.1, G94, G98/G99,
T#, M6, S, F, M0/M1/M2/M3/M4/M5/M8/M9/M30, comments, N numbers, O, %.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FEED, RAPID, DWELL, TOOLCHANGE = 0, 1, 2, 3
KIND_NAMES = {FEED: "feed", RAPID: "rapid", DWELL: "dwell", TOOLCHANGE: "toolchange"}

INCH = 25.4
ARC_TOL_MM = 0.01
CANNED_DELTA_MM = 1.27  # Haas setting 22 (0.050 in): G73 retract / G83 re-approach clearance
CANNED = {73, 81, 82, 83, 84, 85, 86, 89}

_COMMENT = re.compile(r"\([^)]*\)|;.*$")
_WORD = re.compile(r"([A-Z])\s*([+-]?(?:\d+\.?\d*|\.\d+))")


@dataclass
class Toolpath:
    """Flat segment arrays (N segments)."""
    p0: np.ndarray        # (N,3) start, mm
    p1: np.ndarray        # (N,3) end, mm
    kind: np.ndarray      # (N,) int: FEED/RAPID/DWELL/TOOLCHANGE
    tool: np.ndarray      # (N,) int T number active during segment (0 = none)
    feed: np.ndarray      # (N,) mm/min (0 for rapids)
    dwell: np.ndarray     # (N,) seconds (DWELL segments)
    nc_line: np.ndarray   # (N,) 1-based line number in its source file
    program: np.ndarray   # (N,) index into `files`
    files: list[str] = field(default_factory=list)
    lines: list[list[str]] = field(default_factory=list)  # raw source lines per file
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.kind)

    @property
    def rapid(self) -> np.ndarray:
        return self.kind == RAPID

    def source(self, program: int, nc_line: int) -> str:
        try:
            return self.lines[program][nc_line - 1].strip()
        except IndexError:
            return ""


class GCodeError(ValueError):
    pass


class _Interp:
    def __init__(self, home_z: float, home_xy: tuple[float, float] | None,
                 start_pos=None, work_offsets: dict[object, np.ndarray] | None = None):
        self.home_z = home_z
        self.home_xy = home_xy
        # Work offsets are machine-coordinate translations applied to absolute
        # programmed coordinates.  G54 is the zero/default frame; callers may
        # provide configured G54..G59 and G54.1 Pn values.  Keeping this table
        # outside the NC text mirrors a controller's offset page while
        # preserving the historical zero-offset behavior.
        self.work_offsets = work_offsets or {}
        self.work_offset = np.zeros(3, float)
        self.pos = np.array(start_pos if start_pos is not None else [0.0, 0.0, home_z], float)
        self.tool = 0
        self.out: list[tuple] = []  # (p0, p1, kind, tool, feed, dwell, line)
        self.warnings: list[str] = []
        self._warned: set[str] = set()
        self.reset_modal()

    def reset_modal(self):
        self.scale = 1.0          # G21
        # Fanuc/Haas G52 local work-coordinate shift, in machine mm.  The
        # simulator reports positions in the underlying G54 work system, so
        # absolute programmed coordinates are translated by this offset.
        self.local_offset = np.zeros(3, float)
        self.absolute = True      # G90
        self.arc_abs = False      # G91.1 (incremental IJK)
        self.plane = 17
        self.motion = 0
        self.last_linear = 0
        self.feed = 0.0
        self.pending_tool = None
        self.retract_initial = True  # G98
        self.cyc: dict[str, float] = {}
        self.cyc_initial_z = None

    # ---------------------------------------------------------------- utils
    def warn(self, key: str, msg: str):
        if key not in self._warned:
            self._warned.add(key)
            self.warnings.append(msg)

    def emit(self, p1, kind, line, feed=0.0, dwell=0.0):
        p1 = np.asarray(p1, float)
        self.out.append((self.pos.copy(), p1.copy(), kind, self.tool, feed, dwell, line))
        self.pos = p1.copy()

    def move(self, p1, rapid: bool, line: int):
        p1 = np.asarray(p1, float)
        if np.allclose(p1, self.pos, atol=1e-9):
            return
        if rapid:
            self.emit(p1, RAPID, line)
        else:
            if self.feed <= 0:
                self.warn(f"nofeed{line}", f"line {line}: feed move with F=0; assuming 100 mm/min")
            self.emit(p1, FEED, line, feed=self.feed if self.feed > 0 else 100.0)

    # ---------------------------------------------------------------- main
    def run_line(self, raw: str, line: int) -> bool:
        """Interpret one block. Returns False at program end."""
        s = _COMMENT.sub("", raw.upper()).strip()
        if not s:
            return True
        if s.startswith("/"):
            s = s[1:]
        if s.startswith("%"):
            return True
        words = _WORD.findall(s)
        if not words:
            return True
        g: list[float] = []
        m: list[int] = []
        v: dict[str, float] = {}
        for letter, num in words:
            if letter == "G":
                g.append(float(num))
            elif letter == "M":
                m.append(int(float(num)))
            elif letter in ("O", "N"):
                continue
            else:
                v[letter] = float(num)
        gi = [round(x, 1) for x in g]

        # --- modal settings first
        for code in gi:
            if code == 20:
                self.scale = INCH
            elif code == 21:
                self.scale = 1.0
        for code in gi:
            if code == 90:
                self.absolute = True
            elif code == 91:
                self.absolute = False
            elif code == 90.1:
                self.arc_abs = True
            elif code == 91.1:
                self.arc_abs = False
            elif code in (17, 18, 19):
                self.plane = int(code)
            elif code == 98:
                self.retract_initial = True
            elif code == 99:
                self.retract_initial = False
            elif code == 80:
                self.motion = self.last_linear
                self.cyc = {}
                self.cyc_initial_z = None
            elif code in (41, 42):
                self.warn("comp", f"line {line}: G{int(code)} cutter compensation is not modelled (path taken as programmed)")
            elif code in (93, 95):
                self.warn("feedmode", f"line {line}: G{int(code)} feed mode not supported; F treated as per-minute")
            elif code in (51, 68, 68.2, 43.4, 92, 10, 65):
                self.warn(f"g{code}", f"line {line}: G{code} not supported; ignored")
        if "F" in v:
            self.feed = v["F"] * self.scale
        if "T" in v:
            self.pending_tool = int(v["T"])

        nonmodal_axes = False
        # --- motion group
        for code in gi:
            if code in (0, 1, 2, 3):
                self.motion = int(code)
                if code in (0, 1):
                    self.last_linear = int(code)
            elif int(code) in CANNED and code == int(code):
                self.motion = int(code)
                self.cyc_initial_z = self.pos[2]

        # --- M6 tool change (Haas retracts Z to machine home first)
        if 6 in m:
            new = int(v["T"]) if "T" in v else self.pending_tool
            if new is None:
                self.warn(f"m6{line}", f"line {line}: M6 without T; ignored")
            else:
                if self.pos[2] < self.home_z:
                    self.emit([self.pos[0], self.pos[1], self.home_z], RAPID, line)
                self.tool = new
                self.emit(self.pos, TOOLCHANGE, line)

        # --- non-modal G codes that consume axis words
        if 4 in gi:
            p = v.get("P", v.get("X", 0.0))
            secs = p if ("." in _raw_word(s, "P") or "X" in v) else p / 1000.0
            self.emit(self.pos, DWELL, line, dwell=max(secs, 0.0))
            nonmodal_axes = True
        if 53 in gi:
            tgt = self.pos.copy()
            if "Z" in v:
                tgt[2] = self.home_z + v["Z"] * self.scale
            for i, a in ((0, "X"), (1, "Y")):
                if a in v and self.home_xy is not None:
                    tgt[i] = self.home_xy[i] + v[a] * self.scale
            self.move(tgt, True, line)
            nonmodal_axes = True
        if 28 in gi:
            mid = self._target(v)
            self.move(mid, True, line)
            home = self.pos.copy()
            if "Z" in v or not any(a in v for a in "XYZ"):
                home[2] = self.home_z
            for i, a in ((0, "X"), (1, "Y")):
                if (a in v or not any(b in v for b in "XYZ")) and self.home_xy is not None:
                    home[i] = self.home_xy[i]
            self.move(home, True, line)
            nonmodal_axes = True

        # G52 establishes a local work coordinate system.  It is modal until
        # cancelled with G52 X0 Y0 Z0 (omitted axes retain their prior shift).
        # G52 itself never causes a move, even when axis words are present.
        if 52 in gi:
            for i, a in enumerate("XYZ"):
                if a in v:
                    self.local_offset[i] = v[a] * self.scale
            nonmodal_axes = True

        # G54..G59 select the six standard work-coordinate systems.  Haas and
        # Fanuc also expose extended systems as G54.1 Pn.  A missing entry is
        # deliberately treated as the controller's zero setting, with a
        # diagnostic so a verifier never silently invents a datum.
        standard = [int(c) for c in gi if 54 <= c <= 59 and c == int(c)]
        ext = [c for c in gi if abs(c - 54.1) < 1e-9]
        if standard:
            code = standard[-1]
            self.work_offset = self.work_offsets.get(code, np.zeros(3, float)).copy()
            if code not in self.work_offsets and code != 54:
                self.warn(f"wcs-{code}", f"line {line}: G{code} selected with no configured work offset; using zero")
        if ext:
            p = int(v.get("P", 1))
            # Key extended systems by their P number; callers can also provide
            # a directly keyed (54.1, P) tuple for clarity.
            key = (54.1, p)
            off = self.work_offsets.get(key, self.work_offsets.get(p, np.zeros(3, float)))
            self.work_offset = np.asarray(off, float).copy()
            if key not in self.work_offsets and p not in self.work_offsets:
                self.warn(f"wcs-54.1-{p}", f"line {line}: G54.1 P{p} selected with no configured work offset; using zero")

        if not nonmodal_axes:
            has_axes = any(a in v for a in "XYZ")
            if self.motion in CANNED:
                cyc_on_line = any(int(c) in CANNED and c == int(c) for c in gi)
                for k in ("Z", "R", "Q", "P"):
                    if k in v:
                        self.cyc[k] = v[k]
                if "P" in v:
                    self.cyc["P_s"] = v["P"] if "." in _raw_word(s, "P") else v["P"] / 1000.0
                if any(a in v for a in "XY") or (cyc_on_line and has_axes):
                    self._canned(v, line)
            elif has_axes or (self.motion in (2, 3) and any(k in v for k in "IJK")):
                if self.motion in (0, 1):
                    self.move(self._target(v), self.motion == 0, line)
                else:
                    self._arc(v, line)

        for code in m:
            if code in (2, 30):
                return False
            if code in (98, 97):
                self.warn("sub", f"line {line}: M{code} subprogram calls not supported; ignored")
        return True

    def _target(self, v: dict) -> np.ndarray:
        t = self.pos.copy()
        for i, a in enumerate("XYZ"):
            if a in v:
                val = v[a] * self.scale
                t[i] = (val + self.work_offset[i] + self.local_offset[i]) if self.absolute else t[i] + val
        return t

    # ---------------------------------------------------------------- arcs
    def _arc(self, v: dict, line: int):
        end = self._target(v)
        ia, ib, ic = {17: (0, 1, 2), 18: (2, 0, 1), 19: (1, 2, 0)}[self.plane]
        off_letter = "IJK"
        start = self.pos.copy()
        sa, sb = start[ia], start[ib]
        ea, eb = end[ia], end[ib]
        cw = self.motion == 2
        if "R" in v:
            r = v["R"] * self.scale
            dx, dy = ea - sa, eb - sb
            chord = math.hypot(dx, dy)
            if chord < 1e-9:
                raise GCodeError(f"line {line}: R-format arc with identical start and end")
            if abs(r) < chord / 2 - 1e-3:
                self.warn(f"r{line}", f"line {line}: arc radius {abs(r):.4f} < half chord {chord/2:.4f}; clamped")
            h = math.sqrt(max(r * r - (chord / 2) ** 2, 0.0))
            sign = (1.0 if not cw else -1.0) * (1.0 if r > 0 else -1.0)
            ca = (sa + ea) / 2 + sign * h * (-dy / chord)
            cb = (sb + eb) / 2 + sign * h * (dx / chord)
            full = False
        else:
            oa = v.get(off_letter[ia], 0.0) * self.scale
            ob = v.get(off_letter[ib], 0.0) * self.scale
            if self.arc_abs:
                ca, cb = (oa + self.work_offset[ia] + self.local_offset[ia],
                          ob + self.work_offset[ib] + self.local_offset[ib])
            else:
                ca, cb = sa + oa, sb + ob
            full = abs(ea - sa) < 1e-6 and abs(eb - sb) < 1e-6
        rs = math.hypot(sa - ca, sb - cb)
        re_ = math.hypot(ea - ca, eb - cb)
        if rs < 1e-9:
            self.move(end, False, line)
            return
        if abs(rs - re_) > 0.05:
            self.warn(f"arcr{line}", f"line {line}: arc start/end radius differ by {abs(rs-re_):.3f} mm")
        a0 = math.atan2(sb - cb, sa - ca)
        a1 = math.atan2(eb - cb, ea - ca)
        sweep = a1 - a0
        if full:
            sweep = -2 * math.pi if cw else 2 * math.pi
        elif cw:
            if sweep >= 0:
                sweep -= 2 * math.pi
        else:
            if sweep <= 0:
                sweep += 2 * math.pi
        rmax = max(rs, re_)
        if rmax > ARC_TOL_MM:
            dth = 2 * math.acos(max(-1.0, 1 - ARC_TOL_MM / rmax))
            n = max(1, math.ceil(abs(sweep) / dth))
        else:
            n = 1
        n = min(n, 20000)
        k = np.arange(1, n + 1) / n
        th = a0 + sweep * k
        rr = rs + (re_ - rs) * k
        pts = np.empty((n, 3))
        pts[:, ia] = ca + rr * np.cos(th)
        pts[:, ib] = cb + rr * np.sin(th)
        pts[:, ic] = start[ic] + (end[ic] - start[ic]) * k
        pts[-1] = end
        for p in pts:
            self.move(p, False, line)

    # ---------------------------------------------------------- canned cycles
    def _canned(self, v: dict, line: int):
        code = self.motion
        if "Z" not in self.cyc or "R" not in self.cyc:
            raise GCodeError(f"line {line}: canned cycle G{code} without Z or R")
        reps = int(v.get("L", 1)) if "L" in v else 1
        init_z = self.cyc_initial_z if self.cyc_initial_z is not None else self.pos[2]
        for _ in range(max(reps, 0)):
            x, y = self.pos[0], self.pos[1]
            if self.absolute:
                x = v["X"] * self.scale + self.work_offset[0] + self.local_offset[0] if "X" in v else x
                y = v["Y"] * self.scale + self.work_offset[1] + self.local_offset[1] if "Y" in v else y
                r_z = self.cyc["R"] * self.scale + self.work_offset[2] + self.local_offset[2]
                bot = self.cyc["Z"] * self.scale + self.work_offset[2] + self.local_offset[2]
            else:
                x += v.get("X", 0.0) * self.scale
                y += v.get("Y", 0.0) * self.scale
                r_z = init_z + self.cyc["R"] * self.scale
                bot = r_z + self.cyc["Z"] * self.scale
            # position over hole at current height, then rapid to R
            self.move([x, y, self.pos[2]], True, line)
            self.move([x, y, r_z], True, line)
            q = abs(self.cyc.get("Q", 0.0)) * self.scale
            if code in (83, 73) and q > 1e-6:
                d = r_z
                while d > bot + 1e-9:
                    nxt = max(d - q, bot)
                    if code == 83:
                        if d < r_z:
                            self.move([x, y, d + CANNED_DELTA_MM], True, line)
                        self.move([x, y, nxt], False, line)
                        if nxt > bot + 1e-9:
                            self.move([x, y, r_z], True, line)
                    else:
                        self.move([x, y, nxt], False, line)
                        if nxt > bot + 1e-9:
                            self.move([x, y, nxt + CANNED_DELTA_MM], True, line)
                    d = nxt
            else:
                self.move([x, y, bot], False, line)
            if code in (82, 89) and self.cyc.get("P_s", 0) > 0:
                self.emit(self.pos, DWELL, line, dwell=self.cyc["P_s"])
            ret = max(init_z, r_z) if self.retract_initial else r_z
            self.move([x, y, ret], code not in (84, 85, 89), line)


def _raw_word(s: str, letter: str) -> str:
    mm = re.search(letter + r"\s*([+-]?(?:\d+\.?\d*|\.\d+))", s)
    return mm.group(1) if mm else ""


def _line_words(raw: str) -> list[tuple[str, str]]:
    """Return words from a block after comments, preserving numeric text."""
    return _WORD.findall(_COMMENT.sub("", raw.upper()))


def _sub_call(raw: str) -> tuple[int | None, int, bool, str]:
    """Extract M98/M99 call metadata.

    Returns (program number, repeat count, is_return, cleaned block).  Haas and
    Fanuc controllers commonly put M98 P1234 L2 on a block by itself.  We
    consume that block here so the regular motion interpreter cannot mistake
    P/L for canned-cycle parameters.
    """
    words = _line_words(raw)
    m_codes = {int(float(n)) for k, n in words if k == "M"}
    if 99 in m_codes:
        return None, 1, True, ""
    if 98 not in m_codes:
        return None, 1, False, raw
    p = next((int(float(n)) for k, n in words if k == "P"), None)
    l = next((int(float(n)) for k, n in words if k == "L"), 1)
    l = max(1, l)
    # Remove M98/P/L from a mixed block. A standalone call becomes empty.
    cleaned = " ".join(f"{k}{n}" for k, n in words if not (k == "M" and int(float(n)) == 98) and k not in {"P", "L"})
    return p, l, False, cleaned


def _program_ranges(lines: list[str]) -> tuple[dict[int, tuple[int, int]], tuple[int, int]]:
    """Find O-numbered subprogram ranges and the main range for one file."""
    labels: list[tuple[int, int]] = []
    for i, raw in enumerate(lines):
        for k, n in _line_words(raw):
            if k == "O":
                labels.append((int(float(n)), i))
                break
    if not labels:
        return {}, (0, len(lines))
    ranges: dict[int, tuple[int, int]] = {}
    for j, (num, start) in enumerate(labels):
        ranges[num] = (start + 1, labels[j + 1][1] if j + 1 < len(labels) else len(lines))
    # The first O block is the entry program; later O blocks are callable.
    main = (0, labels[1][1] if len(labels) > 1 else len(lines))
    return ranges, main


def parse_programs(paths_or_texts, home_z: float = 50.0, home_xy=None,
                   work_offsets: dict[object, tuple[float, float, float] | np.ndarray] | None = None) -> Toolpath:
    """Parse one or more programs (paths or raw text) run in sequence.

    M98 P#### [L###] calls an ``O####`` subprogram in the same source file.
    M99 returns from a subprogram. Calls are expanded with a bounded depth and
    repeat count, while source line numbers and the public Toolpath contract are
    retained. Undefined or recursive calls are reported as deterministic
    warnings rather than silently producing an incomplete path.

    home_z: work-coordinate Z of machine Z home (G53 Z0 / G28 / M6 retract).
    home_xy: work-coordinate XY of machine home, or None to leave XY unchanged on G28/G53.
    work_offsets: optional controller offset table. Keys 54..59 select G54..G59;
        an integer P or ``(54.1, P)`` tuple selects G54.1 Pn. Values are XYZ mm.
    """
    if isinstance(paths_or_texts, (str, Path)):
        paths_or_texts = [paths_or_texts]
    offsets = {k: np.asarray(v, float) for k, v in (work_offsets or {}).items()}
    it = _Interp(home_z, home_xy, work_offsets=offsets)
    files, all_lines, prog_idx = [], [], []
    sources: list[tuple[list[str], dict[int, tuple[int, int]], tuple[int, int]]] = []
    for pi, src in enumerate(paths_or_texts):
        if isinstance(src, Path) or (isinstance(src, str) and "\n" not in src and Path(src).exists()):
            text = Path(src).read_text(errors="replace")
            files.append(str(src))
        else:
            text = str(src)
            files.append(f"<program {pi}>")
        lines = text.splitlines()
        all_lines.append(lines)
        sources.append((lines, *_program_ranges(lines)))

    max_depth = 32
    max_calls = 10000
    call_count = 0

    def execute(pi: int, start: int, end: int, stack: tuple[tuple[int, int], ...], *, is_sub: bool = False) -> bool:
        nonlocal call_count
        lines, ranges, _ = sources[pi]
        i = start
        pct = 0
        while i < end:
            raw = lines[i]
            # A second % ends a standard wrapped program; an O label itself is
            # metadata and should never be sent through motion interpretation.
            if raw.strip().startswith("%"):
                pct += 1
                if pct >= 2:
                    return True
                i += 1
                continue
            pnum, repeat, is_return, cleaned = _sub_call(raw)
            if is_return:
                return True
            if pnum is not None:
                target = ranges.get(pnum)
                if target is None:
                    it.warn(f"sub-missing-{pnum}", f"line {i + 1}: M98 P{pnum} target not found")
                elif (pi, pnum) in stack:
                    it.warn("sub-cycle", f"line {i + 1}: recursive M98 P{pnum} call skipped")
                elif len(stack) >= max_depth:
                    it.warn("sub-depth", f"line {i + 1}: M98 call depth exceeds {max_depth}; call skipped")
                elif call_count + repeat > max_calls:
                    it.warn("sub-limit", f"line {i + 1}: M98 call limit {max_calls} exceeded; call skipped")
                else:
                    call_count += repeat
                    for _ in range(repeat):
                        execute(pi, target[0], target[1], stack + ((pi, pnum),), is_sub=True)
                # A mixed block may contain an independent motion command; run
                # its cleaned words after the call. Standalone M98 is empty.
                if not cleaned.strip():
                    i += 1
                    continue
                raw = cleaned
            try:
                if not it.run_line(raw, i + 1):
                    return False
            except GCodeError:
                raise
            except Exception as e:  # pragma: no cover - defensive
                raise GCodeError(f"{files[pi]} line {i + 1}: {e}: {lines[i].strip()}") from e
            i += 1
        return True

    for pi, (lines, ranges, main) in enumerate(sources):
        it.reset_modal()
        n0 = len(it.out)
        execute(pi, main[0], main[1], ())
        prog_idx += [pi] * (len(it.out) - n0)
    if it.out:
        p0 = np.array([o[0] for o in it.out])
        p1 = np.array([o[1] for o in it.out])
    else:
        p0 = p1 = np.zeros((0, 3))
    return Toolpath(
        p0=p0, p1=p1,
        kind=np.array([o[2] for o in it.out], dtype=np.int8),
        tool=np.array([o[3] for o in it.out], dtype=np.int32),
        feed=np.array([o[4] for o in it.out], dtype=float),
        dwell=np.array([o[5] for o in it.out], dtype=float),
        nc_line=np.array([o[6] for o in it.out], dtype=np.int32),
        program=np.array(prog_idx, dtype=np.int32),
        files=files, lines=all_lines, warnings=it.warnings,
    )
