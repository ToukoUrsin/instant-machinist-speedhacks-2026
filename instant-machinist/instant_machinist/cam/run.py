"""CLI: .venv/bin/python -m instant_machinist.cam.run --part parts/sm-101 --out out/sm-101"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gparse import parse
from .optimize import optimize

TOOL_DESC = {"face_mill": "face mill", "flat": "flat end mill", "spot_drill": "spot drill", "drill": "drill",
             "ball": "ball end mill"}


def ops_doc(job: str, res: dict, tools_doc: dict, kind: str) -> dict:
    """Build the ops.json document for a CAM result (operations, params, cycle time, sim checks)."""
    ops = []
    for op in res["ops"]:
        t = tools_doc["tools"][str(op["tool"])]
        d = {k: v for k, v in op.items() if k not in ("moves", "params")}
        d["tool_desc"] = f"T{op['tool']} D{t['diameter']:g} {TOOL_DESC.get(t['type'], t['type'])}"
        ops.append(d)
    return {"job": job, "engine": "instant-machinist-native", "kind": kind, "program": 1001,
            "setup": "top", "file": "1001.nc", "variant": res["params"]["name"], "params": res["params"],
            "cycle_time": res["time"], "sim_checks": res.get("sim"), "operations": ops}


def write(out: Path, job: str, res: dict, tools_doc: dict, kind: str):
    """Write ``1001.nc`` and ``ops.json`` to ``out``, self-checking the NC with the strict parser."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "1001.nc").write_text(res["nc"])
    parse(res["nc"])  # self-check: must parse with the strict mini parser
    (out / "ops.json").write_text(json.dumps(ops_doc(job, res, tools_doc, kind), indent=2))


def main(argv=None):
    """CLI entry point: optimise native CAM for a part and write the best and baseline programs."""
    ap = argparse.ArgumentParser(description="Instant Machinist native 2.5D CAM")
    ap.add_argument("--part", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    part_dir, out = Path(a.part), Path(a.out)
    part = json.loads((part_dir / "features.json").read_text())
    tools_doc = json.loads((part_dir / "tools.json").read_text())
    job = out.name
    results, baseline = optimize(part, tools_doc, part_dir)
    best = results[0]
    write(out / "native", job, best, tools_doc, "best")
    write(out / "baseline", job, baseline, tools_doc, "baseline")
    summary = {
        "best": best["params"]["name"], "best_s": best["time"]["total_s"],
        "baseline_s": baseline["time"]["total_s"], "time_source": best["time"].get("source"),
        "saved_s": round(baseline["time"]["total_s"] - best["time"]["total_s"], 1),
        "saved_pct": round(100 * (1 - best["time"]["total_s"] / baseline["time"]["total_s"]), 1),
        "best_sim": best.get("sim"), "baseline_sim": baseline.get("sim"),
        "variants": [{"name": r["params"]["name"], "total_s": r["time"]["total_s"],
                      "source": r["time"].get("source"),
                      "sim_ok": None if r["sim"] is None else r["sim"].get("ok")} for r in results],
    }
    (out / "native" / "variants.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
