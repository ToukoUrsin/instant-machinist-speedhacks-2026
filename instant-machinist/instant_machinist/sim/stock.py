"""Heightmap (single-dexel, Z-up) stock model and vectorised tool sweeps."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SLOPE_PIECE_DZ = 0.01  # mm: max Z change per piece when sweeping non-flat tools along ramps


@dataclass
class Tool:
    """Cutting tool geometry in mm (type, diameter, tip/taper angles, corner radius, flute and envelope)."""
    number: int
    type: str              # flat | face_mill | ball | bull | spot_drill | drill | chamfer
    diameter: float
    tip_angle: float = 118.0
    corner_radius: float = 0.0
    flute_length: float = 0.0
    # Included drill angle and axial taper angle are distinct dimensions.
    taper_angle: float = 0.0
    # Optional small-end diameter for a tapered cutter.  ``diameter`` remains
    # the bounding/body diameter used to select affected stock cells.
    tip_diameter: float | None = None
    # Optional non-cutting envelope dimensions, measured from the tool tip.
    # They are deliberately optional: older crib files remain valid and simply
    # do not request holder/shank collision verification.
    shank_diameter: float | None = None
    shank_length: float = 0.0
    holder_diameter: float | None = None
    holder_length: float = 0.0

    @property
    def radius(self) -> float:
        """Tool radius in mm."""
        return self.diameter / 2.0

    @property
    def is_flat(self) -> bool:
        """True for flat-bottom cutters (flat end mill, face mill, sharp-corner bull)."""
        return self.type in ("flat", "face_mill", "endmill", "end_mill") or (
            self.type == "bull" and self.corner_radius <= 0)

    def height(self, d: np.ndarray) -> np.ndarray:
        """Height of the cutting surface above the tip at radial distance d (d <= radius)."""
        r = self.radius
        t = self.type
        if t == "ball":
            return r - np.sqrt(np.maximum(r * r - d * d, 0.0))
        if t in ("drill", "spot_drill", "chamfer", "center_drill"):
            half = math.radians(max(self.tip_angle, 1.0)) / 2.0
            return d / math.tan(half)
        if t == "bull" and self.corner_radius > 0:
            cr = min(self.corner_radius, r)
            flat_r = r - cr
            e = np.maximum(d - flat_r, 0.0)
            return cr - np.sqrt(np.maximum(cr * cr - e * e, 0.0))
        if t == "taper" and self.taper_angle > 1e-9:
            tip_r = max(0.0, float(self.tip_diameter or 0.0) / 2.0)
            tan_a = math.tan(math.radians(self.taper_angle))
            # Inverse of the axial profile r(z) = r_tip + z*tan(alpha).
            return np.maximum(d - tip_r, 0.0) / tan_a
        return np.zeros_like(d)


SUPPORTED_TOOL_TYPES = frozenset({
    "flat", "face_mill", "endmill", "end_mill", "ball", "bull",
    "spot_drill", "drill", "chamfer", "center_drill", "taper",
})


def load_tools_diagnostics(path) -> tuple[dict[int, Tool], list[dict]]:
    """Load the tool crib and return deterministic metadata diagnostics.

    Invalid entries are excluded from the crib so callers never simulate with
    guessed geometry.  Diagnostics are data (rather than exceptions) because a
    verifier should produce an auditable report for incomplete shop metadata.
    File access and JSON syntax errors still raise: those are input/configuration
    failures, not an individual tool's metadata.
    """
    data = json.loads(Path(path).read_text())
    tools = data.get("tools", data) if isinstance(data, dict) else None
    events: list[dict] = []
    out: dict[int, Tool] = {}
    if not isinstance(tools, dict):
        return out, [{"tool": None, "severity": "error", "issue": "tools must be a JSON object"}]

    units = str(data.get("units", "mm")).strip().lower() if isinstance(data, dict) else "mm"

    def scale_for(raw):
        """Unit scale to mm: 25.4 for inch, else 1.0."""
        u = str(raw or units).strip().lower()
        return 25.4 if u in ("in", "inch", "inches") else 1.0

    def canonical_type(raw):
        """Normalise a tool type alias (e.g. 'end_mill', 'spot') to its canonical name."""
        key = str(raw or "flat").strip().lower().replace("-", "_").replace(" ", "_")
        return {
            "endmill": "flat", "end_mill": "flat", "flat_endmill": "flat",
            "flat_end_mill": "flat", "face": "face_mill", "facemill": "face_mill",
            "ball_endmill": "ball", "ball_end_mill": "ball",
            "bull_endmill": "bull", "bull_end_mill": "bull", "corner_radius": "bull",
            "chamfer_mill": "chamfer", "chamfer_tool": "chamfer",
            "spot": "spot_drill", "spotdrill": "spot_drill",
            "centre_drill": "center_drill", "tapered": "taper",
            "tapered_endmill": "taper", "tapered_end_mill": "taper",
            "taper_endmill": "taper",
        }.get(key, key)

    def number(value, name, n):
        """Parse a finite float for field ``name`` of tool ``n``; record an error event and return None if invalid."""
        try:
            x = float(value)
        except (TypeError, ValueError):
            events.append({"tool": n, "severity": "error", "issue": f"{name} must be numeric"})
            return None
        if not math.isfinite(x):
            events.append({"tool": n, "severity": "error", "issue": f"{name} must be finite"})
            return None
        return x

    for key, raw in tools.items():
        try:
            n = int(key)
        except (TypeError, ValueError):
            events.append({"tool": str(key), "severity": "error", "issue": "tool number must be an integer"})
            continue
        if not isinstance(raw, dict):
            events.append({"tool": n, "severity": "error", "issue": "tool entry must be an object"})
            continue
        typ = canonical_type(raw.get("type", raw.get("fusion_type", raw.get("tool_type", "flat"))))
        if typ not in SUPPORTED_TOOL_TYPES:
            events.append({"tool": n, "severity": "error", "issue": f"unsupported tool type: {typ!r}"})
            continue
        scale = scale_for(raw.get("units"))
        diameter = number(raw.get("diameter"), "diameter", n)
        if diameter is None or diameter <= 0:
            if diameter is not None:
                events.append({"tool": n, "severity": "error", "issue": "diameter must be > 0"})
            continue
        conical = typ in ("drill", "spot_drill", "chamfer", "center_drill")
        tip_default = 118.0 if conical else 0.0
        tip = number(raw.get("tip_angle", tip_default), "tip_angle", n)
        corner = number(raw.get("corner_radius", 0.0), "corner_radius", n)
        flute = number(raw.get("flute_length", 0.0), "flute_length", n)
        taper_value = raw.get("taper_angle", raw.get("taperAngle", 0.0))
        # Early Fusion exports put the axial half-angle in tip_angle and mark
        # the entry with fusion_type.  Keep drill tip-angle semantics intact.
        if "fusion_type" in raw and "taper_angle" not in raw and "taperAngle" not in raw and typ == "taper":
            taper_value = raw.get("tip_angle", 0.0)
        taper = number(taper_value, "taper_angle", n)
        tip_d = raw.get("tip_diameter", raw.get("tipDiameter"))
        tip_diameter = None if tip_d is None else number(tip_d, "tip_diameter", n)
        shank_d = raw.get("shank_diameter", raw.get("shankDiameter"))
        holder_d = raw.get("holder_diameter", raw.get("holderDiameter"))
        shank_l = raw.get("shank_length", raw.get("shankLength", 0.0))
        holder_l = raw.get("holder_length", raw.get("holderLength", 0.0))
        shank_diameter = None if shank_d is None else number(shank_d, "shank_diameter", n)
        holder_diameter = None if holder_d is None else number(holder_d, "holder_diameter", n)
        shank_length = number(shank_l, "shank_length", n)
        holder_length = number(holder_l, "holder_length", n)
        if (tip is None or corner is None or flute is None or taper is None or
                shank_length is None or holder_length is None or
                (tip_d is not None and tip_diameter is None) or
                (shank_d is not None and shank_diameter is None) or
                (holder_d is not None and holder_diameter is None)):
            continue
        invalid = False
        if conical and (tip <= 0 or tip >= 180):
            events.append({"tool": n, "severity": "error", "issue": "tip_angle must be between 0 and 180 degrees"})
            invalid = True
        if not conical and (tip < 0 or tip >= 180):
            events.append({"tool": n, "severity": "error", "issue": "tip_angle must be between 0 and 180 degrees"})
            invalid = True
        if taper < 0 or taper >= 89.9 or (typ == "taper" and taper <= 0):
            events.append({"tool": n, "severity": "error", "issue": "taper_angle must be in (0, 89.9) degrees for taper tools"})
            invalid = True
        if corner < 0 or corner > diameter / 2:
            events.append({"tool": n, "severity": "error", "issue": "corner_radius must be between 0 and radius"})
            invalid = True
        if tip_diameter is not None and (tip_diameter <= 0 or tip_diameter > diameter):
            events.append({"tool": n, "severity": "error", "issue": "tip_diameter must be in (0, diameter]"})
            invalid = True
        if flute < 0:
            events.append({"tool": n, "severity": "error", "issue": "flute_length must be >= 0"})
            invalid = True
        if shank_length < 0 or holder_length < 0:
            events.append({"tool": n, "severity": "error", "issue": "shank_length and holder_length must be >= 0"})
            invalid = True
        if shank_diameter is not None and shank_diameter <= 0:
            events.append({"tool": n, "severity": "error", "issue": "shank_diameter must be > 0 when provided"})
            invalid = True
        if holder_diameter is not None and holder_diameter <= 0:
            events.append({"tool": n, "severity": "error", "issue": "holder_diameter must be > 0 when provided"})
            invalid = True
        if invalid:
            continue
        if "flute_length" not in raw:
            events.append({"tool": n, "severity": "warning", "issue": "missing flute_length; flute check disabled"})
        out[n] = Tool(number=n, type=typ, diameter=diameter * scale, tip_angle=tip,
                      corner_radius=corner * scale, flute_length=flute * scale,
                      taper_angle=taper,
                      tip_diameter=None if tip_diameter is None else tip_diameter * scale,
                      shank_diameter=None if shank_diameter is None else shank_diameter * scale,
                      shank_length=shank_length * scale, holder_diameter=None if holder_diameter is None else holder_diameter * scale,
                      holder_length=holder_length * scale)
    return out, events


def load_tools(path) -> dict[int, Tool]:
    """Compatibility wrapper returning only valid tool geometry."""
    return load_tools_diagnostics(path)[0]


class Grid:
    """Regular XY grid of cell centres. x0/y0 = centre of cell [0,0]."""

    def __init__(self, x0: float, y0: float, cell: float, nx: int, ny: int):
        self.x0, self.y0, self.cell, self.nx, self.ny = float(x0), float(y0), float(cell), int(nx), int(ny)
        self.xs = self.x0 + self.cell * np.arange(self.nx)
        self.ys = self.y0 + self.cell * np.arange(self.ny)

    @classmethod
    def for_box(cls, xr, yr, cell: float) -> "Grid":
        """Grid of ``cell`` mm cells centred on the XY box ``xr`` x ``yr``."""
        nx = max(1, int(math.ceil((xr[1] - xr[0]) / cell - 1e-9)))
        ny = max(1, int(math.ceil((yr[1] - yr[0]) / cell - 1e-9)))
        # centre the grid on the box
        x0 = (xr[0] + xr[1]) / 2 - (nx - 1) * cell / 2
        y0 = (yr[0] + yr[1]) / 2 - (ny - 1) * cell / 2
        return cls(x0, y0, cell, nx, ny)

    def mesh(self):
        """``(X, Y)`` meshgrid of cell centres."""
        return np.meshgrid(self.xs, self.ys)

    def index_range(self, lo: float, hi: float, axis: str):
        """Cell index range ``[i0, i1)`` whose centres lie in ``[lo, hi]`` along ``axis`` ('x' or 'y')."""
        o, n = (self.x0, self.nx) if axis == "x" else (self.y0, self.ny)
        i0 = max(0, int(math.ceil((lo - o) / self.cell - 1e-9)))
        i1 = min(n, int(math.floor((hi - o) / self.cell + 1e-9)) + 1)
        return i0, i1

    def ij(self, x: float, y: float):
        """Nearest cell ``(row, col)`` for point ``(x, y)``."""
        return (int(round((y - self.y0) / self.cell)), int(round((x - self.x0) / self.cell)))

    def downsample(self, k: int) -> "Grid":
        """Coarser grid with cells ``k`` times larger covering the same area."""
        nx, ny = -(-self.nx // k), -(-self.ny // k)
        return Grid(self.x0 + (k - 1) * self.cell / 2, self.y0 + (k - 1) * self.cell / 2, self.cell * k, nx, ny)


class Stock:
    """Top-surface heightmap of the stock. Cells cut to the stock bottom = no material."""

    def __init__(self, grid: Grid, z_top: float, z_bottom: float):
        self.grid = grid
        self.z_top = float(z_top)
        self.z_bottom = float(z_bottom)
        self.h = np.full((grid.ny, grid.nx), self.z_top, dtype=np.float64)
        self._zmax = self.z_top
        self._ops = 0

    @classmethod
    def from_features(cls, feats: dict, cell: float = 0.25) -> "Stock":
        """Stock block from ``features.json`` stock box at ``cell`` mm resolution."""
        s = feats["stock"]
        return cls(Grid.for_box(s["x"], s["y"], cell), s["z"][1], s["z"][0])

    def heights_nan(self) -> np.ndarray:
        """Heights as float32 with cut-through cells (at stock bottom) set to NaN."""
        out = self.h.astype(np.float32)
        out[self.h <= self.z_bottom + 1e-6] = np.nan
        return out

    def zmax(self) -> float:
        """Cached highest stock Z, refreshed every 256 calls."""
        self._ops += 1
        if self._ops % 256 == 0:
            self._zmax = float(self.h.max())
        return self._zmax

    def sweep(self, p0, p1, tool: Tool):
        """Remove material swept by `tool` moving tip from p0 to p1 (straight line).

        Returns None if nothing in reach, else (iy0, iy1, ix0, ix1, old, new) where
        old/new are the affected window before/after (new is a view into self.h).
        """
        r = tool.radius
        x0, y0, z0 = float(p0[0]), float(p0[1]), float(p0[2])
        x1, y1, z1 = float(p1[0]), float(p1[1]), float(p1[2])
        if min(z0, z1) >= self.zmax():
            return None
        g = self.grid
        ix0, ix1 = g.index_range(min(x0, x1) - r, max(x0, x1) + r, "x")
        iy0, iy1 = g.index_range(min(y0, y1) - r, max(y0, y1) + r, "y")
        if ix0 >= ix1 or iy0 >= iy1:
            return None
        win = self.h[iy0:iy1, ix0:ix1]
        if min(z0, z1) >= win.max():
            return None
        X = g.xs[ix0:ix1][None, :]
        Y = g.ys[iy0:iy1][:, None]
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        a = dx * dx + dy * dy
        cx, cy = X - x0, Y - y0
        if tool.is_flat:
            if a < 1e-18:
                cover = cx * cx + cy * cy <= r * r
                zc = np.where(cover, min(z0, z1), np.inf)
            else:
                b = cx * dx + cy * dy            # t* * a
                c = cx * cx + cy * cy - r * r
                disc = b * b - a * c
                cover = disc >= 0
                sq = np.sqrt(np.maximum(disc, 0.0))
                r1 = (b - sq) / a
                r2 = (b + sq) / a
                cover &= (r2 >= 0.0) & (r1 <= 1.0)   # coverage interval overlaps the segment
                tt = np.clip(r1, 0.0, 1.0) if dz >= 0 else np.clip(r2, 0.0, 1.0)
                zc = np.where(cover, z0 + dz * tt, np.inf)
        else:
            zc = self._profile_sweep(cx, cy, dx, dy, dz, a, z0, tool)
        old = win.copy()
        np.minimum(win, np.maximum(zc, self.z_bottom), out=win)
        return iy0, iy1, ix0, ix1, old, win

    @staticmethod
    def _profile_sweep(cx, cy, dx, dy, dz, a, z0, tool: Tool):
        r = tool.radius
        if a < 1e-18:  # pure plunge: lowest point stamps
            d = np.sqrt(cx * cx + cy * cy)
            zlow = z0 + min(dz, 0.0)
            return np.where(d <= r, zlow + tool.height(np.minimum(d, r)), np.inf)
        n = 1 if abs(dz) < 1e-9 else min(400, int(math.ceil(abs(dz) / SLOPE_PIECE_DZ)))
        zc = np.full(np.broadcast(cx, cy).shape, np.inf)
        for k in range(n):
            ta, tb = k / n, (k + 1) / n
            zp = z0 + dz * min(ta, tb) if dz >= 0 else z0 + dz * tb
            # horizontal capsule from ta to tb at height zp
            pcx, pcy = cx - dx * ta, cy - dy * ta
            sdx, sdy = dx * (tb - ta), dy * (tb - ta)
            sa = sdx * sdx + sdy * sdy
            t = np.clip((pcx * sdx + pcy * sdy) / sa, 0.0, 1.0) if sa > 1e-18 else 0.0
            ex, ey = pcx - t * sdx, pcy - t * sdy
            d = np.sqrt(ex * ex + ey * ey)
            np.minimum(zc, np.where(d <= r, zp + tool.height(np.minimum(d, r)), np.inf), out=zc)
        return zc
