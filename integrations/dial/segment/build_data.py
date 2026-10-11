"""Build segment/data.js from evidence/<slug>/ (real call transcripts + extracted quotes) for segment.html.
  python3 dial/segment/build_data.py ftc-10
"""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
slug = sys.argv[1] if len(sys.argv) > 1 else "ftc-10"
ev = HERE.parent / "evidence" / slug
lines = json.loads((HERE.parent / "lines.json").read_text())
summary = json.loads((ev / "summary.json").read_text())
calls = []
for nick in ("im-supplier-pacific", "im-supplier-bayalloy"):
    tp, qp, cp = ev / f"{nick}.transcript.json", ev / f"{nick}.quote.json", ev / f"{nick}.call.json"
    if not tp.exists():
        continue
    t, c = json.loads(tp.read_text()), json.loads(cp.read_text())
    calls.append({"nick": nick, "supplier": lines[nick]["persona"], "duration": c.get("duration"),
                  "call_id": c.get("id"), "turns": t["turns"],
                  "quote": json.loads(qp.read_text()) if qp.exists() else None})
def envelope(path, a, b, fps=30):
    """Real loudness envelope of the clip (one value per video frame, 0..1) for the on-screen waveform."""
    import subprocess, numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a), "-t", str(b - a), "-i", str(path), "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = 16000 // fps
    rms = np.sqrt([np.mean(x[i:i + n] ** 2) for i in range(0, len(x) - n, n)])
    db = 20 * np.log10(rms + 1e-6)
    return [round(float(v), 3) for v in np.clip((db + 50) / 35, 0, 1)]


clip = None
cw = ev / "listen_clip_words.json"
if cw.exists():
    w = json.loads(cw.read_text())
    a, b = float(sys.argv[2]) if len(sys.argv) > 2 else 51.3, float(sys.argv[3]) if len(sys.argv) > 3 else 74.0
    clip = {"file": w["source"], "start": a, "end": b, "supplier": lines["im-supplier-pacific"]["persona"]
            if "pacific" in w["source"] else lines["im-supplier-bayalloy"]["persona"],
            "words": [x for x in w["words"] if a - 0.05 <= x["s"] < b], "env": envelope(ev / w["source"], a, b)}
data = {"slug": slug, "clip": clip, "gap": json.loads((ev / "gap.json").read_text()), "calls": calls,
        "best": summary.get("best"), "elapsed_s": summary.get("elapsed_s")}
(HERE / "data.js").write_text("window.DATA = " + json.dumps(data) + ";\n")
print("wrote", HERE / "data.js", [(c["supplier"], len(c["turns"]), c["duration"]) for c in calls])
