"""Material gap check: what stock does this job need that the shop doesn't have?

    python -m shop.material_gap ../instant-machinist/out/demo-native/spec.json  > gap.json

Reads the core pipeline's spec.json (read-only) and shop_inventory.json; prints one JSON gap record.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

INV = Path(__file__).with_name("shop_inventory.json")
MM_PER_IN = 25.4
KERF_MM = 3.0  # saw kerf per cut blank


def need(spec: dict) -> dict:
    s = spec["stock"]
    dims = sorted((s[a][1] - s[a][0] for a in "xyz"), reverse=True)  # L, W, T in mm
    qty = int(spec.get("quantity", 1))
    return {"material": spec["material"], "blank_mm": [round(d, 2) for d in dims], "qty": qty}


def blanks_from(item: dict, blank: list[float]) -> int:
    """How many blanks this rack item yields (blank must fit W and T; cut along length)."""
    L, W, T = sorted(item["size_mm"], reverse=True)
    bl, bw, bt = blank
    if W < bw or T < bt:
        return 0
    per_piece = math.floor((L + KERF_MM) / (bl + KERF_MM))
    return per_piece * int(item["qty"])


def alloy(material: str) -> str:
    """'6061-T6 aluminum (assumed; ...)' -> '6061-t6 aluminum'."""
    return material.split(" (")[0].strip().lower()


def gap(spec: dict, inv: dict) -> dict:
    n = need(spec)
    have = sum(blanks_from(i, n["blank_mm"]) for i in inv["stock_rack"] if alloy(i["material"]) == alloy(n["material"]))
    short = max(0, n["qty"] - have)
    L, W, T = n["blank_mm"]
    return {
        "part": spec.get("part_number"),
        "material": n["material"].split(" (")[0].strip(),
        "material_as_drawn": n["material"],
        "blank_mm": n["blank_mm"],
        "blank_in": [round(d / MM_PER_IN, 3) for d in n["blank_mm"]],
        "qty_needed": n["qty"],
        "blanks_on_hand": have,
        "blanks_short": short,
        "missing": short > 0,
        "ask": (f"{short} blanks of {n['material'].split(' (')[0]}, at least {L/MM_PER_IN:.2f} x {W/MM_PER_IN:.2f} x {T/MM_PER_IN:.2f} in "
                f"(e.g. {math.ceil(T/MM_PER_IN*8)/8:.3f} in thick x {math.ceil(W/MM_PER_IN*4)/4:.2f} in wide flat bar, "
                f"cut to {math.ceil(L/MM_PER_IN*4)/4:.2f} in lengths)") if short else "",
    }


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(gap(spec, json.loads(INV.read_text())), indent=1))
