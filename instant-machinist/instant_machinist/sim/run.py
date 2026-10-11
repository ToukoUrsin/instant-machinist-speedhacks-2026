"""Simulator CLI / API.

    .venv/bin/python -m instant_machinist.sim.run --part parts/sm-101 --nc a.nc [b.nc] \
        --out out/<job>/sim [--tools tools.json] [--frames 360] [--cell 0.25] [--frame-cell 0.5]

Python:  from instant_machinist.sim.run import simulate; report = simulate("parts/sm-101", ["a.nc"], "out/x/sim")
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np

from . import gcode
from .checks import Checker
from .cycle import cycle_report, segment_times
from .gcode import DWELL, FEED, RAPID, TOOLCHANGE, parse_programs
from .stock import Grid, Stock, Tool, load_tools_diagnostics
from .target import load_target


def _block_reduce(a: np.ndarray, k: int, how: str) -> np.ndarray:
    if k == 1:
        return a.copy()
    ny, nx = a.shape
    py, px = (-ny) % k, (-nx) % k
    if py or px:
        a = np.pad(a, ((0, py), (0, px)), mode="edge")
    b = a.reshape(a.shape[0] // k, k, a.shape[1] // k, k)
    if how == "any":
        return b.any(axis=(1, 3))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(b, axis=(1, 3))


def simulate(part, nc, out=None, tools=None, frames: int = 360, cell: float = 0.25, frame_cell: float = 0.5,
             target_mode: str = "features", home_z: float = 50.0, vise_grip: float = 6.0, jaw_axis: str = "y",
             fixture_mode: str = "jaws", write_png: bool = True, verbose: bool = False,
             work_offsets=None) -> dict:
    """Run the full simulation. Returns the report dict (also written to `out` if given)."""
    t_start = time.perf_counter()
    part = Path(part)
    if isinstance(nc, (str, Path)):
        nc = [nc]
    feats = json.loads((part / "features.json").read_text())
    tool_path = Path(tools) if tools else part / "tools.json"
    tool_crib, tool_metadata = load_tools_diagnostics(tool_path)

    tp = parse_programs([Path(p) for p in nc], home_z=home_z, work_offsets=work_offsets)
    t_parse = time.perf_counter()
    times = segment_times(tp)
    cum = np.concatenate([[0.0], np.cumsum(times)])
    total_t = float(cum[-1])

    stock = Stock.from_features(feats, cell)
    target = load_target(part, stock.grid, target_mode)
    warn = list(tp.warnings)
    missing = sorted({int(t) for t in np.unique(tp.tool) if t != 0 and int(t) not in tool_crib})
    if missing:
        warn.append(f"tools not in {tool_path}: {missing} (their moves are not simulated)")
        tool_metadata.extend({"tool": n, "severity": "error", "issue": "tool referenced by program is missing"} for n in missing)
    chk = Checker(feats, stock, target, tool_crib, tp, vise_grip=vise_grip, jaw_axis=jaw_axis,
                  fixture_mode=fixture_mode, tool_metadata=tool_metadata)

    # ---- frame bookkeeping
    k = max(1, int(round(frame_cell / cell)))
    fgrid = stock.grid.downsample(k)
    F = max(1, int(frames))
    frame_t = np.linspace(0.0, total_t, F) if F > 1 else np.array([total_t])
    fh = np.empty((F, fgrid.ny, fgrid.nx), np.float32)
    f_pos = np.zeros((F, 3))
    f_tool = np.zeros(F, np.int32)
    f_diam = np.zeros(F)
    f_line = np.zeros(F, np.int32)
    f_prog = np.zeros(F, np.int32)
    fi = 0

    def snap(pos, seg_i):
        """Store a downsampled heightmap frame with tool position, tool and NC line for segment ``seg_i``."""
        nonlocal fi
        hn = stock.heights_nan()
        fh[fi] = _block_reduce(hn, k, "mean")
        f_pos[fi] = pos
        tn = int(tp.tool[seg_i]) if seg_i >= 0 else 0
        f_tool[fi] = tn
        f_diam[fi] = tool_crib[tn].diameter if tn in tool_crib else 0.0
        f_line[fi] = int(tp.nc_line[seg_i]) if seg_i >= 0 else 0
        f_prog[fi] = int(tp.program[seg_i]) if seg_i >= 0 else 0
        fi += 1

    n = len(tp)
    if n == 0:
        warn.append("no motion in program(s)")
    p0s, p1s, kinds, toolsarr = tp.p0, tp.p1, tp.kind, tp.tool
    for i in range(n):
        kind = int(kinds[i])
        tool = tool_crib.get(int(toolsarr[i]))
        p0, p1 = p0s[i], p1s[i]
        cutting = kind in (FEED, RAPID) and tool is not None
        if cutting:
            chk.pre_segment(i, p0, p1, kind, tool)
        t0, t1 = cum[i], cum[i + 1]
        # frames falling inside this segment: cut the partial move first (sweeps are idempotent)
        while fi < F and frame_t[fi] <= t1 + 1e-9:
            frac = (frame_t[fi] - t0) / (t1 - t0) if t1 > t0 else 1.0
            frac = min(max(frac, 0.0), 1.0)
            pos = p0 + frac * (p1 - p0)
            if cutting and frac > 0.0:
                res = stock.sweep(p0, pos, tool)
                if res is not None:
                    chk.on_cut(i, kind, tool, p0, pos, res)
            snap(pos, i)
        if cutting:
            res = stock.sweep(p0, p1, tool)
            if res is not None:
                chk.on_cut(i, kind, tool, p0, p1, res)
        elif kind == FEED and tool is None and int(toolsarr[i]) == 0:
            chk.warnings.append(f"line {tp.nc_line[i]}: feed move with no tool loaded")
    while fi < F:  # empty program / numerical tail
        snap(p1s[-1] if n else np.zeros(3), n - 1)
    t_sim = time.perf_counter()

    checks, gouge, leftover = chk.finalize()
    warn += chk.warnings[:20]
    cyc = cycle_report(tp, times)
    ok = all(v["ok"] for kk, v in checks.items() if isinstance(v, dict) and kk != "flute_length")
    hn = stock.heights_nan()
    report = {
        "part": feats.get("part_number", part.name),
        "programs": tp.files,
        "tools_file": str(tool_path),
        "ok": ok,
        "cycle_time": cyc,
        "checks": checks,
        "summary": {
            "segments": n, "frames": F, "cell_mm": cell, "frame_cell_mm": fgrid.cell,
            "grid": [stock.grid.ny, stock.grid.nx], "target_source": target.source,
            "removed_volume_cm3": round(float(((stock.z_top - stock.h)).sum()) * cell * cell / 1000.0, 2),
            "final_min_z": round(float(np.nanmin(stock.h)), 3),
        },
        "toolpath_convention": "points[0] = start position; move j (1..N) goes points[j-1] -> points[j]; "
                               "rapid/tool_id/nc_line[j] describe move j (index 0 = start state)",
        "warnings": warn,
        "runtime_s": {"parse": round(t_parse - t_start, 2), "simulate": round(t_sim - t_parse, 2)},
    }

    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        fg = _block_reduce(gouge, k, "any")
        fl = _block_reduce(leftover, k, "any")
        np.savez_compressed(
            out / "frames.npz", x0=fgrid.x0, y0=fgrid.y0, cell=fgrid.cell, heights=fh,
            stock_z_bottom=stock.z_bottom, tool_pos=f_pos, tool_id=f_tool, tool_diam=f_diam,
            nc_line=f_line, program=f_prog, t_sec=frame_t, final_gouge=fg, final_leftover=fl,
            target=_block_reduce(target.top.astype(np.float32), k, "mean").astype(np.float32))
        pts = np.vstack([p0s[:1] if n else np.zeros((1, 3)), p1s])
        rapid = np.concatenate([[True], kinds == RAPID])
        np.savez_compressed(
            out / "toolpath.npz", points=pts, rapid=rapid,
            tool_id=np.concatenate([[toolsarr[0] if n else 0], toolsarr]).astype(np.int32),
            nc_line=np.concatenate([[tp.nc_line[0] if n else 0], tp.nc_line]).astype(np.int32),
            program=np.concatenate([[0], tp.program]).astype(np.int32),
            kind=np.concatenate([[TOOLCHANGE], kinds]).astype(np.int8))
        if write_png:
            _plot_maps(out / "final_maps.png", stock, hn, target, gouge, leftover, report)
        report["runtime_s"]["total"] = round(time.perf_counter() - t_start, 2)
        (out / "report.json").write_text(json.dumps(report, indent=2))
        (out / "report.md").write_text(report_md(report))
    else:
        report["runtime_s"]["total"] = round(time.perf_counter() - t_start, 2)
    if verbose:
        print(report_md(report))
    return report


def _plot_maps(path, stock, hn, target, gouge, leftover, report):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    g = stock.grid
    ext = [g.xs[0] - g.cell / 2, g.xs[-1] + g.cell / 2, g.ys[0] - g.cell / 2, g.ys[-1] + g.cell / 2]
    fig, ax = plt.subplots(1, 3, figsize=(18, 5.2), constrained_layout=True)
    im = ax[0].imshow(hn, origin="lower", extent=ext, cmap="viridis")
    ax[0].set_title("Final stock top Z (mm)")
    fig.colorbar(im, ax=ax[0], shrink=0.8)
    dev = np.where(np.isfinite(hn), hn, stock.z_bottom) - target.top
    dev = np.where(np.isinf(target.floor) & (dev < 0), 0.0, dev)  # cutting deeper in through regions is fine
    lim = max(0.2, float(report["checks"]["leftover"]["tolerance_mm"]) * 5)
    im = ax[1].imshow(np.clip(dev, -lim, lim), origin="lower", extent=ext, cmap="RdBu_r", vmin=-lim, vmax=lim)
    ax[1].set_title("Deviation vs target (stock - target, mm; clipped)")
    fig.colorbar(im, ax=ax[1], shrink=0.8)
    over = np.zeros(hn.shape, np.int8)
    over[leftover] = 1
    over[gouge] = 2
    ax[2].imshow(np.where(np.isfinite(target.top), target.top, np.nan), origin="lower", extent=ext, cmap="Greys_r", alpha=0.6)
    ax[2].imshow(np.ma.masked_equal(over, 0), origin="lower", extent=ext,
                 cmap=ListedColormap(["#f5a623", "#d0021b"]), vmin=1, vmax=2, interpolation="nearest")
    c = report["checks"]
    ax[2].set_title(f"Gouge (red) {c['gouge']['area_mm2']} mm2 / leftover (orange) {c['leftover']['area_mm2']} mm2")
    for e in c["gouge"]["events"][:10]:
        ax[2].annotate(f"L{e.get('nc_line', '?')}", (e["x"], e["y"]), color="#d0021b", fontsize=8)
    for a in ax:
        a.set_xlabel("X (mm)")
        a.set_ylabel("Y (mm)")
        a.set_aspect("equal")
    fig.suptitle(f"{report['part']}  -  {'PASS' if report['ok'] else 'FAIL'}  -  cycle {report['cycle_time']['total_min']} min")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _fmt_s(s: float) -> str:
    return f"{int(s // 60)}:{s % 60:04.1f}"


def report_md(r: dict) -> str:
    """Render a simulation report dict as Markdown (cycle time table and checks)."""
    c, ct = r["checks"], r["cycle_time"]
    L = [f"# Simulation report: {r['part']}", "",
         f"**Result: {'PASS' if r['ok'] else 'FAIL'}**  ", f"Programs: {', '.join(r['programs'])}", "",
         "## Cycle time", "",
         "| | time |", "|---|---|",
         f"| Cutting (feed) | {_fmt_s(ct['cutting_s'])} |", f"| Rapid | {_fmt_s(ct['rapid_s'])} |",
         f"| Dwell | {_fmt_s(ct['dwell_s'])} |",
         f"| Tool change ({ct['tool_changes']} x 4 s) | {_fmt_s(ct['tool_change_s'])} |",
         f"| **Total** | **{_fmt_s(ct['total_s'])}** ({ct['total_min']} min) |", "",
         "| Tool | cutting | rapid | total | feed distance |", "|---|---|---|---|---|"]
    for t, v in ct["per_tool"].items():
        L.append(f"| {t} | {_fmt_s(v['cutting_s'])} | {_fmt_s(v['rapid_s'])} | {_fmt_s(v['total_s'])} | {v['feed_distance_mm']} mm |")
    L += ["", "## Checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    names = {"gouge": "Gouge", "leftover": "Leftover above tolerance", "rapid_into_stock": "Rapid into stock",
             "flat_plunge": "Flat end mill plunge into solid", "below_fixture": "Below fixture / vise",
             "flute_length": "Engagement > flute length (warning)",
             "shank_collision": "Shank collision", "holder_collision": "Holder collision"}
    for key, nm in names.items():
        v = c[key]
        detail = ""
        if key == "gouge" and not v["ok"]:
            detail = f"{v['area_mm2']} mm2, max {v['max_depth_mm']} mm deep"
        elif key == "leftover" and v["count"]:
            detail = f"{v['area_mm2']} mm2 in {v['count']} regions, max {v['max_excess_mm']} mm"
        elif not v["ok"]:
            detail = f"{v['count']} events"
        L.append(f"| {nm} | {'OK' if v['ok'] else ('WARN' if key == 'flute_length' else 'FAIL')} | {detail} |")
    for key, nm in names.items():
        evs = c[key]["events"]
        if not evs:
            continue
        L += ["", f"### {nm}", ""]
        for e in evs[:10]:
            loc = f"line {e['nc_line']} `{e.get('block', '')}` (T{e.get('tool')})" if "nc_line" in e else ""
            xy = f"X{e['x']} Y{e['y']}" if "x" in e else ""
            extra = {kk: vv for kk, vv in e.items() if kk not in ("program", "file", "nc_line", "block", "tool", "x", "y", "first_segment", "bbox")}
            L.append(f"- {loc} at {xy} {json.dumps(extra)}")
    if r["warnings"]:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    s = r["summary"]
    L += ["", f"_{s['segments']} segments, grid {s['grid'][1]}x{s['grid'][0]} @ {s['cell_mm']} mm, "
              f"target from {s['target_source']}, runtime {r['runtime_s'].get('total', '?')} s_", ""]
    return "\n".join(L)


def main(argv=None):
    """CLI entry point: simulate NC program(s) against a part and write the report, frames and toolpath."""
    ap = argparse.ArgumentParser(description="Instant Machinist 3-axis G-code simulator / verifier")
    ap.add_argument("--part", required=True, help="part dir with features.json (+ tools.json)")
    ap.add_argument("--nc", nargs="+", required=True, help="NC program(s), run in order")
    ap.add_argument("--out", required=True, help="output dir, e.g. out/<job>/sim")
    ap.add_argument("--tools", help="tools.json overriding <part>/tools.json")
    ap.add_argument("--frames", type=int, default=360)
    ap.add_argument("--cell", type=float, default=0.25, help="check grid cell (mm)")
    ap.add_argument("--frame-cell", type=float, default=0.5, help="frame grid cell (mm, multiple of --cell)")
    ap.add_argument("--target", choices=["features", "stl", "auto"], default="features")
    ap.add_argument("--home-z", type=float, default=50.0, help="work Z of machine Z home (G53 Z0/G28/M6)")
    ap.add_argument("--vise-grip", type=float, default=6.0, help="mm of stock held in the vise jaws")
    ap.add_argument("--jaw-axis", choices=["x", "y"], default="y", help="jaws clamp the +/- faces normal to this axis")
    ap.add_argument("--fixture-mode", choices=["jaws", "plane"], default="jaws",
                    help="jaws: crash only where the tool enters jaw/parallel volumes; plane: any cut below vise top")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = simulate(a.part, a.nc, a.out, tools=a.tools, frames=a.frames, cell=a.cell, frame_cell=a.frame_cell,
                     target_mode=a.target, home_z=a.home_z, vise_grip=a.vise_grip, jaw_axis=a.jaw_axis,
                     fixture_mode=a.fixture_mode)
    except gcode.GCodeError as e:
        print(f"G-code error: {e}", file=sys.stderr)
        return 2
    if not a.quiet:
        ct = r["cycle_time"]
        print(f"{'PASS' if r['ok'] else 'FAIL'}  cycle {ct['total_min']} min  "
              + "  ".join(f"{k}={'ok' if v['ok'] else 'FAIL'}" for k, v in r["checks"].items() if isinstance(v, dict))
              + f"  runtime {r['runtime_s']['total']} s  -> {a.out}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
