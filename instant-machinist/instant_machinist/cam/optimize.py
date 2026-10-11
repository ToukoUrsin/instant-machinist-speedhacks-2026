"""Strategy variants, cycle-time scoring and the conservative manual baseline."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .plan import DEFAULT_PARAMS, plan_setup
from .post_haas import post
from .toolpath import estimate_ops

BASELINE_PARAMS = {
    "name": "manual-baseline",
    "rough_style": "conventional",
    "stepover": 0.10,        # cautious 10% stepover, slotting-style clearing
    "ap_max": 0.5,           # half-diameter depth steps
    "feed_scale": 0.6,       # low feeds and speeds
    "thinning": False,
    "helix_frac": 0.25,
    "ramp_angle": 2.0,
    "floor_stepover": 0.40,
    "face_stepover": 0.50,
    "peck_q_frac": 0.5,
}


def variants() -> list[dict]:
    """Roughing parameter variants to try: adaptive stepover/depth sweeps plus two conventional baselines."""
    out = []
    for so in (0.25, 0.35, 0.45):
        for ap in (2.0, 1.0):
            out.append({"name": f"adaptive-so{int(so * 100)}-ap{ap:g}D", "rough_style": "adaptive",
                        "stepover": so, "ap_max": ap})
    out.append({"name": "conventional-so50-ap0.5D", "rough_style": "conventional", "stepover": 0.50,
                "ap_max": 0.5, "thinning": False})
    out.append({"name": "conventional-so60-ap1D", "rough_style": "conventional", "stepover": 0.60,
                "ap_max": 1.0, "thinning": False})
    return out


def _sim_cycle():
    try:
        from instant_machinist.sim.cycle import cycle_report, segment_times
        from instant_machinist.sim.gcode import parse_programs
        return parse_programs, segment_times, cycle_report
    except Exception:
        return None


def score(nc: str, ops: list[dict], tools_doc: dict, part: dict, part_dir: Path | None = None) -> dict:
    """Cycle time from the simulator's model (instant_machinist.sim.cycle) when available, else own estimate."""
    est = estimate_ops(ops)
    sim = _sim_cycle()
    if not sim:
        return est
    parse_programs, segment_times, cycle_report = sim
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "1001.nc"
            p.write_text(nc)
            tp = parse_programs([p])
            rep = cycle_report(tp, segment_times(tp))
        rep.pop("per_tool", None)
        rep["source"] = "sim.cycle"
        rep["native_estimate_s"] = est["total_s"]
        return rep
    except Exception as e:  # simulator under construction elsewhere: fall back
        est["sim_error"] = f"{type(e).__name__}: {e}"
        return est


def build(part: dict, tools_doc: dict, params: dict) -> tuple[list[dict], str]:
    """Plan operations with ``params`` and post them; return ``(ops, nc_text)``."""
    ops = plan_setup(part, tools_doc, params)
    nc = post(ops, tools_doc, part)
    return ops, nc


def sim_verify(nc: str, part_dir: Path | None) -> dict | None:
    """Full simulator checks (gouge, leftover, rapids, plunges, fixture) if instant_machinist.sim exists."""
    if part_dir is None:
        return None
    try:
        from instant_machinist.sim.run import simulate
    except Exception:
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "1001.nc"
            p.write_text(nc)
            rep = simulate(part_dir, [p], out=None, frames=2, write_png=False)
        return {"ok": bool(rep["ok"]),
                "checks": {k: bool(v["ok"]) for k, v in rep["checks"].items() if isinstance(v, dict) and "ok" in v},
                "total_s": rep["cycle_time"]["total_s"]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def optimize(part: dict, tools_doc: dict, part_dir: Path | None = None):
    """Rank variants by cycle time; the winner is the fastest one that passes every simulator check."""
    results = []
    for v in variants():
        P = dict(DEFAULT_PARAMS, **v)
        ops, nc = build(part, tools_doc, P)
        sc = score(nc, ops, tools_doc, part, part_dir)
        results.append({"params": P, "ops": ops, "nc": nc, "time": sc, "sim": None})
    results.sort(key=lambda r: r["time"]["total_s"])
    for r in results:
        r["sim"] = sim_verify(r["nc"], part_dir)
        if r["sim"] is None or r["sim"].get("ok"):
            break
    passing = [r for r in results if r["sim"] is None or r["sim"].get("ok")]
    if passing and passing[0] is not results[0]:
        results.remove(passing[0])
        results.insert(0, passing[0])
    P = dict(DEFAULT_PARAMS, **BASELINE_PARAMS)
    ops, nc = build(part, tools_doc, P)
    baseline = {"params": P, "ops": ops, "nc": nc, "time": score(nc, ops, tools_doc, part, part_dir),
                "sim": sim_verify(nc, part_dir)}
    return results, baseline
