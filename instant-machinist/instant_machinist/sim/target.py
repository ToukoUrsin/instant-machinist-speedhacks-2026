"""Target (finished part) heightmaps on the stock grid.

Two maps are produced, both sampled at cell centres:
- `top`:   Z of the finished part's top surface (what should remain after machining).
           Where no part material exists (outside the profile, through holes) it is the
           depth the program must reach in a single setup (feature z_bottom).
- `floor`: lowest Z the tool may cut to without damaging the part.  -inf where there is
           no part material below (outside the part / through features); the vise check
           covers those regions.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .stock import Grid


@dataclass
class Target:
    top: np.ndarray
    floor: np.ndarray
    source: str
    label: np.ndarray | None = None        # (ny,nx) index into feature_ids: feature that defines `top`
    feature_ids: list | None = None

    def feature_at(self, iy: int, ix: int):
        if self.label is None or self.feature_ids is None:
            return None
        return self.feature_ids[int(self.label[iy, ix])]


def rounded_rect_mask(X, Y, cx, cy, w, h, r=0.0):
    r = max(0.0, min(r, w / 2, h / 2))
    ax, ay = np.abs(X - cx), np.abs(Y - cy)
    ex, ey = ax - (w / 2 - r), ay - (h / 2 - r)
    inside = (ax <= w / 2) & (ay <= h / 2)
    corner = (ex > 0) & (ey > 0)
    return inside & (~corner | (ex * ex + ey * ey <= r * r))


def shape_mask(X, Y, f: dict) -> np.ndarray:
    if "rect" in f:
        q = f["rect"]
        return rounded_rect_mask(X, Y, q.get("cx", 0.0), q.get("cy", 0.0), q["w"], q["h"], q.get("r", 0.0))
    if "circle" in f:
        q = f["circle"]
        d = q.get("d", 2 * q.get("r", 0.0))
        return (X - q.get("cx", 0.0)) ** 2 + (Y - q.get("cy", 0.0)) ** 2 <= (d / 2) ** 2
    if "polygon" in f or "points" in f:
        from matplotlib.path import Path as MPath
        pts = np.asarray(f.get("polygon", f.get("points")), float)
        return MPath(pts).contains_points(np.c_[X.ravel(), Y.ravel()]).reshape(X.shape)
    raise ValueError(f"feature {f.get('id')}: unsupported shape (need rect/circle/polygon)")


def from_features(feats: dict, grid: Grid) -> Target:
    X, Y = grid.mesh()
    stock_top = feats["stock"]["z"][1]
    zmin = feats.get("part_bbox", {}).get("z", [feats["stock"]["z"][0], 0])[0]
    top = np.full(X.shape, stock_top, float)
    floor = np.full(X.shape, -np.inf)
    through_mask = np.zeros(X.shape, bool)
    face = [f for f in feats["features"] if f["type"] == "face"]
    ids = [face[0].get("id", "face") if face else "stock_top"]
    label = np.zeros(X.shape, np.int16)
    if face:
        top[:] = min(f["z"] for f in face)

    def through(f):
        return bool(f.get("through")) or f.get("z_bottom", 0) <= zmin + 1e-6

    for f in feats["features"]:
        t = f["type"]
        if t == "face":
            continue
        if t == "profile":
            m = shape_mask(X, Y, f)
            if f.get("side", "outside") == "outside":
                m = ~m
        elif t in ("pocket", "slot", "step"):
            m = shape_mask(X, Y, f)
        elif t == "hole":
            m = np.zeros(X.shape, bool)
            r = f["d"] / 2
            for px, py in f["positions"]:
                m |= (X - px) ** 2 + (Y - py) ** 2 <= r * r
        else:
            continue
        zb = f["z_bottom"]
        ids.append(f.get("id", t))
        label[m & (zb <= top)] = len(ids) - 1
        np.minimum(top, np.where(m, zb, np.inf), out=top)
        if through(f):
            through_mask |= m
    floor = np.where(through_mask, -np.inf, top)
    return Target(top=top, floor=floor, source="features.json", label=label, feature_ids=ids)


def from_stl(stl_path, feats: dict, grid: Grid) -> Target:
    """Top-surface heightmap of part.stl by z-buffer rasterisation (= vertical raycast)."""
    import trimesh
    mesh = trimesh.load(str(stl_path), force="mesh")
    tri = np.asarray(mesh.triangles, float)  # (T,3,3)
    zmin = feats.get("part_bbox", {}).get("z", [float(tri[..., 2].min()), 0])[0]
    top = np.full((grid.ny, grid.nx), -np.inf)
    for t in tri:
        xs, ys = t[:, 0], t[:, 1]
        ix0, ix1 = grid.index_range(xs.min(), xs.max(), "x")
        iy0, iy1 = grid.index_range(ys.min(), ys.max(), "y")
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        X = grid.xs[ix0:ix1][None, :]
        Y = grid.ys[iy0:iy1][:, None]
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = t
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        l0 = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / den
        l1 = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / den
        l2 = 1 - l0 - l1
        e = -1e-9
        inside = (l0 >= e) & (l1 >= e) & (l2 >= e)
        z = l0 * z0 + l1 * z1 + l2 * z2
        win = top[iy0:iy1, ix0:ix1]
        np.maximum(win, np.where(inside, z, -np.inf), out=win)
    hit = np.isfinite(top)
    floor = np.where(hit, top, -np.inf)
    top = np.where(hit, top, zmin)
    return Target(top=top, floor=floor, source=str(stl_path))


def load_target(part_dir, grid: Grid, mode: str = "features") -> Target:
    part_dir = Path(part_dir)
    feats = json.loads((part_dir / "features.json").read_text())
    stl = part_dir / "part.stl"
    if mode == "stl" or (mode == "auto" and stl.exists() and not feats.get("features")):
        return from_stl(stl, feats, grid)
    return from_features(feats, grid)
