"""Verification checks run alongside the stock sweep.

- gouge:           stock cut below the part (target floor) by > gouge_tol
- leftover:        stock left above the finished top by > general tolerance
- rapid_into_stock: a G0 move that removes material
- flat_plunge:     straight Z plunge of a flat/face mill > plunge_depth into solid material
- below_fixture:   tool enters the vise (jaws: bottom `vise_grip` mm of the stock on the
                   jaw faces; parallels: anything below the stock bottom)
- flute_length:    axial engagement deeper than the tool's flute length (warning)
- shank_collision: stock intersects the non-cutting shank envelope
- holder_collision: stock intersects the holder envelope
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from .gcode import FEED, RAPID, TOOLCHANGE, DWELL, Toolpath
from .stock import Stock, Tool
from .target import Target

MAX_EVENTS = 50


class Checker:
    """Collects verification findings while the toolpath is swept through the stock.

    Tracks fixture/vise crashes, envelope collisions, rapids into stock, flat plunges,
    flute length, gouges and leftover against the target. Lengths are in mm.
    """
    def __init__(self, feats: dict, stock: Stock, target: Target, tools: dict[int, Tool], tp: Toolpath,
                 gouge_tol: float = 0.02, leftover_tol: float | None = None, plunge_depth: float = 0.5,
                 vise_grip: float = 6.0, jaw_axis: str = "y", fixture_mode: str = "jaws",
                 xy_tol: float | None = None, tool_metadata: list[dict] | None = None):
        self.feats, self.stock, self.target, self.tools, self.tp = feats, stock, target, tools, tp
        self.gouge_tol = gouge_tol
        self.leftover_tol = leftover_tol if leftover_tol is not None else float(feats.get("general_tolerance_mm", 0.1))
        self.plunge_depth = plunge_depth
        s = feats["stock"]
        self.sx, self.sy = s["x"], s["y"]
        self.jaw_top = stock.z_bottom + vise_grip
        self.vise_grip = vise_grip
        self.jaw_axis = jaw_axis
        self.fixture_mode = fixture_mode
        self.xy_tol = stock.grid.cell if xy_tol is None else xy_tol
        self.gouge_first = np.full(stock.h.shape, -1, dtype=np.int64)
        self.events: dict[str, list] = {k: [] for k in ("rapid_into_stock", "flat_plunge", "below_fixture", "flute_length",
                                                          "shank_collision", "holder_collision")}
        self.counts = {k: 0 for k in self.events}
        self._seen: set = set()
        self.warnings: list[str] = []
        self.tool_metadata = list(tool_metadata or [])

    # ----------------------------------------------------------- helpers
    def _loc(self, i: int) -> dict:
        tp = self.tp
        prog, ln = int(tp.program[i]), int(tp.nc_line[i])
        return {"program": prog, "file": tp.files[prog], "nc_line": ln, "block": tp.source(prog, ln),
                "tool": int(tp.tool[i])}

    def _add(self, kind: str, i: int, **kw):
        key = (kind, int(self.tp.program[i]), int(self.tp.nc_line[i]))
        if key in self._seen:
            return
        self._seen.add(key)
        self.counts[kind] += 1
        if len(self.events[kind]) < MAX_EVENTS:
            ev = self._loc(i)
            ev.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in kw.items()})
            self.events[kind].append(ev)

    def _jaw_hit_fraction(self, p0, p1, r, cx, cy, hx, hy):
        """Return earliest fraction where a segment enters a vise jaw."""
        p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        d = p1 - p0
        if self.jaw_axis == "y":
            axis0, da, axis_lim = p0[1] - cy, d[1], hy + r
            lat0, dl, lat_lim = p0[0] - cx, d[0], hx + 75.0
        else:
            axis0, da, axis_lim = p0[0] - cx, d[0], hx + r
            lat0, dl, lat_lim = p0[1] - cy, d[1], hy + 75.0
        ts = [0.0, 1.0]
        for val, base, delta in ((axis_lim, axis0, da), (-axis_lim, axis0, da),
                                 (lat_lim, lat0, dl), (-lat_lim, lat0, dl),
                                 (self.jaw_top, p0[2], d[2])):
            if abs(delta) > 1e-12:
                t = (val - base) / delta
                if 0.0 < t < 1.0:
                    ts.append(float(t))
        ts = sorted(set(ts))
        for t in sorted(ts + [(a + b) * 0.5 for a, b in zip(ts, ts[1:])]):
            q = p0 + t * d
            if (q[2] < self.jaw_top - 1e-6 and
                    abs(lat0 + t * dl) < lat_lim + 1e-6 and
                    abs(axis0 + t * da) > axis_lim + 1e-6):
                return float(t)
        return None

    # ----------------------------------------------------------- per segment
    def _envelope_collision(self, i: int, p0, p1, tool: Tool):
        """Check a segment against optional shank and holder solids.

        The heightmap stores the highest material in each XY cell.  For each
        non-cutting cylindrical envelope we conservatively test the swept
        capsule and the union of its endpoint Z ranges.  This catches a holder
        entering stock during a diagonal move without changing the stock
        removal model or requiring a second 3-D solid kernel.
        """
        p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        lo_tip, hi_tip = float(min(p0[2], p1[2])), float(max(p0[2], p1[2]))
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        aa = dx * dx + dy * dy
        g = self.stock.grid
        for kind, diameter, z0, length in (
                ("shank_collision", tool.shank_diameter, tool.flute_length, tool.shank_length),
                ("holder_collision", tool.holder_diameter, tool.flute_length + tool.shank_length,
                 tool.holder_length)):
            if diameter is None or diameter <= 0 or length <= 0:
                continue
            r = diameter / 2.0
            ix0, ix1 = g.index_range(min(p0[0], p1[0]) - r, max(p0[0], p1[0]) + r, "x")
            iy0, iy1 = g.index_range(min(p0[1], p1[1]) - r, max(p0[1], p1[1]) + r, "y")
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            X = g.xs[ix0:ix1][None, :]
            Y = g.ys[iy0:iy1][:, None]
            cx, cy = X - p0[0], Y - p0[1]
            if aa < 1e-18:
                dist2 = cx * cx + cy * cy
            else:
                t = np.clip((cx * dx + cy * dy) / aa, 0.0, 1.0)
                ex, ey = cx - t * dx, cy - t * dy
                dist2 = ex * ex + ey * ey
            cover = dist2 <= r * r
            if not cover.any():
                continue
            # Material is a solid column from z_bottom through stock.h.  The
            # interval test is conservative for a segment whose tip changes Z.
            h = self.stock.h[iy0:iy1, ix0:ix1]
            low = lo_tip + z0
            high = hi_tip + z0 + length
            hit = cover & (h > low + 1e-6) & (self.stock.z_bottom < high - 1e-6)
            if not hit.any():
                continue
            iy, ix = np.argwhere(hit)[0]
            # Report the highest material cell first; this makes the event
            # useful for a setup sheet and stable across NumPy versions.
            ys, xs = np.nonzero(hit)
            best = int(np.argmax(h[ys, xs]))
            iy, ix = int(ys[best]), int(xs[best])
            self._add(kind, i, x=float(g.xs[ix0 + ix]), y=float(g.ys[iy0 + iy]),
                      z=float(min(h[iy, ix], high)), radius=float(r),
                      envelope_low_z=round(low, 3), material_top=float(h[iy, ix]))

    def pre_segment(self, i: int, p0, p1, kind: int, tool: Tool | None):
        """Check segment ``i`` (p0 -> p1) before it cuts: tool envelope, fixture/vise and
        other geometric checks. Tool changes, dwells and moves without a tool are skipped.
        """
        if kind in (TOOLCHANGE, DWELL) or tool is None:
            return
        self._envelope_collision(i, p0, p1, tool)
        r = tool.radius
        # --- fixture
        zlow = min(p0[2], p1[2])
        lowp = p0 if p0[2] <= p1[2] else p1
        cx, cy = (self.sx[0] + self.sx[1]) / 2, (self.sy[0] + self.sy[1]) / 2
        hx, hy = (self.sx[1] - self.sx[0]) / 2, (self.sy[1] - self.sy[0]) / 2
        over_stock = abs(lowp[0] - cx) < hx + r and abs(lowp[1] - cy) < hy + r
        if zlow < self.stock.z_bottom - 1e-6 and over_stock:
            self._add("below_fixture", i, x=float(lowp[0]), y=float(lowp[1]), z=float(zlow),
                      what="below stock bottom (parallels/table)")
        elif zlow < self.jaw_top - 1e-6:
            if self.fixture_mode == "plane":
                if over_stock:
                    self._add("below_fixture", i, x=float(lowp[0]), y=float(lowp[1]), z=float(zlow),
                              what=f"below vise top Z{self.jaw_top:.2f} over stock")
            else:
                hit_t = self._jaw_hit_fraction(p0, p1, r, cx, cy, hx, hy)
                if hit_t is not None:
                    hp = np.asarray(p0, dtype=float) + hit_t * (np.asarray(p1, dtype=float) - np.asarray(p0, dtype=float))
                    self._add("below_fixture", i, x=float(hp[0]), y=float(hp[1]), z=float(hp[2]),
                              what=f"tool enters vise jaw (jaws on +/-{self.jaw_axis.upper()} faces, top Z{self.jaw_top:.2f})")
    # --- flat end mill straight plunge into solid
        if kind == FEED and tool.is_flat and p1[2] < p0[2] - 1e-6 and math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-3:
            g = self.stock.grid
            rr = 0.5 * r
            ix0, ix1 = g.index_range(p1[0] - rr, p1[0] + rr, "x")
            iy0, iy1 = g.index_range(p1[1] - rr, p1[1] + rr, "y")
            if ix0 < ix1 and iy0 < iy1:
                win = self.stock.h[iy0:iy1, ix0:ix1]
                X = g.xs[ix0:ix1][None, :] - p1[0]
                Y = g.ys[iy0:iy1][:, None] - p1[1]
                m = X * X + Y * Y <= rr * rr
                if m.any():
                    depth = float((np.minimum(win[m], p0[2]) - p1[2]).max())
                    if depth > self.plunge_depth:
                        self._add("flat_plunge", i, x=float(p1[0]), y=float(p1[1]), z=float(p1[2]),
                                  depth_into_material=depth)

    def on_cut(self, i: int, kind: int, tool: Tool, p0, p1, res):
        """Record cut results for segment ``i``: first gouge segment per cell and rapids that remove stock.

        ``res`` is the stock sweep result ``(iy0, iy1, ix0, ix1, old, new)``.
        """
        iy0, iy1, ix0, ix1, old, new = res
        removed = old - new
        rmax = float(removed.max())
        if rmax <= 1e-9:
            return
        fl = self.target.floor[iy0:iy1, ix0:ix1]
        bad = (new < fl - self.gouge_tol)
        if bad.any():
            gf = self.gouge_first[iy0:iy1, ix0:ix1]
            gf[bad & (gf < 0)] = i
        if kind == RAPID and rmax > 0.01:
            iy, ix = np.unravel_index(int(removed.argmax()), removed.shape)
            g = self.stock.grid
            self._add("rapid_into_stock", i, x=float(g.xs[ix0 + ix]), y=float(g.ys[iy0 + iy]),
                      depth=rmax)
        if tool.flute_length > 0 and (removed > 1e-6).any():
            ch = removed > 1e-6
            eng = float(old[ch].max()) - min(p0[2], p1[2])
            if eng > tool.flute_length + 0.05:
                self._add("flute_length", i, engagement=eng, flute_length=tool.flute_length,
                          x=float(p1[0]), y=float(p1[1]))

    # ----------------------------------------------------------- final
    def finalize(self) -> tuple[dict, np.ndarray, np.ndarray]:
        """Build the final checks dict after all segments.

        Returns ``(checks, gouge_mask, leftover_mask)``; masks are boolean grids over the stock.
        """
        h, g = self.stock.h, self.stock.grid
        b = int(math.ceil(self.xy_tol / g.cell - 1e-9))
        size = 2 * b + 1
        top_hi = ndimage.maximum_filter(self.target.top, size=size, mode="nearest") if b else self.target.top
        floor_lo = ndimage.minimum_filter(self.target.floor, size=size, mode="nearest") if b else self.target.floor
        gouge = h < floor_lo - self.gouge_tol
        # A target height outside the part (or in a through feature) is only a
        # bookkeeping depth used by the stock sweep.  ``Target.floor`` is
        # -inf there, so comparing the stock against ``top`` would report all
        # uncut waste as leftover.  Restrict this check to cells that contain
        # finished material; gouge already uses the same floor map to avoid
        # penalising cuts through open regions.
        material = np.isfinite(self.target.floor)
        leftover = material & (h > top_hi + self.leftover_tol)
        cell_a = g.cell * g.cell

        gouge_regions = []
        lab, n = ndimage.label(gouge, structure=np.ones((3, 3)))
        depth = np.where(gouge, self.target.floor - h, 0.0)
        for k, sl in enumerate(ndimage.find_objects(lab), start=1):
            m = lab[sl] == k
            d = np.where(m, depth[sl], -1)
            iy, ix = np.unravel_index(int(d.argmax()), d.shape)
            firsts = self.gouge_first[sl][m]
            firsts = firsts[firsts >= 0]
            seg = int(firsts.min()) if firsts.size else -1
            reg = {"area_mm2": round(float(m.sum()) * cell_a, 2), "max_depth_mm": round(float(d.max()), 3),
                   "x": round(float(g.xs[sl[1].start + ix]), 2), "y": round(float(g.ys[sl[0].start + iy]), 2),
                   "z": round(float(h[sl][iy, ix]), 3), "first_segment": seg,
                   "feature": self.target.feature_at(sl[0].start + iy, sl[1].start + ix),
                   "part_floor_z": round(float(self.target.floor[sl][iy, ix]), 3)}
            if seg >= 0:
                reg.update(self._loc(seg))
            gouge_regions.append(reg)
        gouge_regions.sort(key=lambda r: (r["first_segment"] if r["first_segment"] >= 0 else 1 << 60))

        left_regions = []
        lab, n = ndimage.label(leftover, structure=np.ones((3, 3)))
        excess = np.where(leftover, h - self.target.top, 0.0)
        for k, sl in enumerate(ndimage.find_objects(lab), start=1):
            m = lab[sl] == k
            e = np.where(m, excess[sl], -1)
            iy, ix = np.unravel_index(int(e.argmax()), e.shape)
            ys, xs = np.nonzero(m)
            left_regions.append({
                "area_mm2": round(float(m.sum()) * cell_a, 2), "max_excess_mm": round(float(e.max()), 3),
                "x": round(float(g.xs[sl[1].start + ix]), 2), "y": round(float(g.ys[sl[0].start + iy]), 2),
                "bbox": [round(float(g.xs[sl[1].start + xs.min()]), 2), round(float(g.ys[sl[0].start + ys.min()]), 2),
                         round(float(g.xs[sl[1].start + xs.max()]), 2), round(float(g.ys[sl[0].start + ys.max()]), 2)],
                "feature": self.target.feature_at(sl[0].start + iy, sl[1].start + ix),
                "target_z": round(float(self.target.top[sl][iy, ix]), 3),
                "stock_z": round(float(h[sl][iy, ix]), 3)})
        left_regions.sort(key=lambda r: -r["area_mm2"])

        g_area = float(gouge.sum()) * cell_a
        l_area = float(leftover.sum()) * cell_a
        metadata_errors = [e for e in self.tool_metadata if e.get("severity") == "error"]
        checks = {
            "tool_metadata": {"ok": not metadata_errors, "count": len(self.tool_metadata),
                              "errors": metadata_errors, "warnings": [e for e in self.tool_metadata if e.get("severity") != "error"]},
            "gouge": {"ok": not gouge.any(), "tolerance_mm": self.gouge_tol, "area_mm2": round(g_area, 2),
                      "max_depth_mm": round(max([r["max_depth_mm"] for r in gouge_regions], default=0.0), 3),
                      "count": len(gouge_regions), "events": gouge_regions[:MAX_EVENTS]},
            "leftover": {"ok": l_area < 0.5, "tolerance_mm": self.leftover_tol, "area_mm2": round(l_area, 2),
                         "max_excess_mm": round(max([r["max_excess_mm"] for r in left_regions], default=0.0), 3),
                         "count": len(left_regions), "events": left_regions[:MAX_EVENTS]},
        }
        for k in ("rapid_into_stock", "flat_plunge", "below_fixture", "flute_length"):
            checks[k] = {"ok": self.counts[k] == 0, "count": self.counts[k], "events": self.events[k]}
        for k in ("shank_collision", "holder_collision"):
            checks[k] = {"ok": self.counts[k] == 0, "count": self.counts[k], "events": self.events[k],
                         "description": "non-cutting tool envelope intersects stock"}
        checks["below_fixture"].update({"mode": self.fixture_mode, "vise_top_z": round(self.jaw_top, 3),
                                        "jaw_axis": self.jaw_axis, "vise_grip_mm": self.vise_grip})
        checks["flat_plunge"]["max_depth_mm"] = self.plunge_depth
        checks["flute_length"]["severity"] = "warning"
        checks["xy_tolerance_band_mm"] = round(b * g.cell, 3)
        return checks, gouge, leftover
