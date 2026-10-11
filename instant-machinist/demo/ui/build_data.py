"""Bundle a real pipeline run into data.js for the replay UI (file:// friendly).
usage: python3 demo/ui/build_data.py <run_dir> <part_dir> [--customer X] [--title Y] [--model PNG]"""
import argparse, json, os
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
UI = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("run"); ap.add_argument("part")
ap.add_argument("--customer", default=""); ap.add_argument("--title", default=""); ap.add_argument("--model", default="")
a = ap.parse_args()
run, part = REPO / a.run, REPO / a.part
events = [json.loads(l) for l in (run / "events.jsonl").read_text().splitlines() if l.strip()]
for e in events:
    e.pop("ts", None)
    for o in e.get("ops", []) or []:
        o.pop("error", None); o.pop("warning", None)
summary = json.loads((run / "summary.json").read_text())
best = REPO / summary["best"]["dir"]
gcode = (best / "1001.nc").read_text().splitlines()
reports = {}
for v in summary["variants"]:
    rp = REPO / v["dir"] / "sim" / "report.json"
    if not rp.exists():
        continue
    r = json.loads(rp.read_text())
    reports[v["strategy"]] = {k: r["checks"].get(k, {}).get("count", 0) for k in ("gouge", "leftover", "rapid_into_stock")}
    reports[v["strategy"]]["ok"] = r.get("ok")
model = Path(a.model) if a.model else (run / "fusion" / "model.png")
if not (REPO / model).exists() and not model.is_absolute():
    model = REPO / model
rel = lambda p: os.path.relpath(REPO / p if not Path(p).is_absolute() else p, UI)
pdf = part / "drawing.pdf"
data = {"events": events, "summary": summary, "gcode": gcode[:900], "gcode_total": len(gcode), "reports": reports,
        "part": {"drawing": rel(part / "drawing.png"), "model": rel(model), "customer": a.customer, "title": a.title,
                 "file": "drawing.pdf", "file_kb": round(pdf.stat().st_size / 1024) if pdf.exists() else None,
                 "dir": part.name}}
if (run / "spec.json").exists():
    data["spec_file"] = json.loads((run / "spec.json").read_text())
wj = REPO / "out/demo/vo/solution.words.json"
if wj.exists():
    data["vo"] = {"solution": json.loads(wj.read_text()), "offset": 0.8}
(UI / "data.js").write_text("window.RUN = " + json.dumps(data) + ";\n")
print("events", len(events), "gcode", len(gcode), "model", data["part"]["model"])
