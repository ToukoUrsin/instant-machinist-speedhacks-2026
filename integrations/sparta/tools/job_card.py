"""Build a part-agnostic quote job card from Instant Machinist outputs (read-only).

    python3 sparta/tools/job_card.py <spec.json|features.json> [--summary summary.json] [--qty N]
        [--setups N] [--assume-cycle-s S] > sparta/jobs/<slug>.json

Cycle time: summary.json best.cycle_s (verified by the core simulator) when given; otherwise
--assume-cycle-s, labelled "assumed" in the card. Stock: the buy size material_gap suggests
(thickness up to 1/8 in, width and length up to 1/4 in).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # sponsors/
from shop.material_gap import gap, INV  # noqa: E402


def slug(part: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", part.lower().replace("nist ", "")).strip("-")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--summary")
    ap.add_argument("--qty", type=int)
    ap.add_argument("--setups", type=int, default=1)
    ap.add_argument("--assume-cycle-s", type=float)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    if a.qty:
        spec["quantity"] = a.qty
    g = gap(spec, json.loads(INV.read_text()))
    L, W, T = g["blank_in"]
    stock = [math.ceil(T * 8) / 8, math.ceil(W * 4) / 4, math.ceil(L * 4) / 4]  # T x W x L, inches
    if a.summary:
        s = json.loads(Path(a.summary).read_text())
        cycle, basis = s["best"]["cycle_s"], f"verified by Instant Machinist simulation ({Path(a.summary).parent.name})"
        baseline = s.get("baseline", {}).get("cycle_s")
    elif a.assume_cycle_s:
        cycle, basis, baseline = a.assume_cycle_s, "assumed (no verified simulation for this part yet)", None
    else:
        sys.exit("need --summary or --assume-cycle-s")
    card = {
        "part": spec["part_number"],
        "slug": slug(spec["part_number"]),
        "name": spec["name"].split(" (")[0],
        "material": g["material"],
        "quantity": g["qty_needed"],
        "machine": "3-axis VMC",
        "cycle_s_per_part": cycle,
        "cycle_basis": basis,
        "baseline_cycle_s_per_part": baseline,
        "setups": a.setups,
        "part_numbers_to_program": 1,
        "stock_in": {"thickness": stock[0], "width": stock[1], "length": stock[2]},
        "stock_in3_per_blank": round(stock[0] * stock[1] * stock[2], 4),
        "finish": "none (as machined)",
    }
    print(json.dumps(card, indent=1))


if __name__ == "__main__":
    main()
