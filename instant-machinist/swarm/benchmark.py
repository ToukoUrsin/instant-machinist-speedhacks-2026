#!/usr/bin/env python3
"""Reproducible simulator benchmark and regression statistics.

The harness deliberately treats the simulator as a black box.  It records
parser coverage, simulation outcomes, defect detection metrics, and timings
without changing simulator state.  Example::

    .venv/bin/python swarm/benchmark.py
    .venv/bin/python swarm/benchmark.py --skip-tests --include-large

Each invocation writes a small ``runs/<run-id>/summary.json`` and updates
``stats.json``.  Generated simulator artefacts are kept in a temporary
directory and are never checked in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Running this file directly puts ``swarm/`` on sys.path, while the package
# lives one directory above it.  Keep direct invocation and installed use
# equivalent.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    return value


def _run_tests(repo: Path, timeout: int) -> dict:
    started = time.perf_counter()
    cmd = [sys.executable, "-m", "pytest", "tests/sim", "-q", "--disable-warnings"]
    try:
        p = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=timeout)
        return {
            "command": " ".join(cmd), "returncode": p.returncode,
            "passed": p.returncode == 0, "runtime_s": round(time.perf_counter() - started, 3),
            "stdout_tail": p.stdout[-1200:], "stderr_tail": p.stderr[-1200:],
        }
    except subprocess.TimeoutExpired as e:
        return {"command": " ".join(cmd), "returncode": None, "passed": False,
                "timeout_s": timeout, "runtime_s": round(time.perf_counter() - started, 3),
                "stdout_tail": (e.stdout or "")[-1200:] if isinstance(e.stdout, str) else ""}


def _nc_files(repo: Path, include_large: bool) -> list[Path]:
    roots = [repo / "tests" / "sim" / "fixtures"]
    if include_large:
        roots += [repo / "out", repo / "parts"]
    found: list[Path] = []
    for root in roots:
        if root.exists():
            found.extend(p for p in root.rglob("*.nc") if ".git" not in p.parts)
    # Stable and bounded: avoid accidentally benchmarking generated archives.
    unique = {p.resolve(): p for p in found}
    return sorted(unique.values(), key=lambda p: str(p))[:80]


def _parse_metrics(repo: Path, include_large: bool) -> dict:
    from instant_machinist.sim.gcode import parse_programs

    rows, successes, segments = [], 0, 0
    for path in _nc_files(repo, include_large):
        start = time.perf_counter()
        try:
            tp = parse_programs(path)
            n = len(tp)
            successes += 1
            segments += n
            row = {"file": str(path.relative_to(repo)), "ok": True, "segments": n,
                   "warnings": len(tp.warnings), "runtime_s": round(time.perf_counter() - start, 4),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16]}
        except Exception as exc:  # parser robustness metric; retain class, not traceback
            row = {"file": str(path.relative_to(repo)), "ok": False,
                   "error": f"{type(exc).__name__}: {exc}",
                   "runtime_s": round(time.perf_counter() - start, 4)}
        rows.append(row)
    return {"files": len(rows), "successes": successes,
            "success_rate": successes / len(rows) if rows else None,
            "segments": segments, "cases": rows}


def _simulate_metrics(repo: Path, include_large: bool) -> dict:
    from instant_machinist.sim.run import simulate

    tiny = repo / "tests" / "sim" / "fixtures" / "tiny_block"
    fixture = repo / "tests" / "sim" / "fixtures"
    cases = [(fixture / "tiny_good.nc", False), (fixture / "sm101_good.nc", False),
             (fixture / "tiny_gouge.nc", True)]
    if include_large:
        cases += [(repo / "out" / "sm-101" / "native" / "1001.nc", False),
                  (repo / "out" / "sm-101" / "fusion" / "1001.nc", False)]
    rows = []
    with tempfile.TemporaryDirectory(prefix="im-swarm-") as td:
        for nc, expected_defect in cases:
            if not nc.exists():
                continue
            start = time.perf_counter()
            try:
                # Tiny frames keep this a fast verifier benchmark; checks still run fully.
                report = simulate(tiny if nc.name.startswith("tiny_") else repo / "parts" / "sm-101",
                                  [nc], Path(td) / nc.stem, frames=8, cell=0.5, frame_cell=1.0,
                                  write_png=False)
                detected = not bool(report["ok"])
                rows.append({"program": str(nc.relative_to(repo)), "expected_defect": expected_defect,
                             "detected_defect": detected, "ok": bool(report["ok"]),
                             "segments": report["summary"]["segments"],
                             "cycle_s": report["cycle_time"]["total_s"],
                             "runtime_s": round(time.perf_counter() - start, 4),
                             "checks_failed": [k for k, v in report["checks"].items()
                                               if isinstance(v, dict) and not v.get("ok", True)]})
            except Exception as exc:
                rows.append({"program": str(nc.relative_to(repo)), "expected_defect": expected_defect,
                             "error": f"{type(exc).__name__}: {exc}",
                             "runtime_s": round(time.perf_counter() - start, 4)})
    classified = [r for r in rows if "detected_defect" in r]
    tp = sum(r["expected_defect"] and r["detected_defect"] for r in classified)
    fp = sum(not r["expected_defect"] and r["detected_defect"] for r in classified)
    fn = sum(r["expected_defect"] and not r["detected_defect"] for r in classified)
    tn = sum(not r["expected_defect"] and not r["detected_defect"] for r in classified)
    return {"cases": rows, "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "runtime_s": round(sum(r.get("runtime_s", 0) for r in rows), 4)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--include-large", action="store_true", help="include generated native/Fusion programs")
    ap.add_argument("--test-timeout", type=int, default=180)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    out_dir = args.out_dir or (repo / "swarm")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    before = _run_tests(repo, args.test_timeout) if not args.skip_tests else {"skipped": True}
    parser = _parse_metrics(repo, args.include_large)
    simulation = _simulate_metrics(repo, args.include_large)
    stats = {"schema": 1, "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
             "git": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                                    capture_output=True).stdout.strip(),
             "python": platform.python_version(), "platform": platform.platform(),
             "tests": before, "parser": parser, "simulation": simulation,
             "wall_clock_s": round(time.perf_counter() - started, 3)}
    (run_dir / "summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps({"run_id": run_id, "tests_passed": before.get("passed"),
                      "parser_success_rate": parser["success_rate"],
                      "defect_precision": simulation["precision"], "defect_recall": simulation["recall"],
                      "wall_clock_s": stats["wall_clock_s"]}, indent=2))
    return 0 if before.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
