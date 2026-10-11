"""Program a part in cloud Fusion: model from the spec, try strategy variants, post Haas NC for each."""
from __future__ import annotations

import json
from pathlib import Path

from ..events import Events
from .build import script
from .session import FusionSession

DEFAULT_FOLDER = "urn:adsk.wipprod:fs.folder:co._VAyIB-zTLCsUy0QDFnBTA"  # Fusion Team: helios / Default Project


def sim_tools(table: dict) -> dict:
    """Convert a Fusion tool table into the simulator's tools.json format (mm)."""
    kind = {"face mill": "face_mill", "flat end mill": "flat", "ball end mill": "ball", "bull nose end mill": "flat",
            "spot drill": "spot_drill", "drill": "drill"}
    return {"units": "mm", "tools": {k: {"type": kind.get(t["fusion_type"], "flat"), "diameter": round(t["diameter"], 3),
                                         "flutes": t["flutes"], "flute_length": round(t["flute_length"], 2),
                                         "tip_angle": t.get("tip_angle") or 0, "description": t["desc"]}
                                     for k, t in table["tools"].items()}}


class FusionProgrammer:
    """Drives a cloud Fusion session: model the part, generate toolpaths, post NC and save."""
    def __init__(self, spec: dict, out: Path, ev: Events, session_id: str | None = None) -> None:
        import time
        session_id = session_id or f"im-{int(time.time())}"
        self.spec, self.out, self.ev = spec, Path(out), ev
        self.fs = FusionSession(session_id)
        self.out.mkdir(parents=True, exist_ok=True)

    def model(self) -> dict:
        """Start Fusion and build the 3D model from the spec; return model stats (faces, volume)."""
        self.ev.emit("fusion", "Starting Autodesk Fusion in the cloud")
        self.fs.start()
        self.fs.ts(script("model", call=f"newDoc({json.dumps(self.spec['part_number'])})"))
        r = self.fs.ts(script("model", call="buildPart(FEATURES)", FEATURES=self.spec))
        self.ev.emit("model", f"3D model built from drawing: {r['faces']} faces, {r['volume_mm3'] / 1000:.1f} cm³", **r)
        try:
            self.screenshot(self.out / "model.png")
        except Exception as e:  # screenshots are cosmetic
            self.ev.emit("model", f"screenshot skipped: {e}")
        return r

    def import_step(self, url: str, rot_x_deg: float = 0) -> dict:
        """STEP input: Fusion downloads the customer's STEP, we orient it Z-up with the top-center at the origin."""
        self.ev.emit("fusion", "Starting Autodesk Fusion in the cloud")
        self.fs.start()
        self.fs.invoke("MCP.IO", {"mode": "import", "format": "step", "downloadUrl": url, "fileName": f"{self.spec['part_number']}.stp"})
        r = self.fs.ts(script("importstep", call=f"orientImported({rot_x_deg})"))
        self.ev.emit("model", f"Customer STEP imported into Fusion: {r['faces']} faces, {r['volume_mm3'] / 1000:.1f} cm³", **r)
        try:
            self.screenshot(self.out / "model.png")
        except Exception as e:
            self.ev.emit("model", f"screenshot skipped: {e}")
        return r

    def program3d(self, strategy: dict, poll_s: float = 240) -> Path:
        """Generate 3D strategy toolpaths op by op (polling up to ``poll_s`` s), post NC and tool table.

        Returns the strategy output dir.
        """
        import time
        d = self.out / strategy["name"]
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        r = self.fs.ts(script("cam", "cam3d", call="program3d(FEATURES, STRATEGY)", FEATURES=self.spec, STRATEGY=strategy))
        for i in range(len(r["ops"])):  # generation only advances while a script runs: one op per call, in slices
            for _ in range(int(poll_s / 25) + 1):
                g = self.fs.ts(script("cam", "cam3d", call=f"genOp({i}, 25000)"))
                if g["done"]:
                    break
            r["ops"][i] = {"name": g["name"], "valid": g["valid"], "warning": g["warning"], "error": g["error"], "gen_ms": g["ms"]}
        bad = [o["name"] for o in r["ops"] if not o["valid"]]
        self.ev.emit("toolpaths", f"{strategy['label']}: {len(r['ops'])} operations generated in {time.time() - t0:.1f} s"
                     + (f" — INVALID: {bad}" if bad else ""), strategy=strategy["name"], ops=r["ops"])
        nc = self.fs.ts(script("cam", call='post("1001")'))["nc"]
        (d / "1001.nc").write_text(nc)
        tt = self.fs.ts(script("cam", call="toolTable(STRATEGY)", STRATEGY=strategy))
        (d / "tools.json").write_text(json.dumps(sim_tools(tt), indent=1))
        (d / "ops.json").write_text(json.dumps({"strategy": strategy, "ops": r["ops"]}, indent=1))
        self.ev.emit("post", f"Posted Haas G-code: {len(nc.splitlines())} lines ({', '.join(o['name'] for o in r['ops'])})", strategy=strategy["name"])
        return d

    def screenshot(self, path: Path) -> None:
        """Save an isometric screenshot of the current document to ``path``."""
        import requests
        r = json.loads(self.fs.invoke("MCP.IO", {"mode": "screenshot", "delivery": "signedUrl",
                                                 "directions": ["isoTopRight"], "width": 1600, "height": 1000}))
        path.write_bytes(requests.get(r["artifact"]["url"], timeout=60).content)

    def program(self, strategy: dict) -> Path:
        """Generate toolpaths for ``strategy``, post ``1001.nc`` and write tools.json/ops.json; return the output dir."""
        d = self.out / strategy["name"]
        d.mkdir(parents=True, exist_ok=True)
        r = self.fs.ts(script("cam", call="program(FEATURES, STRATEGY)", FEATURES=self.spec, STRATEGY=strategy))
        ops = ", ".join(o["name"] for o in r["ops"])
        bad = [o["name"] for o in r["ops"] if not o["valid"]]
        self.ev.emit("toolpaths", f"{strategy['label']}: {len(r['ops'])} operations generated in {r['gen_ms'] / 1000:.1f} s"
                     + (f" — INVALID: {bad}" if bad else ""), strategy=strategy["name"], ops=r["ops"])
        nc = self.fs.ts(script("cam", call='post("1001")'))["nc"]
        (d / "1001.nc").write_text(nc)
        tt = self.fs.ts(script("cam", call="toolTable(STRATEGY)", STRATEGY=strategy))
        (d / "tools.json").write_text(json.dumps(sim_tools(tt), indent=1))
        (d / "ops.json").write_text(json.dumps({"strategy": strategy, "ops": r["ops"]}, indent=1))
        self.ev.emit("post", f"Posted Haas G-code: {len(nc.splitlines())} lines ({ops})", strategy=strategy["name"])
        return d

    def save(self, name: str, folder_urn: str = DEFAULT_FOLDER) -> str:
        """Save the document to Fusion Team as ``name`` in ``folder_urn``."""
        r = self.fs.invoke("MCP.Documents", {"mode": "saveAs", "name": name, "targetFolderUrn": folder_urn,
                                             "description": "Programmed by Instant Machinist"})
        self.ev.emit("fusion", f"Saved editable Fusion file '{name}' to Fusion Team")
        return r
