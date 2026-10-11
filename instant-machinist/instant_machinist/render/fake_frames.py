"""Synthesize plausible sim output (frames.npz + toolpath.npz per docs/CONTRACTS.md).

Stock 124 x 84 (z 1.5 .. -26.5) is faced to Z0, a 64x36 r6 pocket is cut 8 deep,
then spot drilled and drilled. Used to develop the renderer before the real simulator lands.

    .venv/bin/python -m instant_machinist.render.fake_frames --out out/fake/sim --frames 360
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

STOCK_X, STOCK_Y, STOCK_TOP, STOCK_BOT = (-62.0, 62.0), (-42.0, 42.0), 1.5, -26.5
SAFE_Z = 25.0
TOOL_CHANGE_S = 6.0
RAPID_MM_MIN = 15000.0

# id: (type, diameter, tip_angle_deg)
TOOLS = {1: ("face_mill", 50.0, 0), 2: ("flat", 10.0, 0), 4: ("spot_drill", 10.0, 90),
         5: ("drill", 6.6, 118), 6: ("drill", 8.0, 118)}


def _rounded_rect_ring(cx, cy, w, h, r, n_arc=10):
    """Closed CCW contour of a rounded rectangle (centre-line of a tool pass)."""
    pts = []
    hw, hh = w / 2 - r, h / 2 - r
    for (ox, oy, a0) in ((hw, -hh, -90), (hw, hh, 0), (-hw, hh, 90), (-hw, -hh, 180)):
        for a in np.linspace(a0, a0 + 90, n_arc):
            t = np.radians(a)
            pts.append((cx + ox + r * np.cos(t), cy + oy + r * np.sin(t)))
    pts.append(pts[0])
    return pts


def build_program():
    """Return list of (tool_id, kind, xyz, feed_mm_min) moves; kind in rapid|feed|change."""
    moves = []
    cur = None

    def change(tid):
        """Add a tool change."""
        moves.append((tid, "change", None, 0.0))

    def rapid(tid, x, y, z):
        """Add a rapid move."""
        moves.append((tid, "rapid", (x, y, z), RAPID_MM_MIN))

    def feed(tid, x, y, z, f):
        """Add a feed move at ``f`` mm/min."""
        moves.append((tid, "feed", (x, y, z), f))

    # T1 face mill: zig-zag along X, 3 passes
    change(1)
    ys = [-26.0, 0.0, 26.0]
    rapid(1, -95, ys[0], SAFE_Z)
    rapid(1, -95, ys[0], 2.0)
    feed(1, -95, ys[0], 0.0, 1500)
    for i, y in enumerate(ys):
        x_end = 95 if i % 2 == 0 else -95
        feed(1, x_end, y, 0.0, 1500)
        if i + 1 < len(ys):
            feed(1, x_end, ys[i + 1], 0.0, 1500)
    rapid(1, -95 if len(ys) % 2 == 0 else 95, ys[-1], SAFE_Z)

    # T2 Ø10 pocket 64x36 r6, two 4 mm steps, concentric rings outward from centre
    change(2)
    rapid(2, 0, 0, SAFE_Z)
    rapid(2, 0, 0, 2.0)
    for z in (-4.0, -8.0):
        # helical-ish ramp entry
        feed(2, 0, 0, z, 300)
        feed(2, -13.5, 0, z, 900)
        feed(2, 13.5, 0, z, 1100)
        for inset in (9.0, 4.5, 0.0):  # finish wall centre-line is 54x26 r1 (Ø10 tool in 64x36 r6)
            w, h = 54 - 2 * inset, 26 - 2 * inset
            ring = _rounded_rect_ring(0, 0, w, h, 1.0 if inset == 0 else 0.8)
            feed(2, ring[0][0], ring[0][1], z, 900)
            for (x, y) in ring[1:]:
                feed(2, x, y, z, 1100)
        feed(2, 0, 0, z, 1100)
    rapid(2, 0, 0, SAFE_Z)
    # T2 small slot pocket F4 40x8 r4 at y=-30, 4 deep (Ø10 tool won't fit the 8 wide slot; skip)

    holes_a = [(-50, -30), (50, -30), (50, 30), (-50, 30)]
    holes_b = [(-20, 0), (20, 0)]
    # T4 spot drill all
    change(4)
    for (x, y) in holes_a:
        rapid(4, x, y, SAFE_Z); rapid(4, x, y, 2.0); feed(4, x, y, -1.8, 250); rapid(4, x, y, 2.0)
    for (x, y) in holes_b:
        rapid(4, x, y, SAFE_Z); rapid(4, x, y, -6.0); feed(4, x, y, -9.8, 250); rapid(4, x, y, -6.0)
    rapid(4, holes_b[-1][0], holes_b[-1][1], SAFE_Z)
    # T5 drill Ø6.6 peck
    change(5)
    for (x, y) in holes_a:
        rapid(5, x, y, SAFE_Z); rapid(5, x, y, 2.0)
        for z in (-7, -14, -22.5):
            feed(5, x, y, z, 320); rapid(5, x, y, 2.0)
    rapid(5, holes_a[-1][0], holes_a[-1][1], SAFE_Z)
    # T6 drill Ø8 from pocket floor
    change(6)
    for (x, y) in holes_b:
        rapid(6, x, y, SAFE_Z); rapid(6, x, y, -6.0)
        for z in (-14, -22.5):
            feed(6, x, y, z, 300); rapid(6, x, y, -6.0)
    rapid(6, holes_b[-1][0], holes_b[-1][1], SAFE_Z)
    return moves


def _kernel(tool_id, cell):
    typ, d, tip = TOOLS[tool_id]
    r = d / 2
    n = int(np.ceil(r / cell))
    ax = np.arange(-n, n + 1) * cell
    dx, dy = np.meshgrid(ax, ax)
    rr = np.hypot(dx, dy)
    k = np.full(rr.shape, np.inf, np.float32)
    inside = rr <= r
    if tip:
        k[inside] = rr[inside] / np.tan(np.radians(tip / 2))
    else:
        k[inside] = 0.0
    return n, k


def main(argv=None):
    """CLI entry point: write synthetic sim frames for renderer development."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="out/fake/sim")
    ap.add_argument("--frames", type=int, default=360)
    ap.add_argument("--cell", type=float, default=0.25)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    cell = a.cell
    nx = int(round((STOCK_X[1] - STOCK_X[0]) / cell))
    ny = int(round((STOCK_Y[1] - STOCK_Y[0]) / cell))
    x0, y0 = STOCK_X[0] + cell / 2, STOCK_Y[0] + cell / 2
    heights = np.full((ny, nx), STOCK_TOP, np.float32)

    moves = build_program()
    # Expand into a dense sample stream: (t, tool, xyz, is_feed, nc_line)
    samples = []
    tp_pts, tp_rapid, tp_tool, tp_line = [], [], [], []
    t = 0.0
    pos = np.array([0.0, 0.0, SAFE_Z + 50])
    for line, (tid, kind, xyz, f) in enumerate(moves, start=10):
        if kind == "change":
            t += TOOL_CHANGE_S
            pos = np.array([pos[0], pos[1], SAFE_Z + 50])
            continue
        tgt = np.array(xyz, float)
        L = float(np.linalg.norm(tgt - pos))
        dur = L / f * 60.0 if L > 0 else 0.0
        nstep = max(1, int(np.ceil(L / (cell * 0.8)))) if kind == "feed" else max(1, int(np.ceil(L / 5.0)))
        for s in range(1, nstep + 1):
            u = s / nstep
            samples.append((t + dur * u, tid, pos + (tgt - pos) * u, kind == "feed", line))
        tp_pts.append(tgt); tp_rapid.append(kind == "rapid"); tp_tool.append(tid); tp_line.append(line)
        t += dur
        pos = tgt
    total = t

    # frames evenly in machine time but skip "dead" time: sample over cumulative cutting time
    feed_t = np.array([s[0] for s in samples])
    is_feed = np.array([s[3] for s in samples])
    # warp time so feeds get most frames: weight feeds 1, rapids 0.15
    dt = np.diff(np.concatenate([[0.0], feed_t]))
    w = np.where(is_feed, dt, dt * 0.15)
    cw = np.cumsum(w)
    targets = np.linspace(0, cw[-1], a.frames)
    frame_sample = np.searchsorted(cw, targets, side="left").clip(0, len(samples) - 1)

    kernels = {tid: _kernel(tid, cell) for tid in TOOLS}
    F = a.frames
    H = np.empty((F, ny, nx), np.float32)
    tool_pos = np.zeros((F, 3)); tool_id = np.zeros(F, int); tool_diam = np.zeros(F)
    nc_line = np.zeros(F, int); t_sec = np.zeros(F)
    si = 0
    for fi, target in enumerate(frame_sample):
        while si <= target:
            tt, tid, p, fe, ln = samples[si]
            if fe or p[2] < STOCK_TOP:
                n, k = kernels[tid]
                cx = int(round((p[0] - x0) / cell)); cy = int(round((p[1] - y0) / cell))
                xa, xb = cx - n, cx + n + 1; ya, yb = cy - n, cy + n + 1
                kxa, kya = max(0, -xa), max(0, -ya)
                xa2, ya2, xb2, yb2 = max(xa, 0), max(ya, 0), min(xb, nx), min(yb, ny)
                if xa2 < xb2 and ya2 < yb2:
                    sub = k[kya:kya + (yb2 - ya2), kxa:kxa + (xb2 - xa2)] + p[2]
                    np.minimum(heights[ya2:yb2, xa2:xb2], sub, out=heights[ya2:yb2, xa2:xb2])
            si += 1
        tt, tid, p, fe, ln = samples[target]
        hh = heights.copy()
        hh[hh < STOCK_BOT] = np.nan
        H[fi] = hh
        tool_pos[fi] = p; tool_id[fi] = tid; tool_diam[fi] = TOOLS[tid][1]; nc_line[fi] = ln; t_sec[fi] = tt
    # end frame: tool retracted, full time
    t_sec[-1] = total

    fin = H[-1]
    np.savez_compressed(
        out / "frames.npz", x0=np.float64(x0), y0=np.float64(y0), cell=np.float64(cell), heights=H,
        stock_z_bottom=np.float64(STOCK_BOT), tool_pos=tool_pos, tool_id=tool_id, tool_diam=tool_diam,
        nc_line=nc_line, t_sec=t_sec, final_gouge=np.zeros(fin.shape, bool), final_leftover=np.zeros(fin.shape, bool),
    )
    np.savez_compressed(out / "toolpath.npz", points=np.array(tp_pts), rapid=np.array(tp_rapid),
                        tool_id=np.array(tp_tool), nc_line=np.array(tp_line))
    print(f"wrote {out}/frames.npz ({F} frames, {ny}x{nx} @ {cell} mm, cycle {total:.0f}s) and toolpath.npz")


if __name__ == "__main__":
    main()
