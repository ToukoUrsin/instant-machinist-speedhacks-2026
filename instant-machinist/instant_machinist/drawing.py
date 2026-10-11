"""Read a customer drawing with Claude Opus 5.5 vision and return the machining spec (features.json schema)."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import List, Literal, Optional

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"


class Rect(BaseModel):
    """Rounded rectangle: centre, width, height and corner radius, in drawing units."""
    cx: float
    cy: float
    w: float
    h: float
    r: float


class Feature(BaseModel):
    """One machinable feature read from the drawing (face, profile, pocket or hole)."""
    id: str
    type: Literal["face", "profile", "pocket", "hole"]
    z: Optional[float] = None
    side: Optional[Literal["outside", "inside"]] = None
    rect: Optional[Rect] = None
    z_top: Optional[float] = None
    z_bottom: Optional[float] = None
    d: Optional[float] = None
    through: Optional[bool] = None
    positions: Optional[List[List[float]]] = None


class Spec(BaseModel):
    """Structured spec extracted from a customer drawing."""
    part_number: str
    name: str
    material: str
    quantity: int
    units: Literal["mm", "in"]
    general_tolerance_mm: float
    surface_finish_ra_um: Optional[float] = None
    features: List[Feature]
    notes: List[str]
    questions_for_customer: List[str]


PROMPT = """You are a senior CNC programmer reading a customer drawing for a 3-axis job (one setup, top side).
Extract the machining spec. Coordinates: origin at the top-center of the finished part, X along the drawing's
horizontal, Y vertical, Z=0 the finished top face, Z negative down, all in mm.
Feature types: face (z=0), profile (outside rounded rect: rect cx,cy,w,h,r and z_top/z_bottom), pocket (rounded rect,
a full-round slot has r = h/2), hole (diameter d, z_top/z_bottom, through, positions [[x,y],...]). Holes that start on a
pocket floor have z_top = that floor. Always fill z_top and z_bottom for profile, pockets and holes. Give each feature an id F1, F2, ... in machining order (face, profile, pockets, holes).
Put anything a machinist must know (tolerances, finish, edge breaks) in notes, and real ambiguities in questions_for_customer."""


def read_drawing(path: Path) -> Spec:
    """Read a PDF/PNG/JPEG/WEBP drawing with Claude and return the structured ``Spec``."""
    path = Path(path)
    data = base64.standard_b64encode(path.read_bytes()).decode()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    else:
        media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix)
        if media is None:
            raise ValueError(f"unsupported drawing format {suffix}; use PDF, PNG, JPEG, or WEBP")
        block = {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
        output_format=Spec,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"drawing read failed: stop_reason={resp.stop_reason}")
    return normalize(resp.parsed_output)


def normalize(spec: Spec) -> Spec:
    """Fill hole depths the drawing implies: through holes end at the part bottom; holes inside a pocket start on its floor."""
    prof = next((f for f in spec.features if f.type == "profile"), None)
    bottom = prof.z_bottom if prof and prof.z_bottom is not None else None
    pockets = [f for f in spec.features if f.type == "pocket" and f.rect]
    for f in spec.features:
        if f.type != "hole":
            continue
        if f.z_bottom is None and f.through and bottom is not None:
            f.z_bottom = bottom
        if f.z_top is None:
            f.z_top = 0.0
            for p in pockets:
                r = p.rect
                if f.positions and all(abs(x - r.cx) < r.w / 2 and abs(y - r.cy) < r.h / 2 for x, y in f.positions):
                    f.z_top = p.z_bottom
    return spec



def validate_spec(spec: Spec | dict) -> list[str]:
    """Return deterministic, actionable issues before a drawing becomes CAD.

    The vision model can describe a drawing successfully while leaving an
    ambiguous feature or dimension unresolved.  These issues are deliberately
    data, so a caller can put them in a review packet instead of silently
    manufacturing a guessed shape.
    """
    if isinstance(spec, dict):
        spec = Spec.model_validate(spec)
    issues: list[str] = []
    profiles = [f for f in spec.features if f.type == "profile"]
    if len(profiles) != 1:
        issues.append(f"expected exactly one outside profile, found {len(profiles)}")
    for f in spec.features:
        if f.type in ("profile", "pocket"):
            if f.rect is None:
                issues.append(f"{f.id}: {f.type} has no rectangular geometry")
            if f.z_top is None or f.z_bottom is None:
                issues.append(f"{f.id}: {f.type} needs z_top and z_bottom")
            elif f.z_bottom >= f.z_top:
                issues.append(f"{f.id}: z_bottom must be below z_top")
            if f.rect is not None and (f.rect.w <= 0 or f.rect.h <= 0 or f.rect.r < 0 or 2 * f.rect.r > min(f.rect.w, f.rect.h)):
                issues.append(f"{f.id}: invalid rectangle dimensions or corner radius")
        elif f.type == "hole":
            if f.d is None or f.d <= 0:
                issues.append(f"{f.id}: hole diameter must be positive")
            if not f.positions:
                issues.append(f"{f.id}: hole has no positions")
            if f.z_top is None or f.z_bottom is None:
                issues.append(f"{f.id}: hole needs z_top and z_bottom")
        elif f.type != "face":
            issues.append(f"{f.id}: unsupported feature type {f.type}")
    if spec.quantity < 1:
        issues.append("quantity must be positive")
    if spec.general_tolerance_mm <= 0:
        issues.append("general tolerance must be positive")
    return issues


def spec_to_features(spec: Spec | dict, stock_margin_mm: float = 2.0,
                      stock_top_mm: float = 1.5, stock_bottom_margin_mm: float = 2.0) -> dict:
    """Convert a validated drawing ``Spec`` into the native CAD/CAM feature schema.

    This is the deterministic seam between drawing understanding and geometry:
    ``parts.build_part.build_model`` can turn the returned dictionary into STEP/STL,
    and ``cam.run`` can consume it for native toolpath generation.  Inches are
    normalized to millimetres.  Ambiguous or unsupported drawings raise with all
    issues together; no guessed CAD solid is emitted.
    """
    if isinstance(spec, dict):
        spec = Spec.model_validate(spec)
    issues = validate_spec(spec)
    if issues:
        raise ValueError("drawing spec is not manufacturable:\n- " + "\n- ".join(issues))
    scale = 25.4 if spec.units == "in" else 1.0
    fs = [f.model_dump(exclude_none=True) for f in spec.features]
    profile = next(f for f in fs if f["type"] == "profile")

    def rect_mm(r: dict) -> dict:
        """Rect fields converted to mm."""
        return {k: float(r[k]) * scale for k in ("cx", "cy", "w", "h", "r")}

    converted = []
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    zbottom = 0.0
    for f in fs:
        out = {"id": f["id"], "type": f["type"]}
        if f["type"] == "face":
            out["z"] = float(f.get("z", 0.0)) * scale
        elif f["type"] in ("profile", "pocket"):
            out["rect"] = rect_mm(f["rect"])
            out["z_top"] = float(f["z_top"]) * scale
            out["z_bottom"] = float(f["z_bottom"]) * scale
            if f["type"] == "profile":
                out["side"] = f.get("side", "outside")
            r = out["rect"]
            xmin, xmax = min(xmin, r["cx"] - r["w"] / 2), max(xmax, r["cx"] + r["w"] / 2)
            ymin, ymax = min(ymin, r["cy"] - r["h"] / 2), max(ymax, r["cy"] + r["h"] / 2)
            zbottom = min(zbottom, out["z_bottom"])
        elif f["type"] == "hole":
            out.update({"d": float(f["d"]) * scale,
                        "z_top": float(f["z_top"]) * scale,
                        "z_bottom": float(f["z_bottom"]) * scale,
                        "through": bool(f.get("through", False)),
                        "positions": [[float(x) * scale, float(y) * scale] for x, y in f["positions"]]})
            for x, y in out["positions"]:
                rr = out["d"] / 2
                xmin, xmax = min(xmin, x - rr), max(xmax, x + rr)
                ymin, ymax = min(ymin, y - rr), max(ymax, y + rr)
            zbottom = min(zbottom, out["z_bottom"])
        converted.append(out)
    # Stock is intentionally a little larger than finished geometry; the caller
    # can replace it with a purchased blank after the drawing review.
    margin = float(stock_margin_mm)
    stock_bottom = zbottom - float(stock_bottom_margin_mm)
    stock_top = float(stock_top_mm)
    return {
        "part_number": spec.part_number, "name": spec.name, "material": spec.material,
        "quantity": spec.quantity, "units": "mm",
        "origin": "drawing-derived top-center; Z=0 is the finished top face",
        "general_tolerance_mm": float(spec.general_tolerance_mm) * scale,
        "surface_finish_ra_um": spec.surface_finish_ra_um,
        "stock": {"x": [xmin - margin, xmax + margin], "y": [ymin - margin, ymax + margin],
                  "z": [stock_bottom, stock_top]},
        "part_bbox": {"x": [xmin, xmax], "y": [ymin, ymax], "z": [zbottom, 0.0]},
        "features": converted,
        "drawing_notes": list(spec.notes), "drawing_questions": list(spec.questions_for_customer),
        "source": "drawing_spec",
    }


def write_feature_model(spec: Spec | dict, path: Path, **kwargs) -> dict:
    """Write a drawing-derived ``features.json`` and return the written model."""
    model = spec_to_features(spec, **kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2) + "\n")
    return model

def compare(spec: Spec, truth: dict) -> list[str]:
    """Differences between the extracted spec and a reference features.json (used in tests and the demo log)."""
    def key(t, rect, d, zb, pos):
        """Rounded comparison key for a feature (type, rect, diameter, bottom Z, positions)."""
        r = tuple(round(float(rect[k]), 2) for k in ("cx", "cy", "w", "h", "r")) if rect else None
        p = tuple(sorted((round(float(x), 2), round(float(y), 2)) for x, y in pos)) if pos else None
        return (t, r, round(float(d), 2) if d else None, round(float(zb), 2) if zb is not None else None, p)

    diffs = []
    got = {key(f.type, f.rect.model_dump() if f.rect else None, f.d, f.z_bottom, f.positions) for f in spec.features}
    for f in truth["features"]:
        if f["type"] != "face" and key(f["type"], f.get("rect"), f.get("d"), f.get("z_bottom"), f.get("positions")) not in got:
            diffs.append(f"missing or different: {f['id']} {f['type']}")
    return diffs


if __name__ == "__main__":
    import sys
    s = read_drawing(Path(sys.argv[1]))
    print(s.model_dump_json(indent=2))
