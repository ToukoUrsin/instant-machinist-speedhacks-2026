"""Derive a few sibling parts from the SM-101 plate family so the shop history has more than one part.
All CAM/sim numbers for these parts come from real native-engine runs; only the part geometry is derived.
Ingest flags them source=variant_part."""
import copy, json, shutil
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "instant-machinist" / "parts" / "sm-101"
OUT = Path(__file__).resolve().parents[1] / "runs" / "parts"
base = json.loads((CORE / "features.json").read_text())


def part(pn, name, qty, edit):
    p = copy.deepcopy(base)
    p.update(part_number=pn, name=name, quantity=qty)
    edit(p)
    d = OUT / pn.lower()
    d.mkdir(parents=True, exist_ok=True)
    (d / "features.json").write_text(json.dumps(p, indent=1))
    shutil.copy(CORE / "tools.json", d / "tools.json")


def deep(p):  # deeper centre pocket
    p["features"][2]["z_bottom"] = -14
    p["features"][5]["z_top"] = -14


def big(p):  # larger plate, bigger pocket
    p["stock"] = {"x": [-82, 82], "y": [-52, 52], "z": [-26.5, 1.5]}
    p["part_bbox"] = {"x": [-80, 80], "y": [-50, 50], "z": [-20, 0]}
    p["features"][1]["rect"].update(w=160, h=100)
    p["features"][2]["rect"].update(w=96, h=50)
    p["features"][4]["positions"] = [[-70, -40], [70, -40], [-70, 40], [70, 40]]
    p["features"][3]["rect"].update(cy=-38)


def thin(p):  # 12 mm thin plate, shallow pocket
    p["stock"]["z"] = [-18.5, 1.5]
    p["part_bbox"]["z"] = [-12, 0]
    p["features"][1]["z_bottom"] = -12
    p["features"][2]["z_bottom"] = -5
    p["features"][3]["z_bottom"] = -3
    p["features"][4]["z_bottom"] = -12
    p["features"][5].update(z_top=-5, z_bottom=-12)


def slotless(p):  # no slot, small pocket
    del p["features"][3]
    p["features"][2]["rect"].update(w=40, h=24, r=5)


part("SM-102", "Sensor mount plate, deep pocket", 40, deep)
part("SM-103", "Sensor mount plate, large", 10, big)
part("SM-104", "Sensor mount plate, thin", 60, thin)
part("SM-105", "Sensor mount plate, no slot", 25, slotless)
print("ok")


def new_job(p):  # the "new job" Shop Brain plans: deep pocket (12 mm) on a mid-size plate
    p["stock"] = {"x": [-72, 72], "y": [-47, 47], "z": [-26.5, 1.5]}
    p["part_bbox"] = {"x": [-70, 70], "y": [-45, 45], "z": [-20, 0]}
    p["features"][1]["rect"].update(w=140, h=90)
    p["features"][2]["rect"].update(w=80, h=44)
    p["features"][2]["z_bottom"] = -12
    p["features"][5]["z_top"] = -12
    p["features"][4]["positions"] = [[-60, -35], [60, -35], [-60, 35], [60, 35]]
    p["features"][3]["rect"].update(cy=-34)


part("SM-106", "Sensor mount plate, new job", 30, new_job)


def unseen(p):  # a part Shop Brain has never seen: 10 mm pocket on a 100 x 70 plate
    p["stock"] = {"x": [-52, 52], "y": [-37, 37], "z": [-26.5, 1.5]}
    p["part_bbox"] = {"x": [-50, 50], "y": [-35, 35], "z": [-20, 0]}
    p["features"][1]["rect"].update(w=100, h=70)
    p["features"][2]["rect"].update(w=56, h=30)
    p["features"][2]["z_bottom"] = -10
    p["features"][5]["z_top"] = -10
    p["features"][4]["positions"] = [[-40, -25], [40, -25], [-40, 25], [40, 25]]
    p["features"][3]["rect"].update(w=30, cy=-26)
    p["features"][5]["positions"] = [[-15, 0], [15, 0]]


part("SM-107", "Sensor mount plate, compact", 50, unseen)
