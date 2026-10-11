"""Render a machining-sim video (or hero still) from simulator output with headless Chrome + three.js.

    .venv/bin/python -m instant_machinist.render.video \
        --frames out/<job>/sim/frames.npz --toolpath out/<job>/sim/toolpath.npz \
        --out out/<job>/sim.mp4 --fps 30 --size 1920x1080 --badge "Verified: 0 gouges · 12:34 cycle"
    ... --still [hero.png]     # single PNG of the final frame instead of the mp4

Inputs follow docs/CONTRACTS.md exactly. Tool types/flute lengths come from --tools (tools.json); if omitted,
parts/<job>/tools.json is used when it exists, else types are inferred from diameter and motion.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

FRAME_KEYS = ("x0", "y0", "cell", "heights", "stock_z_bottom", "tool_pos", "tool_id", "tool_diam", "nc_line", "t_sec",
              "final_gouge", "final_leftover")
TP_KEYS = ("points", "rapid", "tool_id", "nc_line")
TYPE_NAMES = {"flat": "end mill", "face_mill": "face mill", "spot_drill": "spot drill", "drill": "drill",
              "ball": "ball end mill"}
OP_NAMES = {"flat": "Milling", "face_mill": "Facing", "spot_drill": "Spot drilling", "drill": "Drilling",
            "ball": "3D finishing"}


def load_npz(path, keys):
    d = np.load(path, allow_pickle=False)
    missing = [k for k in keys if k not in d.files]
    if missing:
        sys.exit(f"{path}: missing keys {missing} (see docs/CONTRACTS.md)")
    return {k: d[k] for k in keys}


def fmt_d(d):
    return f"{d:.1f}".rstrip("0").rstrip(".")


def resolve_tools(fr, tp, tools_path, frames_path):
    crib = {}
    if tools_path is None:
        job = Path(frames_path).resolve().parent.parent.name
        cand = REPO / "parts" / job / "tools.json"
        tools_path = cand if cand.exists() else None
    if tools_path:
        crib = json.loads(Path(tools_path).read_text()).get("tools", {})
    out = {}
    for tid in sorted(set(int(t) for t in fr["tool_id"])):
        sel = fr["tool_id"] == tid
        diam = float(np.median(fr["tool_diam"][sel]))
        c = crib.get(str(tid), {})
        typ = c.get("type")
        if typ is None:  # infer: big = face mill; feed moves without XY travel = drill
            pts, rapid, ids = tp["points"], tp["rapid"], tp["tool_id"]
            j = np.nonzero((ids[1:] == tid) & ~rapid[1:])[0] + 1
            xy = np.hypot(*(pts[j, :2] - pts[j - 1, :2]).T) if len(j) else np.zeros(0)
            zz = np.abs(pts[j, 2] - pts[j - 1, 2]) if len(j) else np.zeros(0)
            if diam >= 25:
                typ = "face_mill"
            elif len(j) and xy.sum() < 0.05 * max(zz.sum(), 1e-6):
                typ = "spot_drill" if (pts[j, 2].min() > -diam * 0.5) else "drill"
            else:
                typ = "flat"
        d = float(c.get("diameter", diam))
        out[str(tid)] = {
            "type": typ, "diam": d, "flutes": c.get("flutes"), "flute_length": c.get("flute_length"),
            "tip_angle": c.get("tip_angle"), "label": f"Ø{fmt_d(d)} {TYPE_NAMES.get(typ, typ)}",
        }
    return out


def resample_grid(fr, max_cells):
    """Nearest-neighbour resample so the mesh has at most max_cells along its longer side (keeps edges crisp)."""
    F, ny, nx = fr["heights"].shape
    cell = float(fr["cell"])
    x0, y0 = float(fr["x0"]), float(fr["y0"])
    if max(nx, ny) <= max_cells * 1.05:
        return dict(x0=x0, y0=y0, cell=cell, cell_y=cell, nx=nx, ny=ny), np.arange(nx), np.arange(ny)
    sx, sy = nx * cell, ny * cell
    mcell = max(sx, sy) / max_cells
    mnx, mny = int(round(sx / mcell)), int(round(sy / mcell))
    mcx, mcy = sx / mnx, sy / mny
    xs = (x0 - cell / 2) + (np.arange(mnx) + 0.5) * mcx
    ys = (y0 - cell / 2) + (np.arange(mny) + 0.5) * mcy
    ix = np.clip(np.round((xs - x0) / cell).astype(int), 0, nx - 1)
    iy = np.clip(np.round((ys - y0) / cell).astype(int), 0, ny - 1)
    return dict(x0=float(xs[0]), y0=float(ys[0]), cell=float(mcx), nx=mnx, ny=mny, cell_y=float(mcy)), ix, iy


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    return np.linalg.norm(a + ab * t[:, None] - p, axis=1)


def map_frames_to_moves(fr, tp, window=5000):
    """Monotone match of each sim frame to the toolpath move (index j: segment points[j-1] -> points[j])."""
    pts, ids, lines = tp["points"], tp["tool_id"], tp["nc_line"]
    N = len(pts)
    out = np.zeros(len(fr["t_sec"]), int)
    ptr = 1
    for i, (p, tid, ln) in enumerate(zip(fr["tool_pos"], fr["tool_id"], fr["nc_line"])):
        if N < 2:
            break
        j = np.arange(max(ptr, 1), min(N, max(ptr, 1) + window))
        if len(j) == 0:
            out[i] = N - 1
            continue
        d = seg_dist(np.broadcast_to(p, (len(j), 3)), pts[j - 1], pts[j])
        score = d + 1e4 * (ids[j] != tid) + 0.5 * (lines[j] != ln) + 1e-6 * (j - j[0])
        m = int(np.argmin(score))
        k = int(j[m])
        if d[m] < 1.0:
            out[i] = k
            ptr = k
        else:  # tool not on any nearby move (approach / retract / tool change): keep the last match
            out[i] = -max(ptr, 1) if i else -1
    return out


def build_data(a, workdir):
    fr = load_npz(a.frames, FRAME_KEYS)
    tp = load_npz(a.toolpath, TP_KEYS)
    tp["rapid"] = tp["rapid"].astype(bool)
    F = fr["heights"].shape[0]
    W, H = map(int, a.size.lower().split("x"))
    tools = resolve_tools(fr, tp, a.tools, a.frames)

    sel = np.arange(F) if not a.max_frames or F <= a.max_frames else np.unique(
        np.round(np.linspace(0, F - 1, a.max_frames)).astype(int))
    grid, ix, iy = resample_grid(fr, a.mesh_cells)
    Hs = fr["heights"][sel][:, iy][:, :, ix].astype(np.float32)
    zbot = float(fr["stock_z_bottom"])
    lo, hi = float(np.nanmin(Hs)), float(np.nanmax(Hs))
    lo = min(lo, zbot)
    if hi - lo < 1e-6:
        hi = lo + 1
    q = np.round((np.nan_to_num(Hs, nan=lo) - lo) / (hi - lo) * 65534).astype(np.uint16)
    q[np.isnan(Hs)] = 65535
    q.tofile(workdir / "heights.bin")
    ztop0 = float(np.nanmax(Hs[0]))

    mask = np.zeros(fr["final_gouge"].shape, np.uint8)
    mask[fr["final_leftover"].astype(bool)] = 2
    mask[fr["final_gouge"].astype(bool)] = 1
    mask = mask[iy][:, ix]
    mask.tofile(workdir / "masks.bin")

    # trail: feed segments in program order with cumulative length
    pts = tp["points"].astype(np.float64)
    feed_j = np.nonzero(~tp["rapid"][1:])[0] + 1
    feed_j = feed_j[tp["tool_id"][feed_j] == tp["tool_id"][feed_j - 1]]
    seg_a, seg_b = pts[feed_j - 1], pts[feed_j]
    cum = np.cumsum(np.linalg.norm(seg_b - seg_a, axis=1))
    np.concatenate([seg_a, seg_b, cum[:, None]], axis=1).astype(np.float32).tofile(workdir / "trail.bin")

    move_of = map_frames_to_moves(fr, tp)
    on_move = move_of > 0
    move_of = np.abs(move_of)
    seg_done = np.searchsorted(feed_j, move_of, side="left")  # feed segments strictly before current move
    seg_done[~on_move] = np.searchsorted(feed_j, move_of[~on_move], side="right")  # off-path: last move finished
    seg_done[: max(1, int(np.argmax(on_move)))] *= on_move[: max(1, int(np.argmax(on_move)))]  # nothing before first match
    cur_is_feed = np.isin(move_of, feed_j) & on_move

    # operations = contiguous runs of tool_id
    tids = fr["tool_id"]
    t = fr["t_sec"].astype(float)
    starts = np.r_[0, np.nonzero(np.diff(tids))[0] + 1]
    ends = np.r_[starts[1:], F]
    ops, op_of = [], np.zeros(F, int)
    for k, (s, e) in enumerate(zip(starts, ends)):
        typ = tools[str(int(tids[s]))]["type"]
        ops.append({"tool": int(tids[s]), "label": OP_NAMES.get(typ, "Machining"), "t0": float(t[s]), "t1": float(t[e - 1])})
        op_of[s:e] = k
    t_total = float(t[-1]) if t[-1] > 0 else 1.0

    fps = a.fps
    n_intro, n_hold = int(round(a.intro * fps)), int(round(a.hold * fps))
    timeline = [("intro", sel[0])] * n_intro + [("main", s) for s in sel] + [("hold", sel[-1])] * n_hold
    N = len(timeline)
    Fd = {k: [] for k in ("sim", "pos", "tool", "t", "op", "opp", "prog", "seg", "head", "lift", "tool_a", "badge", "cam", "fade", "cut", "seg0")}
    sel_index = {int(s): k for k, s in enumerate(sel)}
    for i, (phase, s) in enumerate(timeline):
        s = int(s)
        op = int(op_of[s])
        o = ops[op]
        opp = 1.0 if o["t1"] <= o["t0"] else (t[s] - o["t0"]) / (o["t1"] - o["t0"])
        h = (i - (N - n_hold)) / max(n_hold - 1, 1) if phase == "hold" else 0.0
        lift = 0.0
        tool_a = 1.0
        badge = 0.0
        if phase == "hold":
            lift = 160.0 * (min(1.0, h / 0.45) ** 2)
            tool_a = 0.0 if h > 0.45 else 1.0
            badge = min(1.0, max(0.0, (h - 0.35) / 0.25)) if a.badge else 0.0
        head = None
        if cur_is_feed[s]:
            j = move_of[s]
            head = [float(v) for v in pts[j - 1]]
        Fd["sim"].append(sel_index[s])
        Fd["pos"].append([round(float(v), 4) for v in fr["tool_pos"][s]])
        Fd["tool"].append(int(tids[s]))
        Fd["t"].append(float(t[s]) if phase != "hold" else t_total)
        Fd["op"].append(op)
        Fd["opp"].append(float(min(max(opp, 0), 1)) if phase != "hold" else 1.0)
        Fd["prog"].append(float(t[s] / t_total) if phase != "hold" else 1.0)
        Fd["seg"].append(int(seg_done[s]))
        Fd["seg0"].append(int(seg_done[starts[op]]))  # trail only shows the current tool's moves
        Fd["head"].append(head)
        Fd["lift"].append(lift)
        Fd["tool_a"].append(tool_a)
        Fd["badge"].append(badge)
        Fd["cam"].append(i / max(N - 1, 1))
        z_here = float(fr["tool_pos"][s][2])
        Fd["cut"].append(1 if (phase == "main" and cur_is_feed[s] and z_here < ztop0 - 0.05) else 0)
        Fd["fade"].append(max(0.0, 1.0 - i / max(1, 0.5 * fps)))
    meta = {
        "width": W, "height": H, "fps": fps, "grid": grid, "zbot": zbot, "ztop0": ztop0, "zq": [lo, hi],
        "tools": tools, "ops": ops, "badge": a.badge, "trail_len_mm": a.trail_mm, "has_masks": True,
        "frames": Fd,
    }
    (workdir / "meta.json").write_text(json.dumps(meta, separators=(",", ":"), ensure_ascii=False))
    return N


def node_bin():
    return shutil.which("node") or sys.exit("node not found")


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), file=sys.stderr)
    subprocess.run(cmd, check=True, **kw)


DRUN_SETUP = ("(sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg) >/dev/null 2>&1; "
              "npm i -s --no-audit --no-fund playwright@1.63 >/dev/null 2>&1 && npx playwright install --with-deps chromium >/dev/null 2>&1")


def render_drun(work, data, a, n_frames, out, chunks):
    """Render chunks in parallel Daytona sandboxes (`drun`), each encoding its own segment; concat locally (-c copy)."""
    per = -(-n_frames // chunks)
    procs = []
    for k in range(chunks):
        s, e = k * per, min(n_frames, (k + 1) * per)
        if s >= e:
            break
        d = work / f"chunk{k}"
        (d / "render").mkdir(parents=True, exist_ok=True)
        for sub in ("web", "vendor"):
            shutil.copytree(HERE / sub, d / "render" / sub, dirs_exist_ok=True)
        shutil.copytree(data, d / "data", dirs_exist_ok=True)
        (d / "go.sh").write_text(
            "set -e\n"
            f"node render/web/render.mjs --data data --outdir png --size {a.size} --workers 4 --start {s} --end {e}\n"
            f"ffmpeg -y -loglevel error -framerate {a.fps} -start_number {s} -i png/f%05d.png -c:v libx264 -preset slow "
            f"-crf {a.crf} -pix_fmt yuv420p -movflags +faststart seg.mp4\nrm -rf png data\n")
        log = open(d / "drun.log", "w")
        procs.append((d, subprocess.Popen(["drun", "--setup", DRUN_SETUP, "--", "bash", "go.sh"], cwd=d, stdout=log,
                                          stderr=subprocess.STDOUT)))
        print(f"drun chunk {k}: frames {s}..{e} ({d}/drun.log)", file=sys.stderr)
    for d, p in procs:
        if p.wait() != 0 or not (d / "seg.mp4").exists():
            sys.exit(f"drun chunk failed, see {d}/drun.log")
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{d / 'seg.mp4'}'\n" for d, _ in procs))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", str(out)])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--toolpath", required=True)
    ap.add_argument("--out", required=True, help="output .mp4 (or .png with --still)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--badge", default="", help='final-beat badge text, e.g. "Verified: 0 gouges · 12:34 cycle"')
    ap.add_argument("--tools", default=None, help="tools.json (default parts/<job>/tools.json if present)")
    ap.add_argument("--still", nargs="?", const="", default=None, help="write a single hero PNG of the final frame")
    ap.add_argument("--still-frame", type=int, default=None, help="output frame index for --still (default last)")
    ap.add_argument("--max-frames", type=int, default=0, help="evenly subsample sim frames to at most N")
    ap.add_argument("--mesh-cells", type=int, default=440, help="max height-field cells along the long side")
    ap.add_argument("--intro", type=float, default=0.8, help="seconds before cutting starts")
    ap.add_argument("--hold", type=float, default=3.2, help="seconds for the final beat")
    ap.add_argument("--trail-mm", type=float, default=320.0, help="length of the glowing toolpath trail")
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 4) // 4)))
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--keep", default=None, help="keep the work dir (data + PNG frames) here")
    ap.add_argument("--range", default=None, help="render only output frames A:B (debug)")
    ap.add_argument("--drun", type=int, default=0, metavar="N",
                    help="render in N parallel Daytona sandboxes via `drun` instead of locally (needs drun on PATH)")
    a = ap.parse_args(argv)

    t0 = time.time()
    work = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="im-render-"))
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)
    N = build_data(a, data)
    print(f"prepared {N} output frames in {time.time() - t0:.1f}s ({data})", file=sys.stderr)
    script = HERE / "web" / "render.mjs"
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if a.still is not None:
            still = Path(a.still) if a.still else out.with_suffix(".png")
            still.parent.mkdir(parents=True, exist_ok=True)
            cmd = [node_bin(), str(script), "--data", str(data), "--size", a.size, "--still", str(still)]
            if a.still_frame is not None:
                cmd += ["--frame", str(a.still_frame)]
            run(cmd)
            print(still)
            return
        if a.drun:
            render_drun(work, data, a, N, out, a.drun)
            print(f"{out} ({N} frames, {time.time() - t0:.0f}s)", file=sys.stderr)
            print(out)
            return
        frames_dir = work / "png"
        cmd = [node_bin(), str(script), "--data", str(data), "--outdir", str(frames_dir), "--size", a.size,
               "--workers", str(a.workers)]
        if a.range:
            s, e = a.range.split(":")
            cmd += ["--start", s, "--end", e]
        run(cmd)
        first = min(int(p.stem[1:]) for p in frames_dir.glob("f*.png"))
        run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-start_number", str(first),
             "-i", str(frames_dir / "f%05d.png"), "-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
        print(f"{out} ({N} frames, {time.time() - t0:.0f}s)", file=sys.stderr)
        print(out)
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
