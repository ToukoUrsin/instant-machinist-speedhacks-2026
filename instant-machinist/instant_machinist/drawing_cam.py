"""Drawing -> CAD solid -> native CAM -> simulator bridge.

This is the offline handoff for customers who want the complete local path.  The
vision reader extracts a structured 2.5D specification; validation rejects
ambiguous geometry before a solid or toolpath is emitted.  The resulting
``features.json`` is the stable CAD/CAM contract used by the part builder and
native planner.

Usage::

    python -m instant_machinist.drawing_cam drawing.pdf --out out/job \\
        --tools parts/sm-101/tools.json

The drawing reader needs ``ANTHROPIC_API_KEY``.  ``--spec`` is useful for
reviewed JSON specs and deterministic offline runs.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _export_cad(model: dict, part_dir: Path) -> dict:
    """Build and export the CAD solid without requiring a drawing template."""
    import cadquery as cq
    from .parts.build_part import build_model

    part_dir.mkdir(parents=True, exist_ok=True)
    solid = build_model(model)
    step = part_dir / "part.step"
    stl = part_dir / "part.stl"
    cq.exporters.export(solid, str(step))
    cq.exporters.export(solid, str(stl), tolerance=0.02, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    return {
        "step": str(step),
        "stl": str(stl),
        "volume_mm3": round(float(solid.val().Volume()), 1),
        "bbox": [bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax],
    }


def build_from_spec(spec: dict, out: Path, tools: Path) -> dict:
    """Run validated spec -> features -> STEP/STL -> native CAM -> simulation."""
    from .drawing import spec_to_features

    out = Path(out)
    part_dir = out / "part"
    cam_dir = out / "cam"
    model = spec_to_features(spec)
    part_dir.mkdir(parents=True, exist_ok=True)
    (part_dir / "features.json").write_text(json.dumps(model, indent=2) + "\n")
    shutil.copy2(tools, part_dir / "tools.json")
    cad = _export_cad(model, part_dir)

    from .cam.run import main as cam_main
    cam_main(["--part", str(part_dir), "--out", str(cam_dir)])

    from .sim.run import simulate
    best_nc = cam_dir / "native" / "native" / "1001.nc"
    if not best_nc.exists():
        best_nc = cam_dir / "native" / "1001.nc"
    best_sim = cam_dir / "native" / "native" / "sim"
    report = simulate(part_dir, best_nc, out=best_sim, tools=part_dir / "tools.json", frames=2, write_png=False)
    result = {
        "part_number": model["part_number"],
        "features": len(model["features"]),
        "cad": cad,
        "cam_dir": str(cam_dir),
        "program": str(best_nc),
        "simulation": str(best_sim / "report.json"),
        "ok": bool(report["ok"]),
        "cycle_time": report["cycle_time"],
        "checks": report["checks"],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def run(drawing: Path | None, out: Path, tools: Path, spec_path: Path | None = None) -> dict:
    from .drawing import read_drawing

    if spec_path:
        spec = json.loads(Path(spec_path).read_text())
    elif drawing:
        spec = read_drawing(Path(drawing)).model_dump(exclude_none=True)
    else:
        raise ValueError("provide a drawing path or --spec JSON")
    return build_from_spec(spec, Path(out), Path(tools))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("drawing", nargs="?", type=Path, help="PDF, PNG, JPEG, or WEBP customer drawing")
    ap.add_argument("--spec", type=Path, help="reviewed drawing spec JSON (offline input)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tools", type=Path, required=True, help="tool crib JSON for native CAM and simulation")
    args = ap.parse_args(argv)
    print(json.dumps(run(args.drawing, args.out, args.tools, args.spec), indent=2))


if __name__ == "__main__":
    main()
