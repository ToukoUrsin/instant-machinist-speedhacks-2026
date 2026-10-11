"""Live demo server: drop the customer's drawing + STEP in the browser, the real pipeline runs, the page follows it live.

    .venv/bin/python demo/live/server.py   # http://<host>:8790
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LIVE = REPO / "out" / "live"
PY = str(REPO / ".venv" / "bin" / "python")
FONTS = REPO / "instant_machinist" / "render" / "vendor" / "fonts"
# Parts the cloud Fusion path knows: STEP md5 -> part dir (features.json carries the STEP's download URL + orientation).
KNOWN = {}
for d in (REPO / "parts").iterdir():
    for s in list(d.glob("*.stp")) + list(d.glob("*.step")):
        KNOWN[hashlib.md5(s.read_bytes()).hexdigest()] = d


def post_render(run_dir: Path) -> None:
    """After programming finishes, render the simulation video of the winning program."""
    summary = json.loads((run_dir / "summary.json").read_text())
    best = summary.get("best")
    if not best:
        return
    d = Path(best["dir"])
    m, s = divmod(int(best["cycle_s"]), 60)
    badge = f"Verified: 0 gouges · {m}:{s:02d} cycle"
    part = run_dir.parent / "part"
    log = (run_dir / "render.log").open("w")
    code = ("from instant_machinist.sim.run import simulate as sim; "
            f"sim({str(part)!r}, [{str(d / '1001.nc')!r}], out={str(d / 'sim')!r}, tools={str(d / 'tools.json')!r}, frames=360, target_mode='auto')")
    subprocess.run([PY, "-c", code], cwd=REPO, stdout=log, stderr=log, check=True)
    subprocess.run([PY, "-m", "instant_machinist.render.video", "--frames", str(d / "sim/frames.npz"), "--toolpath",
                    str(d / "sim/toolpath.npz"), "--out", str(run_dir / "simulation.mp4"), "--badge", badge],
                   cwd=REPO, stdout=log, stderr=log, check=True)


def launch(job: Path) -> None:
    run_dir = job / "run"
    log = (job / "pipeline.log").open("w")
    p = subprocess.run([PY, "-m", "instant_machinist.pipeline", "--part", str(job / "part"), "--out", str(run_dir),
                        "--engine", "fusion", "--no-video"], cwd=REPO, stdout=log, stderr=log)
    if p.returncode == 0:
        try:
            post_render(run_dir)
        except Exception as e:  # noqa: BLE001
            (job / "render.err").write_text(str(e))
    (job / "exit").write_text(str(p.returncode))
    if (job / "mail.json").exists():
        try:
            import mailwatch
            mailwatch.reply(job)
            (job / "replied").write_text("1")
        except Exception as e:  # noqa: BLE001
            (job / "reply.err").write_text(repr(e))


def start_job(files: dict, mail: dict | None = None) -> Path:
    pdf = next((v for k, v in files.items() if k.lower().endswith(".pdf")), None)
    step = next((v for k, v in files.items() if k.lower().endswith((".step", ".stp"))), None)
    if pdf is None or step is None:
        raise ValueError("Send both the drawing PDF and the STEP model.")
    src = KNOWN.get(hashlib.md5(step).hexdigest())
    if src is None:
        raise ValueError("This STEP isn't uploaded to the Fusion bucket yet.")
    job = LIVE / time.strftime("%H%M%S")
    (job / "upload").mkdir(parents=True)
    for k, v in files.items():
        (job / "upload" / Path(k).name).write_bytes(v)
    shutil.copytree(src, job / "part")
    (job / "part" / "drawing.pdf").write_bytes(pdf)
    (job / "started").write_text(str(time.time()))
    if mail:
        (job / "mail.json").write_text(json.dumps(mail))
    threading.Thread(target=launch, args=(job,), daemon=True).start()
    return job


class H(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def send_file(self, p: Path, ctype: str):
        if not p.exists():
            return self.send_error(404)
        b = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path in ("/", "/index.html"):
            return self.send_file(HERE / "index.html", "text/html; charset=utf-8")
        if path.startswith("/fonts/"):
            return self.send_file(FONTS / Path(path).name, "font/otf")
        if path == "/api/latest":
            jobs = sorted(p for p in LIVE.iterdir() if (p / "started").exists())
            return self.send_json({"id": jobs[-1].name if jobs else None})
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "run":
            job = LIVE / Path(parts[2]).name
            if not job.exists():
                return self.send_error(404)
            if len(parts) == 3:
                return self.send_json(self.state(job))
            name = parts[3]
            if name == "drawing.png":
                return self.send_file(job / "part" / "drawing.png", "image/png")
            if name == "drawing.pdf":
                return self.send_file(job / "part" / "drawing.pdf", "application/pdf")
            if name == "model.png":
                return self.send_file(job / "run" / "fusion" / "model.png", "image/png")
            if name == "simulation.mp4":
                return self.send_file(job / "run" / "simulation.mp4", "video/mp4")
            if name == "1001.nc":
                s = json.loads((job / "run" / "summary.json").read_text())
                return self.send_file(Path(s["best"]["dir"]) / "1001.nc", "text/plain; charset=utf-8")
        return self.send_error(404)

    def state(self, job: Path) -> dict:
        run = job / "run"
        ev = []
        if (run / "events.jsonl").exists():
            for line in (run / "events.jsonl").read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    e.pop("ts", None)
                    ev.append(e)
        out = {"id": job.name, "started": float((job / "started").read_text()), "now": time.time(), "events": ev,
               "model": (run / "fusion" / "model.png").exists(), "video": (run / "simulation.mp4").exists(),
               "mail": json.loads((job / "mail.json").read_text()) if (job / "mail.json").exists() else None,
               "replied": (job / "replied").exists(),
               "exit": (job / "exit").read_text() if (job / "exit").exists() else None,
               "render_error": (job / "render.err").read_text() if (job / "render.err").exists() else None}
        if (run / "summary.json").exists():
            s = json.loads((run / "summary.json").read_text())
            out["summary"] = s
            if s.get("best"):
                lines = (Path(s["best"]["dir"]) / "1001.nc").read_text().splitlines()
                out["gcode"] = lines[:60]
                out["gcode_total"] = len(lines)
        return out

    def do_POST(self):
        if self.path != "/api/run":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))  # {"files": [{"name", "b64"}]}
        import base64
        files = {f["name"]: base64.b64decode(f["b64"]) for f in body["files"]}
        pdf = next((v for k, v in files.items() if k.lower().endswith(".pdf")), None)
        step = next((v for k, v in files.items() if k.lower().endswith((".step", ".stp"))), None)
        if pdf is None or step is None:
            return self.send_json({"error": "Drop both the drawing PDF and the STEP model."}, 400)
        try:
            job = start_job(files)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_json({"id": job.name, "files": sorted(files)})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    LIVE.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    import mailwatch
    threading.Thread(target=mailwatch.watch, args=(start_job, LIVE), daemon=True).start()
    print(f"live demo on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
