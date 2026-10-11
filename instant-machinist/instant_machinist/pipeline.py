"""Instant Machinist: customer drawing in -> verified CNC program, Fusion file and simulation video out.

    python -m instant_machinist.pipeline --part parts/sm-101 --engine fusion|native --out out/sm-101-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .events import Events


def simulate(part: Path, nc: Path, tools: Path, out: Path, frames: int = 0) -> dict:
    from .sim.run import simulate as sim
    return sim(str(part), [str(nc)], out=str(out), tools=str(tools), frames=frames, target_mode="auto")


def cycle_s(rep: dict) -> float:
    return float(rep["cycle_time"]["total_s"])


# Checks that must pass for any program. Leftover is required only when the program is the whole job; for an OP1 of a
# multi-setup part the remaining stock is the next setups' work and is reported, not failed.
SAFETY = ("gouge", "rapid_into_stock", "below_fixture", "flute_length")


def passed(rep: dict, whole_job: bool = True) -> bool:
    if whole_job:
        return bool(rep["ok"])
    return all(rep["checks"].get(k, {}).get("ok", True) for k in SAFETY)


def notes(rep: dict) -> str:
    c = rep["checks"]
    out = [f"{c['gouge'].get('count', 0)} gouges", f"{c['rapid_into_stock'].get('count', 0)} rapid crashes"]
    if c.get("flat_plunge", {}).get("count"):
        out.append(f"{c['flat_plunge']['count']} short plunges flagged")
    if c.get("leftover", {}).get("area_mm2"):
        out.append(f"{c['leftover']['area_mm2'] / 100:.0f} cm² left for next setups")
    return ", ".join(out)


def mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def run(part: Path, out: Path, engine: str, read: bool, video: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.jsonl").unlink(missing_ok=True)
    ev = Events(out)
    t0 = time.time()
    truth = json.loads((part / "features.json").read_text())
    spec = truth
    drawing = next((p for p in [part / "drawing.pdf", part / "drawing.png"] if p.exists()), None)
    step_url = truth.get("step_url")
    if read and drawing and step_url:
        from .drawing import read_drawing
        ev.emit("drawing", f"Reading customer drawing {drawing.name} with Claude Opus 5.5")
        s = read_drawing(drawing)
        ev.emit("drawing", f"{truth['part_number']}: {s.material}, {s.units}, ±{s.general_tolerance_mm} mm general tolerance, "
                f"{len(s.notes)} machining notes, {len(s.questions_for_customer)} questions for the customer",
                notes=s.notes, questions=s.questions_for_customer, material=s.material)
    elif read and drawing:
        from .drawing import compare, read_drawing
        ev.emit("drawing", f"Reading customer drawing {drawing.name} with Claude Opus 5.5")
        s = read_drawing(drawing)
        diffs = compare(s, truth)
        ev.emit("drawing", f"{s.part_number} {s.name}: {s.material}, qty {s.quantity}, ±{s.general_tolerance_mm} mm, "
                f"{len(s.features)} features" + (f"; differs from reference: {diffs}" if diffs else ""),
                spec=json.loads(s.model_dump_json()), notes=s.notes, questions=s.questions_for_customer)
        if not diffs:
            spec = {**truth, **{k: v for k, v in json.loads(s.model_dump_json()).items() if k != "features"},
                    "features": [{k: v for k, v in f.items() if v is not None} for f in json.loads(s.model_dump_json())["features"]]}
    (out / "spec.json").write_text(json.dumps(spec, indent=1))

    results = []
    if engine == "fusion":
        from .fusion.program import FusionProgrammer
        from .fusion.strategies import BASELINE, VARIANTS
        from .fusion.strategies import BASELINE_3D, VARIANTS_3D
        fp = FusionProgrammer(spec, out / "fusion", ev)
        whole = not step_url
        if step_url:
            fp.import_step(step_url, spec.get("step_rot_x_deg", 0))
            BASELINE, VARIANTS = BASELINE_3D, VARIANTS_3D
        else:
            fp.model()
        for strat in [BASELINE] + VARIANTS:
            d = fp.program3d(strat) if step_url else fp.program(strat)
            rep = simulate(part, d / "1001.nc", d / "tools.json", d / "sim")
            results.append({"strategy": strat["name"], "label": strat["label"], "dir": str(d), "cycle_s": cycle_s(rep),
                            "pass": passed(rep, whole), "baseline": strat is BASELINE, "checks": notes(rep)})
            ev.emit("verify", f"{strat['label']}: cycle {mmss(cycle_s(rep))}, "
                    + ("verified ✓" if passed(rep, whole) else "FAILED checks") + f" ({notes(rep)})", **results[-1])
    else:
        from .cam.run import main as native_main  # noqa: F401  (native engine CLI)
        subprocess.run([sys.executable, "-m", "instant_machinist.cam.run", "--part", str(part), "--out", str(out / "native")], check=True)
        for name, base in [("baseline", True), ("native", False)]:  # noqa: B007
            d = out / "native" / name if (out / "native" / name).exists() else (out / "native" / ("baseline" if base else ""))
            rep = simulate(part, d / "1001.nc", part / "tools.json", d / "sim")
            results.append({"strategy": name, "label": name, "dir": str(d), "cycle_s": cycle_s(rep), "pass": passed(rep), "baseline": base})
            ev.emit("verify", f"{name}: cycle {mmss(cycle_s(rep))}, " + ("verified ✓" if passed(rep) else "FAILED checks"), **results[-1])

    base = next(r for r in results if r["baseline"])
    ok = [r for r in results if r["pass"] and not r["baseline"]]
    best = min(ok, key=lambda r: r["cycle_s"]) if ok else None
    summary = {"part": spec["part_number"], "engine": engine, "programming_s": round(time.time() - t0, 1),
               "baseline": base, "best": best, "variants": results}
    if best:
        summary["machining_saved_pct"] = round(100 * (1 - best["cycle_s"] / base["cycle_s"]), 1)
        ev.emit("result", f"Best: {best['label']} — cycle {mmss(best['cycle_s'])} vs {mmss(base['cycle_s'])} typical manual "
                f"program ({summary['machining_saved_pct']}% less machine time)", **summary)
        if engine == "fusion":
            win = next(s for s in VARIANTS if s["name"] == best["strategy"])
            fp.program3d(win) if step_url else fp.program(win)
            try:
                fp.save(f"{spec['part_number']} - Instant Machinist")
            except Exception as e:
                ev.emit("fusion", f"save skipped: {e}")
        if video:
            simulate(part, Path(best["dir"]) / "1001.nc", Path(best["dir"]) / ("tools.json" if engine == "fusion" else "../../" + str(part / "tools.json")), Path(best["dir"]) / "sim", frames=360)
            badge = f"Verified: 0 gouges · {mmss(best['cycle_s'])} cycle"
            subprocess.run([sys.executable, "-m", "instant_machinist.render.video", "--frames", str(Path(best["dir"]) / "sim/frames.npz"),
                            "--toolpath", str(Path(best["dir"]) / "sim/toolpath.npz"), "--out", str(out / "simulation.mp4"), "--badge", badge], check=True)
            ev.emit("video", "Simulation video rendered", path=str(out / "simulation.mp4"))
    summary["programming_s"] = round(time.time() - t0, 1)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    ev.emit("done", f"Programmed in {mmss(summary['programming_s'])} (min:s)", **{k: summary[k] for k in ("programming_s",)})
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--part", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--engine", choices=["fusion", "native"], default="fusion")
    ap.add_argument("--no-read", action="store_true", help="skip the drawing read; use features.json")
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.part, a.out, a.engine, not a.no_read, not a.no_video), indent=1))


if __name__ == "__main__":
    main()
