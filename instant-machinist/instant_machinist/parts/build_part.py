"""Build part.step / part.stl / drawing.png / drawing.pdf / preview.png from features.json.

Usage: .venv/bin/python -m instant_machinist.parts.build_part parts/sm-101
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.patches import Arc, Circle, Polygon  # noqa: E402

import cadquery as cq  # noqa: E402
import trimesh  # noqa: E402

# --------------------------------------------------------------------------- model


def _rounded_rect_solid(cx, cy, w, h, r, z_bottom, z_top, extra_top=0.0):
    z0, z1 = z_bottom, z_top + extra_top
    wp = cq.Workplane("XY").workplane(offset=z0).center(cx, cy)
    if r > 0 and abs(2 * r - min(w, h)) < 1e-6:  # full-round slot
        if w >= h:
            s = wp.slot2D(w, h, 0)
        else:
            s = wp.slot2D(h, w, 90)
        return s.extrude(z1 - z0)
    solid = wp.rect(w, h).extrude(z1 - z0)
    if r > 0:
        solid = solid.edges("|Z").fillet(r)
    return solid


def build_model(feat: dict) -> cq.Workplane:
    prof = next(f for f in feat["features"] if f["type"] == "profile")
    rc = prof["rect"]
    body = _rounded_rect_solid(rc["cx"], rc["cy"], rc["w"], rc["h"], rc["r"], prof["z_bottom"], prof["z_top"])
    for f in feat["features"]:
        if f["type"] == "pocket":
            rc = f["rect"]
            body = body.cut(_rounded_rect_solid(rc["cx"], rc["cy"], rc["w"], rc["h"], rc["r"], f["z_bottom"], f["z_top"], 1.0))
        elif f["type"] == "hole":
            zb = f["z_bottom"] - (1.0 if f.get("through") else 0.0)
            for x, y in f["positions"]:
                cyl = cq.Workplane("XY").workplane(offset=zb).center(x, y).circle(f["d"] / 2).extrude(f["z_top"] - zb + 1.0)
                body = body.cut(cyl)
    return body


# --------------------------------------------------------------------------- renderer (z-buffer, numpy)


def _camera(az_deg=-58.0, el_deg=30.0):
    az, el = math.radians(az_deg), math.radians(el_deg)
    d = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    f = -d
    right = np.cross(f, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, f)
    return d, right, up


def render_iso(mesh: trimesh.Trimesh, width_px: int, height_px: int, ss: int = 2, margin: float = 0.06):
    """Return (rgba float image HxWx4, edge segments in pixel coords [(N,2,2)])."""
    d, right, up = _camera()
    V = mesh.vertices
    u, v, z = V @ right, V @ up, V @ d
    W, H = width_px * ss, height_px * ss
    s = min(W * (1 - 2 * margin) / (u.max() - u.min()), H * (1 - 2 * margin) / (v.max() - v.min()))
    ox = W / 2 - s * (u.max() + u.min()) / 2
    oy = H / 2 + s * (v.max() + v.min()) / 2
    px, py = ox + s * u, oy - s * v

    zbuf = np.full((H, W), -np.inf)
    col = np.zeros((H, W, 3))
    n = mesh.face_normals
    L1 = np.array([0.35, -0.55, 1.0]); L1 /= np.linalg.norm(L1)
    L2 = np.array([-0.8, 0.3, 0.35]); L2 /= np.linalg.norm(L2)
    base = np.array([0.66, 0.71, 0.78])
    inten = 0.38 + 0.55 * np.clip(n @ L1, 0, 1) + 0.18 * np.clip(n @ L2, 0, 1)
    # slight cool tint on vertical walls, brighter tops
    cols = np.clip(base[None, :] * inten[:, None] + 0.05 * (n[:, 2:3] > 0.9), 0, 1)
    vis = (n @ d) > 1e-6
    for fi in np.nonzero(vis)[0]:
        a, b, c = mesh.faces[fi]
        xs = np.array([px[a], px[b], px[c]]); ys = np.array([py[a], py[b], py[c]]); zs = np.array([z[a], z[b], z[c]])
        x0, x1 = max(int(np.floor(xs.min())), 0), min(int(np.ceil(xs.max())), W - 1)
        y0, y1 = max(int(np.floor(ys.min())), 0), min(int(np.ceil(ys.max())), H - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-12:
            continue
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        w2 = 1 - w0 - w1
        m = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not m.any():
            continue
        zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        upd = m & (zz > sub)
        sub[upd] = zz[upd]
        col[y0:y1 + 1, x0:x1 + 1][upd] = cols[fi]

    alpha = np.isfinite(zbuf).astype(float)
    rgba = np.concatenate([col, alpha[..., None]], axis=2)
    rgba = rgba.reshape(height_px, ss, width_px, ss, 4).mean(axis=(1, 3))
    # un-premultiply colour where partially covered
    a = rgba[..., 3:4]
    rgba[..., :3] = np.where(a > 0, rgba[..., :3] / np.maximum(a, 1e-6), 1.0)

    # feature edges with z-buffer visibility test
    zpad = np.pad(zbuf, 1, constant_values=-np.inf)
    zmin = np.min(np.stack([zpad[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] for dy in (-1, 0, 1) for dx in (-1, 0, 1)]), axis=0)
    ang = mesh.face_adjacency_angles
    edges = mesh.face_adjacency_edges[ang > math.radians(28)]
    tol = 0.25
    segs = []
    for a_, b_ in edges:
        p0 = np.array([px[a_], py[a_], z[a_]]); p1 = np.array([px[b_], py[b_], z[b_]])
        L = max(int(np.hypot(*(p1[:2] - p0[:2]))), 2)
        t = np.linspace(0, 1, L + 1)
        P = p0[None] + t[:, None] * (p1 - p0)[None]
        ix = np.clip(P[:, 0].astype(int), 0, W - 1); iy = np.clip(P[:, 1].astype(int), 0, H - 1)
        ok = P[:, 2] >= zmin[iy, ix] - tol
        # split into runs
        i = 0
        while i < len(ok):
            if ok[i]:
                j = i
                while j + 1 < len(ok) and ok[j + 1]:
                    j += 1
                if j > i:
                    segs.append([P[i, :2] / ss, P[j, :2] / ss])
                i = j + 1
            else:
                i += 1
    return rgba, np.array(segs)


def save_preview(mesh, path: Path, size=1600):
    w, h = size, int(size * 0.75)
    rgba, segs = render_iso(mesh, w, h, ss=2)
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(rgba, extent=(0, w, h, 0), interpolation="bilinear")
    ax.add_collection(LineCollection(segs, colors=[(0.13, 0.16, 0.21)], linewidths=1.3, capstyle="round"))
    ax.set_xlim(0, w); ax.set_ylim(h, 0); ax.axis("off")
    fig.savefig(path, dpi=100, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------- drawing primitives (sheet mm)

THICK, THIN = 1.0, 0.45  # points
FS = 9.0  # dimension text, pt (~3.2 mm)
K = "black"


class Sheet:
    def __init__(self, ax):
        self.ax = ax

    def line(self, x0, y0, x1, y1, lw=THIN, ls="-", color=K, z=3):
        self.ax.plot([x0, x1], [y0, y1], color=color, lw=lw, ls=ls, solid_capstyle="butt", zorder=z)

    def chain(self, x0, y0, x1, y1):
        self.ax.plot([x0, x1], [y0, y1], color=K, lw=THIN * 0.9, dashes=(9, 2.5, 2, 2.5), zorder=2)

    def text(self, x, y, s, size=FS, ha="center", va="center", rot=0, weight="normal", bg=False, **kw):
        t = self.ax.text(x, y, s, fontsize=size, ha=ha, va=va, rotation=rot, weight=weight,
                         family="DejaVu Sans", zorder=6, **kw)
        if bg:
            t.set_bbox(dict(facecolor="white", edgecolor="none", pad=0.6))
        return t

    def arrow(self, tip, direction, length=3.2, width=1.05):
        d = np.asarray(direction, float); d /= np.linalg.norm(d)
        nrm = np.array([-d[1], d[0]])
        tip = np.asarray(tip, float)
        base = tip - d * length
        self.ax.add_patch(Polygon([tip, base + nrm * width / 2, base - nrm * width / 2], closed=True,
                                  facecolor=K, edgecolor=K, lw=0.2, zorder=5))

    def dim_linear(self, p1, p2, offset, text, orient="h", ext_from=(None, None), text_side=1):
        """Dimension between p1 and p2 (sheet). orient h: measures x, dim line at y=offset.
        orient v: measures y, dim line at x=offset."""
        gap, over = 1.2, 2.0
        if orient == "h":
            y = offset
            for p in (p1, p2):
                sgn = 1 if y > p[1] else -1
                if abs(y - p[1]) > gap:
                    self.line(p[0], p[1] + sgn * gap, p[0], y + sgn * over)
            self.line(p1[0], y, p2[0], y)
            self.arrow((p1[0], y), (p1[0] - p2[0], 0)); self.arrow((p2[0], y), (p2[0] - p1[0], 0))
            self.text((p1[0] + p2[0]) / 2, y + text_side * 0.9, text, va="bottom" if text_side > 0 else "top")
        else:
            x = offset
            for p in (p1, p2):
                sgn = 1 if x > p[0] else -1
                if abs(x - p[0]) > gap:
                    self.line(p[0] + sgn * gap, p[1], x + sgn * over, p[1])
            self.line(x, p1[1], x, p2[1])
            self.arrow((x, p1[1]), (0, p1[1] - p2[1])); self.arrow((x, p2[1]), (0, p2[1] - p1[1]))
            self.text(x - text_side * 0.9, (p1[1] + p2[1]) / 2, text, rot=90,
                      ha="right" if text_side > 0 else "left")

    def leader(self, tip, knee, text, shoulder=4.0, size=FS):
        """Leader with arrow at tip, line to knee, horizontal shoulder, then text."""
        tip, knee = np.asarray(tip, float), np.asarray(knee, float)
        self.line(*tip, *knee)
        self.arrow(tip, tip - knee)
        sgn = 1 if knee[0] >= tip[0] else -1
        end = knee + [sgn * shoulder, 0]
        self.line(*knee, *end)
        self.text(end[0] + sgn * 1.0, end[1], text, ha="left" if sgn > 0 else "right", va="center", size=size,
                  linespacing=1.35)

    def rrect(self, cx, cy, w, h, r, lw=THICK):
        x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
        if r > 0:
            self.line(x0 + r, y0, x1 - r, y0, lw); self.line(x0 + r, y1, x1 - r, y1, lw)
            self.line(x0, y0 + r, x0, y1 - r, lw); self.line(x1, y0 + r, x1, y1 - r, lw)
            for (ax_, ay_, a0) in ((x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270)):
                self.ax.add_patch(Arc((ax_, ay_), 2 * r, 2 * r, theta1=a0, theta2=a0 + 90, color=K, lw=lw, zorder=3))
        else:
            self.ax.add_patch(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=False, lw=lw, ec=K, zorder=3))

    def circle(self, x, y, r, lw=THICK, cm=True):
        self.ax.add_patch(Circle((x, y), r, fill=False, ec=K, lw=lw, zorder=3))
        if cm:
            e = r + 2.5
            self.chain(x - e, y, x + e, y); self.chain(x, y - e, x, y + e)

    def hatch_rect(self, x0, y0, x1, y1, pitch=2.2):
        segs = []
        for c in np.arange(x0 - (y1 - y0), x1 + pitch, pitch):  # lines y - y0 = x - c
            xa, xb = max(c, x0), min(c + (y1 - y0), x1)
            if xb > xa:
                segs.append([(xa, y0 + xa - c), (xb, y0 + xb - c)])
        self.ax.add_collection(LineCollection(segs, colors=K, linewidths=0.35, zorder=2))
        self.ax.add_patch(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=False, lw=THICK, ec=K, zorder=3))


# --------------------------------------------------------------------------- drawing


def make_drawing(feat: dict, mesh: trimesh.Trimesh, out_png: Path, out_pdf: Path, volume_mm3: float):
    SW, SH = 431.8, 279.4  # ANSI B landscape, mm
    fig = plt.figure(figsize=(SW / 25.4, SH / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, SW); ax.set_ylim(0, SH); ax.set_aspect("equal"); ax.axis("off")
    S = Sheet(ax)

    F = {f["id"]: f for f in feat["features"]}
    prof = next(f for f in feat["features"] if f["type"] == "profile")
    pockets = [f for f in feat["features"] if f["type"] == "pocket"]
    holes = [f for f in feat["features"] if f["type"] == "hole"]
    big_pocket = max(pockets, key=lambda f: f["rect"]["w"] * f["rect"]["h"])
    slot = min(pockets, key=lambda f: f["rect"]["w"] * f["rect"]["h"])
    thru_top = next(h for h in holes if h["z_top"] == 0)
    thru_floor = next(h for h in holes if h["z_top"] != 0)

    # border + zone ticks
    m = 8.0
    S.ax.add_patch(Polygon([(m, m), (SW - m, m), (SW - m, SH - m), (m, SH - m)], fill=False, lw=1.6, ec=K))
    S.ax.add_patch(Polygon([(m - 3, m - 3), (SW - m + 3, m - 3), (SW - m + 3, SH - m + 3), (m - 3, SH - m + 3)],
                           fill=False, lw=0.4, ec=K))
    for i in range(1, 8):
        x = m + i * (SW - 2 * m) / 8
        S.line(x, m - 3, x, m, 0.4); S.line(x, SH - m, x, SH - m + 3, 0.4)
    for i, lab in enumerate("87654321"):
        x = m + (i + 0.5) * (SW - 2 * m) / 8
        S.text(x, m - 1.5, lab, size=5.5); S.text(x, SH - m + 1.5, lab, size=5.5)
    for i in range(1, 4):
        y = m + i * (SH - 2 * m) / 4
        S.line(m - 3, y, m, y, 0.4); S.line(SW - m, y, SW - m + 3, y, 0.4)
    for i, lab in enumerate("ABCD"):
        y = m + (i + 0.5) * (SH - 2 * m) / 4
        S.text(m - 1.5, y, lab, size=5.5); S.text(SW - m + 1.5, y, lab, size=5.5)

    # ------------------------------------------------------------------ top view
    sc = 1.4
    CX, CY = 142.0, 186.0
    T = lambda x, y: (CX + sc * x, CY + sc * y)  # noqa: E731
    pr = prof["rect"]
    hw, hh = pr["w"] / 2, pr["h"] / 2
    S.rrect(*T(pr["cx"], pr["cy"]), sc * pr["w"], sc * pr["h"], sc * pr["r"])
    for p in pockets:
        r = p["rect"]
        S.rrect(*T(r["cx"], r["cy"]), sc * r["w"], sc * r["h"], sc * r["r"])
    for h in holes:
        for x, y in h["positions"]:
            S.circle(*T(x, y), sc * h["d"] / 2)
    # centre lines
    S.chain(*T(-hw - 6, 0), *T(-hw + 4, 0)); S.chain(*T(hw - 4, 0), *T(hw + 6, 0))
    S.chain(*T(0, -hh - 6), *T(0, hh + 6))
    S.chain(*T(-hw + 4, 0), *T(hw - 4, 0))
    sr = slot["rect"]
    S.chain(*T(sr["cx"] - sr["w"] / 2 - 3, sr["cy"]), *T(sr["cx"] + sr["w"] / 2 + 3, sr["cy"]))

    # overall + hole pattern dims (top / left)
    xs = sorted({p[0] for p in thru_top["positions"]}); ys = sorted({p[1] for p in thru_top["positions"]})
    top = T(0, hh)[1]
    S.dim_linear(T(xs[0], ys[-1]), T(xs[-1], ys[-1]), top + 9, f"{xs[-1] - xs[0]:g}")
    # overall width: extension lines from true extremes (tangent edges)
    S.line(*T(-hw, hh - pr["r"] + 0.5), T(-hw, 0)[0], top + 21, THIN)
    S.line(*T(hw, hh - pr["r"] + 0.5), T(hw, 0)[0], top + 21, THIN)
    S.line(T(-hw, 0)[0], top + 19, T(hw, 0)[0], top + 19)
    S.arrow((T(-hw, 0)[0], top + 19), (-1, 0)); S.arrow((T(hw, 0)[0], top + 19), (1, 0))
    S.text(CX, top + 19.9, f"{pr['w']:g}", va="bottom")

    left = T(-hw, 0)[0]
    S.dim_linear(T(xs[0], ys[0]), T(xs[0], ys[-1]), left - 12, f"{ys[-1] - ys[0]:g}", orient="v")
    S.line(T(-hw + pr["r"] - 0.5, -hh)[0], T(0, -hh)[1], left - 26, T(0, -hh)[1])
    S.line(T(-hw + pr["r"] - 0.5, hh)[0], T(0, hh)[1], left - 26, T(0, hh)[1])
    S.line(left - 24, T(0, -hh)[1], left - 24, T(0, hh)[1])
    S.arrow((left - 24, T(0, -hh)[1]), (0, -1)); S.arrow((left - 24, T(0, hh)[1]), (0, 1))
    S.text(left - 24.9, CY, f"{pr['h']:g}", rot=90, ha="right")

    # pocket internal dims
    br = big_pocket["rect"]
    S.dim_linear(T(br["cx"] - br["w"] / 2, 12), T(br["cx"] + br["w"] / 2, 12), T(0, 12)[1], f"{br['w']:g}")
    S.dim_linear(T(-27, br["cy"] - br["h"] / 2), T(-27, br["cy"] + br["h"] / 2), T(-27, 0)[0], f"{br['h']:g}",
                 orient="v", text_side=-1)
    # Ø8 pair spacing inside pocket
    fx = sorted(p[0] for p in thru_floor["positions"])
    fy = thru_floor["positions"][0][1]
    S.dim_linear(T(fx[0], fy - thru_floor["d"] / 2 - 0.6), T(fx[1], fy - thru_floor["d"] / 2 - 0.6), T(0, -11)[1],
                 f"{fx[1] - fx[0]:g}", text_side=1)
    # slot location from centre line
    S.line(*T(sr["cx"] + sr["w"] / 2 + 4, sr["cy"]), *T(40, sr["cy"]))
    S.line(T(38, 0)[0], T(38, 0)[1], T(38, 0)[0], T(38, sr["cy"])[1])
    S.arrow(T(38, 0), (0, 1)); S.arrow(T(38, sr["cy"]), (0, -1))
    S.text(T(38, 0)[0] + 0.9, T(0, sr["cy"] / 2)[1], f"{abs(sr['cy']):g}", rot=90, ha="left")

    # leaders
    a45 = math.radians(45)
    hx, hy = xs[-1], ys[-1]
    rr = thru_top["d"] / 2
    S.leader(T(hx + rr * math.cos(a45), hy + rr * math.sin(a45)), T(66, 37),
             f"{len(thru_top['positions'])}X Ø{thru_top['d']:g} THRU")
    rr8 = thru_floor["d"] / 2
    ang = math.radians(32)
    S.leader(T(fx[1] + rr8 * math.cos(ang), fy + rr8 * math.sin(ang)), T(66, 23),
             f"{len(thru_floor['positions'])}X Ø{thru_floor['d']:g} THRU\nFROM POCKET FLOOR")
    # R8 (outer corners)
    c = (-hw + pr["r"], -hh + pr["r"])
    a = math.radians(225)
    S.leader(T(c[0] + pr["r"] * math.cos(a), c[1] + pr["r"] * math.sin(a)), T(-66, -47), f"R{pr['r']:g} TYP", shoulder=3)
    # R6 (pocket corners)
    c = (br["cx"] - br["w"] / 2 + br["r"], br["cy"] + br["h"] / 2 - br["r"])
    a = math.radians(135)
    S.leader(T(c[0] + br["r"] * math.cos(a), c[1] + br["r"] * math.sin(a)), T(-37, 23),
             f"R{br['r']:g} TYP", shoulder=3)
    # slot note
    c = (sr["cx"] + sr["w"] / 2 - sr["r"], sr["cy"])
    a = math.radians(-50)
    S.leader(T(c[0] + sr["r"] * math.cos(a), c[1] + sr["r"] * math.sin(a)), T(30, -50),
             f"SLOT {sr['w']:g} X {sr['h']:g}, R{sr['r']:g} FULL\n{abs(slot['z_bottom']):g} DEEP")

    # cutting plane A-A (y = 0)
    for sgn in (-1, 1):
        x_out = T(sgn * (hw + 4.5), 0)[0]
        x_in = T(sgn * (hw - 3), 0)[0]
        S.line(x_out, CY, x_in, CY, lw=1.9)
        S.line(x_out, CY, x_out, CY + 6.5, lw=1.0)
        S.arrow((x_out, CY + 8.5), (0, 1), length=3.4, width=1.6)
        S.text(x_out, CY + 13.0, "A", size=12, weight="bold")
    S.text(CX, T(0, -hh)[1] - 22, "TOP VIEW", size=10, weight="bold")

    # ------------------------------------------------------------------ section A-A
    zt, zb = prof["z_top"], prof["z_bottom"]
    SY = 92.0  # sheet y of z=0
    Z = lambda x, zz: (CX + sc * x, SY + sc * zz)  # noqa: E731
    pz = big_pocket["z_bottom"]
    bx0, bx1 = br["cx"] - br["w"] / 2, br["cx"] + br["w"] / 2
    hz = thru_floor["z_top"]
    hr = thru_floor["d"] / 2
    blocks = [(-hw, zb, bx0, zt), (bx1, zb, hw, zt)]
    cuts = sorted([bx0, fx[0] - hr, fx[0] + hr, fx[1] - hr, fx[1] + hr, bx1])
    for i in range(0, len(cuts) - 1, 2):
        blocks.append((cuts[i], zb, cuts[i + 1], pz))
    for (x0, z0, x1, z1) in blocks:
        S.hatch_rect(*Z(x0, z0), *Z(x1, z1))
    # visible lines beyond the plane: pocket back-wall corner tangents & hole far walls already coincide
    for xx in (bx0 + br["r"], bx1 - br["r"]):
        S.line(*Z(xx, pz), *Z(xx, zt), lw=THIN)
    S.line(*Z(bx0 + br["r"], zt), *Z(bx1 - br["r"], zt), lw=THICK)  # far pocket rim (beyond plane)
    S.chain(*Z(0, zt + 4), *Z(0, zb - 4))
    for x in fx:
        S.chain(*Z(x, hz + 3), *Z(x, zb - 4))
    # dims
    S.dim_linear(Z(hw, zt), Z(hw, zb), Z(hw + 9, 0)[0], f"{zt - zb:g}", orient="v", text_side=-1)
    S.line(*Z(bx0 + 1.0, zt), *Z(-4, zt))
    S.line(Z(-6, 0)[0], Z(0, zt)[1], Z(-6, 0)[0], Z(0, pz)[1])
    S.arrow(Z(-6, zt), (0, 1)); S.arrow(Z(-6, pz), (0, -1))
    S.text(Z(-6, 0)[0] - 0.9, Z(0, pz / 2)[1], f"{zt - pz:g}", rot=90, ha="right")
    S.text(CX, Z(0, zb)[1] - 12, "SECTION A-A", size=10, weight="bold")
    S.text(CX, Z(0, zb)[1] - 17, f"SCALE 1.4 : 1", size=8)

    # ------------------------------------------------------------------ isometric
    ix0, iy0, iw, ih = 268.0, 118.0, 150.0, 140.0
    rgba, segs = render_iso(mesh, 1200, int(1200 * ih / iw), ss=2, margin=0.04)
    iax = fig.add_axes([ix0 / SW, iy0 / SH, iw / SW, ih / SH])
    iax.imshow(rgba, extent=(0, rgba.shape[1], rgba.shape[0], 0), interpolation="bilinear")
    iax.add_collection(LineCollection(segs, colors=[(0.1, 0.12, 0.16)], linewidths=0.55, capstyle="round"))
    iax.set_xlim(0, rgba.shape[1]); iax.set_ylim(rgba.shape[0], 0); iax.axis("off")
    S.text(ix0 + iw / 2, iy0 - 2, "ISOMETRIC VIEW", size=10, weight="bold")
    S.text(ix0 + iw / 2, iy0 - 7, "SCALE: NONE  (REFERENCE ONLY)", size=8)

    # ------------------------------------------------------------------ notes
    nx, ny = 268.0, 100.0
    notes = [
        "NOTES:",
        f"1. MATERIAL: {feat['material'].upper()}.",
        "2. ALL DIMENSIONS IN MILLIMETERS.",
        f"3. UNLESS OTHERWISE SPECIFIED, TOLERANCE ±{feat['general_tolerance_mm']:g}.",
        f"4. SURFACE FINISH Ra {feat['surface_finish_ra_um']:g} µm ALL MACHINED SURFACES.",
        "5. BREAK ALL SHARP EDGES 0.2-0.4 X 45°. DEBURR.",
        "6. CLEAN, NO MARKING ON A-SURFACE (TOP).",
    ]
    for i, n in enumerate(notes):
        S.text(nx, ny - i * 4.3, n, size=7.6, ha="left", va="top", weight="bold" if i == 0 else "normal")

    # ------------------------------------------------------------------ title block (bottom-right)
    x0, x1, y0, y1 = 252.0, SW - m, m, 60.0
    def box(a, b, c, d, lw=0.8):
        S.ax.add_patch(Polygon([(a, b), (c, b), (c, d), (a, d)], fill=False, lw=lw, ec=K, zorder=4))
    def cell(a, b, c, d, label, value, vsize=8.5, vweight="normal"):
        box(a, b, c, d)
        S.text(a + 1.2, d - 1.2, label, size=5.2, ha="left", va="top", color="#333")
        S.text((a + c) / 2 if vsize > 9 else a + 1.6, b + (d - b) * 0.38, value, size=vsize,
               ha="center" if vsize > 9 else "left", va="center", weight=vweight)
    box(x0, y0, x1, y1, lw=1.4)
    xm = x0 + 66
    # left column
    rows = [(y1 - 13, y1), (y1 - 22, y1 - 13), (y1 - 31, y1 - 22), (y1 - 40, y1 - 31), (y0, y1 - 40)]
    box(x0, rows[0][0], xm, rows[0][1])
    S.text(x0 + 1.5, y1 - 1.4, "UNLESS OTHERWISE SPECIFIED:", size=5.4, ha="left", va="top", weight="bold")
    S.text(x0 + 1.5, y1 - 4.6, f"DIMENSIONS ARE IN MILLIMETERS\nTOLERANCES: ±{feat['general_tolerance_mm']:g}   ANGLES: ±0.5°\n"
           f"SURFACE FINISH: Ra {feat['surface_finish_ra_um']:g} µm",
           size=5.6, ha="left", va="top", linespacing=1.3)
    xd = x0 + 42
    cell(x0, rows[1][0], xd, rows[1][1], "DRAWN", "M. OKAFOR"); cell(xd, rows[1][0], xm, rows[1][1], "DATE", "2026-10-11", vsize=7)
    cell(x0, rows[2][0], xd, rows[2][1], "CHECKED", "R. LINDQVIST"); cell(xd, rows[2][0], xm, rows[2][1], "DATE", "2026-10-11", vsize=7)
    cell(x0, rows[3][0], xm, rows[3][1], "MATERIAL", feat["material"].upper(), vsize=8)
    cell(x0, rows[4][0], xm, rows[4][1], "FINISH", f"Ra {feat['surface_finish_ra_um']:g} µm / BREAK SHARP EDGES", vsize=7)
    # right column
    box(xm, y1 - 16, x1, y1)
    S.text((xm + x1) / 2, y1 - 6.2, "NORTHWIND ROBOTICS", size=14, weight="bold")
    S.text((xm + x1) / 2, y1 - 12.2, "PRECISION MECHANICAL ENGINEERING", size=5.6, color="#333")
    cell(xm, y1 - 30, x1, y1 - 16, "TITLE", "SENSOR MOUNT PLATE", vsize=13, vweight="bold")
    r3 = (y1 - 41, y1 - 30)
    box(xm, r3[0], xm + 14, r3[1]); S.text(xm + 1.2, r3[1] - 1.2, "SIZE", size=5.2, ha="left", va="top", color="#333")
    S.text(xm + 7, r3[0] + 4, "B", size=11, weight="bold")
    box(xm + 14, r3[0], x1 - 16, r3[1]); S.text(xm + 15.2, r3[1] - 1.2, "DWG NO. / PART NO.", size=5.2, ha="left", va="top", color="#333")
    S.text((xm + 14 + x1 - 16) / 2, r3[0] + 4.2, feat["part_number"], size=13, weight="bold")
    box(x1 - 16, r3[0], x1, r3[1]); S.text(x1 - 14.8, r3[1] - 1.2, "REV", size=5.2, ha="left", va="top", color="#333")
    S.text(x1 - 8, r3[0] + 4.2, "A", size=13, weight="bold")
    r4 = (y0, y1 - 41)
    xs4 = [xm, xm + 22, xm + 42, xm + 60, xm + 84, x1]
    labels = [("SCALE", "1.4 : 1"), ("UNITS", feat["units"]), ("QTY", str(feat["quantity"])),
              ("WEIGHT", f"{volume_mm3 * 2.70e-3 / 1000:.2f} kg"), ("SHEET", "1 OF 1")]
    for (a, b), (lab, val) in zip(zip(xs4[:-1], xs4[1:]), labels):
        box(a, r4[0], b, r4[1]); S.text(a + 1.2, r4[1] - 1.2, lab, size=5.2, ha="left", va="top", color="#333")
        S.text((a + b) / 2, r4[0] + 4.6, val, size=8.5)
    # third-angle projection symbol in last cell area (above sheet cell)
    # put it in a small box left of title block
    sx, sy = x0 - 30, y0 + 4
    box(sx - 2, y0, x0, y0 + 16, lw=0.8)
    S.text(sx + 12, y0 + 14.2, "THIRD ANGLE", size=4.8, va="top")
    cx_, cy_ = sx + 18, sy + 4
    S.ax.add_patch(Circle((cx_, cy_), 3.0, fill=False, lw=0.6, ec=K)); S.ax.add_patch(Circle((cx_, cy_), 1.4, fill=False, lw=0.6, ec=K))
    S.ax.add_patch(Polygon([(sx + 2, cy_ - 1.6), (sx + 10, cy_ - 3.0), (sx + 10, cy_ + 3.0), (sx + 2, cy_ + 1.6)],
                           fill=False, lw=0.6, ec=K))

    # revision block (top-right)
    rx0, rx1, ry1 = SW - m - 110, SW - m, SH - m
    box(rx0, ry1 - 14, rx1, ry1, lw=1.0)
    box(rx0, ry1 - 5, rx1, ry1, lw=0.6)
    S.text((rx0 + rx1) / 2, ry1 - 2.5, "REVISIONS", size=6.5, weight="bold")
    cols = [rx0, rx0 + 12, rx0 + 80, rx1]
    for a in cols[1:-1]:
        S.line(a, ry1 - 14, a, ry1 - 5, 0.6)
    S.text(rx0 + 6, ry1 - 9.5, "A", size=7); S.text(rx0 + 14, ry1 - 9.5, "INITIAL RELEASE", size=7, ha="left")
    S.text((cols[2] + rx1) / 2, ry1 - 9.5, "2026-10-11", size=7)

    fig.savefig(out_png, dpi=2400 / (SW / 25.4), facecolor="white")
    fig.savefig(out_pdf, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------- main


def main(part_dir: str) -> None:
    d = Path(part_dir)
    feat = json.loads((d / "features.json").read_text())
    model = build_model(feat)
    step, stl = d / "part.step", d / "part.stl"
    cq.exporters.export(model, str(step))
    cq.exporters.export(model, str(stl), tolerance=0.02, angularTolerance=0.1)
    vol = model.val().Volume()
    bb = model.val().BoundingBox()
    mesh = trimesh.load(str(stl))
    save_preview(mesh, d / "preview.png")
    make_drawing(feat, mesh, d / "drawing.png", d / "drawing.pdf", vol)
    print(json.dumps({"volume_mm3": round(vol, 1), "bbox": [bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax],
                      "faces": len(mesh.faces), "out": [str(p) for p in (step, stl, d / "drawing.png", d / "drawing.pdf", d / "preview.png")]}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "parts/sm-101")
