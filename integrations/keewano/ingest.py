"""Instant Machinist -> Keewano: map every CAM job and every sponsor step into small typed events.

    python3 ingest.py            # send everything new
    python3 ingest.py --dry-run                                        # print what would be sent

Sources (read-only):
  ../../instant-machinist/out/*/events.jsonl   core pipeline runs (real)
  runs/*/events.jsonl                          native pipeline runs made for this track (real; parts SM-102..105
                                               are derived from SM-101 -> DataSource "variant_part")
  ../out/<part-slug>/<sponsor>.events.jsonl     Darwin / Dial / Sparta sponsor agents (real)

Entities (Keewano installId, UUIDv5):
  job:<run dir>:<first ts>   one CAM programming job
  order:<part slug>          the shop order around a part: material gap, sourcing, supplier calls, quote, deposit

Idempotent: runtime/ledger.json remembers the last timestamp sent per entity; re-running only sends newer events.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import uuid
import zlib
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                     # .../speedruninstanmachinist
CORE_OUT = ROOT / "instant-machinist" / "out"
CORE_PARTS = ROOT / "instant-machinist" / "parts"
SPONSOR_OUT = HERE.parent / "out"
RUNS = HERE / "runs"
LEDGER = HERE / "runtime" / "ledger.json"
API = "https://api.keewano.com/event/ingress/v1/json"
MANUAL_PROGRAMMING_S = 4 * 3600            # shop's stated manual CAM programming time per job (~4 h), an estimate

# Append-only catalog. Never change a type; add a new id instead.
CATALOG = [
    (2000, "Part", "string"), (2001, "Material", "string"), (2002, "Engine", "string"),
    (2003, "DataSource", "string"), (2004, "JobStarted", "none"), (2005, "DrawingRead", "bool"),
    (2006, "FeatureCount", "uint"), (2007, "PocketDepthMaxMm", "uint"), (2008, "HoleCount", "uint"),
    (2009, "OperationPlanned", "string"), (2010, "Strategy", "string"), (2011, "StrategyVerified", "bool"),
    (2012, "CycleSeconds", "uint"), (2013, "JobProgrammedSeconds", "uint"), (2014, "BaselineCycleSeconds", "uint"),
    (2015, "BestCycleSeconds", "uint"), (2016, "MachiningSavedPct", "uint"),
    (2017, "ManualProgrammingEstimateSeconds", "uint"), (2018, "BestStrategy", "string"),
    (2019, "StepName", "string"), (2020, "StepSeconds", "uint"), (2021, "BlanksShort", "uint"),
    (2022, "SourcingNeed", "string"), (2023, "SourcingStatus", "string"),
    (2024, "SourcingCapabilitiesFound", "uint"), (2025, "SourcingAgentSeconds", "uint"),
    (2026, "SourcingManualEstimateSeconds", "uint"), (2027, "Supplier", "string"), (2028, "SupplierCalled", "none"),
    (2029, "SupplierCallSeconds", "uint"), (2030, "SupplierQuotedCents", "price_usd_cent"),
    (2031, "SupplierLeadDays", "uint"), (2032, "DepositInvoicedCents", "price_usd_cent"),
    (2033, "AgentDecision", "string"), (2034, "AgentQuestionTopic", "string"), (2035, "PartQuantity", "uint"),
    (2036, "StrategyFamily", "string"), (2037, "PlateAreaCm2", "uint"), (2038, "VerifyCheckFailed", "string"),
    (2039, "Sponsor", "string"), (2040, "SupplierCallOutcome", "string"),
    (2041, "SourcingVerdict", "string"), (2042, "InvoiceAgentVersion", "string"), (2043, "InvoiceTestCondition", "string"),
    (2044, "InvoiceTestPassed", "bool"), (2045, "InvoiceTestRuns", "uint"), (2046, "DraftDepositCents", "price_usd_cent"),
    # Append-only telemetry types. Keewano custom events accept strings (not
    # arbitrary doubles), so coordinates stay signed and lossless as text.
    (2047, "CoordinateX", "string"), (2048, "CoordinateY", "string"), (2049, "CoordinateZ", "string"),
    (2050, "CoordinateUnits", "string"), (2051, "ReferenceFrame", "string"),
    (2052, "VerificationStatus", "string"), (2053, "VerifierResult", "string"),
]
ID = {n: i for i, n, _ in CATALOG}
TYPE = {n: t for _, n, t in CATALOG}
CUSTOM = [{"eventTypeId": i, "name": n, "dataType": t} for i, n, t in CATALOG]
HASH = zlib.crc32(json.dumps(CUSTOM, sort_keys=True).encode()) or 1


def entity_uuid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "instant-machinist/" + key))


def ev(name: str, ts: float, value=None) -> dict:
    t = TYPE[name]
    e = {"eventTypeId": ID[name], "dataType": t, "timestamp": int(ts)}
    if t == "none":
        return e
    if t == "double":
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value!r}")
    elif t in ("uint", "price_usd_cent"):
        value = max(0, int(round(float(value))))
    elif t == "bool":
        value = bool(value)
    else:
        value = str(value)[:256]
    e["data"] = value
    return e


def slug(part: str) -> str:
    s = part.lower().replace("nist ", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def family(strategy: str) -> str:
    s = strategy.lower()
    if "baseline" in s or "manual" in s:
        return "manual"
    if "adaptive" in s:
        return "adaptive"
    if "conventional" in s:
        return "conventional"
    return s.split("-")[0]


def read_jsonl(p: Path) -> list[dict]:
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def find_part_dir(part: str, run: Path) -> Path | None:
    s = slug(part)
    for d in (RUNS / "parts" / s, CORE_PARTS / s):
        if (d / "features.json").exists():
            return d
    return None


def geometry(features: dict) -> dict:
    feats = features.get("features", [])
    pockets = [f for f in feats if f.get("type") == "pocket"]
    depth = max((abs(f.get("z_bottom", 0) - f.get("z_top", 0)) for f in pockets), default=0)
    if not feats and features.get("part_bbox", {}).get("z"):  # STEP-driven part (e.g. FTC-10): use the part's Z depth
        z = features["part_bbox"]["z"]
        depth = abs(z[1] - z[0])
    holes = sum(len(f.get("positions", [])) for f in feats if f.get("type") == "hole")
    bb = features.get("part_bbox", {})
    area = 0
    if bb.get("x") and bb.get("y"):
        area = (bb["x"][1] - bb["x"][0]) * (bb["y"][1] - bb["y"][0]) / 100
    return {"FeatureCount": len(feats), "PocketDepthMaxMm": depth, "HoleCount": holes, "PlateAreaCm2": area,
            "Material": features.get("material", ""), "PartQuantity": features.get("quantity", 1)}


# ---------------------------------------------------------------- core CAM jobs
def job_events(run: Path) -> tuple[str, str, list[dict]] | None:
    rows = read_jsonl(run / "events.jsonl")
    if not any(r.get("step") == "verify" for r in rows):
        return None
    rows.sort(key=lambda r: r["ts"])
    t0 = rows[0]["ts"]
    rel = str(run.relative_to(ROOT))
    key = f"job:{rel}:{int(t0)}"
    summ = json.loads((run / "summary.json").read_text()) if (run / "summary.json").exists() else {}
    result = next((r for r in rows if r.get("step") == "result"), {})
    part = summ.get("part") or result.get("part") or next((r.get("body") for r in rows if r.get("body")), None)
    spec = json.loads((run / "spec.json").read_text()) if (run / "spec.json").exists() else {}
    part = part or spec.get("part_number") or "unknown"
    engine = summ.get("engine") or result.get("engine") or ("fusion" if (run / "fusion").exists() else "native")
    pdir = find_part_dir(part, run)
    geo = geometry(spec if spec.get("features") else json.loads((pdir / "features.json").read_text()) if pdir else {})
    source = "variant_part" if str(pdir or "").startswith(str(RUNS)) else "real_run"

    E = [ev("DataSource", t0 - 3, source), ev("Part", t0 - 3, part), ev("Material", t0 - 3, geo["Material"] or "?"),
         ev("Engine", t0 - 3, engine), ev("PartQuantity", t0 - 3, geo["PartQuantity"]),
         ev("FeatureCount", t0 - 2, geo["FeatureCount"]), ev("PocketDepthMaxMm", t0 - 2, geo["PocketDepthMaxMm"]),
         ev("HoleCount", t0 - 2, geo["HoleCount"]), ev("PlateAreaCm2", t0 - 2, geo["PlateAreaCm2"]),
         ev("ManualProgrammingEstimateSeconds", t0 - 1, MANUAL_PROGRAMMING_S)]
    agent = json.loads((run / "agent.json").read_text()) if (run / "agent.json").exists() else None
    if agent:  # a job whose CAM search was planned by Shop Brain from Keewano history
        E += [ev("AgentQuestionTopic", t0 - 1, "new_job_plan"), ev("AgentDecision", t0 - 1, "shortlist=" + ",".join(agent["shortlist"])),
              ev("AgentDecision", t0 - 1, f"first_strategy={agent['shortlist'][0]}")]
    E.append(ev("JobStarted", t0))

    vfile = run / "native" / "native" / "variants.json"
    v = json.loads(vfile.read_text()) if vfile.exists() else {}
    real_name = {"native": v.get("best", "native"), "baseline": "manual-baseline"} if v else {}

    for r in rows:
        ts, step = r["ts"], r.get("step")
        if r.get("strategy") in real_name:
            r = {**r, "strategy": real_name[r["strategy"]]}
        if step == "result" and real_name:
            r = {**r, "best": {**(r.get("best") or {}), "strategy": real_name["native"]}}
        if step == "drawing" and "spec" in r:
            E.append(ev("DrawingRead", ts, "differs" not in r.get("msg", "")))
        elif step == "toolpaths" and r.get("ops"):
            E.append(ev("Strategy", ts, r.get("strategy", "?")))
            for op in r["ops"]:
                E.append(ev("OperationPlanned", ts, op.get("name", "?")))
        elif step == "verify":
            strat = r.get("strategy", "?")
            E += [ev("Strategy", ts, strat), ev("StrategyFamily", ts, family(strat)),
                  ev("CycleSeconds", ts, r.get("cycle_s", 0))]
            if not r.get("pass"):
                for chk in failed_checks((ROOT / "instant-machinist" / r.get("dir", "")).resolve()):
                    E.append(ev("VerifyCheckFailed", ts, chk))
            E.append(ev("StrategyVerified", ts, r.get("pass")))
            E += _verification_events(run, r)
        elif step == "result":
            best, base = r.get("best") or {}, r.get("baseline") or {}
            E += [ev("BaselineCycleSeconds", ts, base.get("cycle_s", 0)), ev("BestCycleSeconds", ts, best.get("cycle_s", 0)),
                  ev("BestStrategy", ts, best.get("strategy", "?")), ev("MachiningSavedPct", ts, r.get("machining_saved_pct", 0))]
        elif step == "done":
            E.append(ev("JobProgrammedSeconds", ts, r.get("programming_s", 0)))

    # native engine: the optimizer scored more variants than the pipeline re-verified; add their simulated cycles
    if v:
        ts = next((r["ts"] for r in rows if r.get("step") == "verify"), t0) - 0.5
        for var in v.get("variants", []):
            if var["name"] == v.get("best"):
                continue  # re-verified by the pipeline above
            E += [ev("Strategy", ts, var["name"]), ev("StrategyFamily", ts, family(var["name"])),
                  ev("CycleSeconds", ts, var["total_s"])]
        nops = json.loads((run / "native" / "native" / "ops.json").read_text()).get("operations", []) \
            if (run / "native" / "native" / "ops.json").exists() else []
        for op in nops:
            E.append(ev("OperationPlanned", ts, op.get("strategy", op.get("name", "?"))))

    # Keep signed XYZ values and their units/frame alongside the strategy telemetry.
    E += _coordinate_events(run, t0, spec, rows)

    # wall time before each event is charged to that event's step, emitted at the event (append-only: a job that is
    # still running when ingest runs gets its later steps on the next ingest, never twice)
    if rows[0].get("t", 0) > 0:  # time from job start to the first event
        E += [ev("StepName", rows[0]["ts"], f"cam.{rows[0].get('step', '?')}"), ev("StepSeconds", rows[0]["ts"], rows[0]["t"])]
    for prev, r in zip(rows, rows[1:]):
        gap = r["ts"] - prev["ts"]
        if 0 < gap <= 3600:
            E += [ev("StepName", r["ts"], f"cam.{r.get('step', '?')}"), ev("StepSeconds", r["ts"], gap)]
    E.sort(key=lambda e: e["timestamp"])  # stable: keeps context-before-value order within a second
    return key, part, E


def failed_checks(variant_dir: Path) -> list[str]:
    rep = variant_dir / "sim" / "report.json"
    if not rep.exists():
        return []
    checks = json.loads(rep.read_text()).get("checks", {})
    return [k for k, c in checks.items() if isinstance(c, dict) and c.get("ok") is False]


_AXIS = re.compile(r"(?<![A-Za-z])([XYZ])([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)")


def _nc_coordinates(run: Path) -> list[tuple[float, float, float]]:
    """Read modal XYZ positions from posted NC without normalising signed values."""
    points: list[tuple[float, float, float]] = []
    x = y = z = 0.0
    for nc in sorted(run.rglob("*.nc")):
        for line in nc.read_text(errors="replace").splitlines():
            # Ignore parenthesized comments, but retain signed coordinates in motion words.
            vals = {axis: float(raw) for axis, raw in _AXIS.findall(line.split("(", 1)[0])}
            if not vals:
                continue
            x, y, z = vals.get("X", x), vals.get("Y", y), vals.get("Z", z)
            points.append((x, y, z))
    return points


def _sample_coordinates(points: list[tuple[float, float, float]], limit: int = 256) -> list[tuple[float, float, float]]:
    """Bound telemetry volume while retaining signed extrema and trace endpoints."""
    if len(points) <= limit:
        return points
    indexes = {0, len(points) - 1}
    for axis in range(3):
        indexes.add(min(range(len(points)), key=lambda i: points[i][axis]))
        indexes.add(max(range(len(points)), key=lambda i: points[i][axis]))
    stride = (len(points) - 1) / max(1, limit - len(indexes))
    indexes.update(round(i * stride) for i in range(max(0, limit - len(indexes))))
    return [points[i] for i in sorted(indexes)]


def _coordinate_events(run: Path, ts: float, spec: dict, rows: list[dict]) -> list[dict]:
    """Persist coordinates, units, and the source reference frame in Keewano."""
    units = spec.get("units") or "mm"
    frame = spec.get("reference_frame") or "workpiece-top-center"
    E = [ev("CoordinateUnits", ts - 2, units), ev("ReferenceFrame", ts - 2, frame)]
    points: list[tuple[float, float, float]] = []
    for row in rows:
        raw = row.get("xyz") or row.get("position") or row.get("coords")
        if isinstance(raw, dict):
            raw = [raw.get("x"), raw.get("y"), raw.get("z")]
        if isinstance(raw, (list, tuple)) and len(raw) == 3 and all(v is not None for v in raw):
            points.append(tuple(float(v) for v in raw))
    if not points:
        points = _nc_coordinates(run)
    points = _sample_coordinates(points)
    for x, y, z in points:
        E += [ev("CoordinateX", ts, x), ev("CoordinateY", ts, y), ev("CoordinateZ", ts, z)]
    return E


def _verification_events(run: Path, row: dict) -> list[dict]:
    """Persist aggregate status and each simulator verifier result in Keewano."""
    ts = row["ts"]
    E = [ev("VerificationStatus", ts, "passed" if row.get("pass") else "failed")]
    variant = (ROOT / "instant-machinist" / row.get("dir", "")).resolve()
    report = variant / "sim" / "report.json"
    checks = json.loads(report.read_text()).get("checks", {}) if report.exists() else {}
    for name, result in checks.items():
        ok = result.get("ok") if isinstance(result, dict) else bool(result)
        E.append(ev("VerifierResult", ts, json.dumps({"check": name, "ok": bool(ok)}, sort_keys=True)))
    return E


# ---------------------------------------------------------------- sponsor order events
# wall-clock time between consecutive events is charged to the later event's step, grouped into readable phases
STEP_GROUPS = {
    "dial": {"gap": "material_gap", "calling": "dialing", "call_placed": "dialing", "call_state": "supplier_call",
             "call_ended": "supplier_call", "recording": "quote_extraction", "quote": "quote_extraction",
             "result": "quote_extraction"},
    "darwin": {"start": "setup", "gap": "material_gap", "tools": "setup", "search": "agent_search",
               "search_error": "agent_search", "question": "agent_search", "agent": "agent_search", "found": "agent_search",
               "connect": "agent_connect", "probe": "agent_connect", "live_call": "agent_connect", "rank": "rank_and_plan",
               "plan": "rank_and_plan", "verdict": "rank_and_plan"},
    "sparta": {"run": "deposit_invoice_agent"},
}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def sponsor_events(f: Path) -> tuple[str, str, list[dict]] | None:
    """One entity per (part, sponsor agent): each file is append-only in time, so per-entity order always holds."""
    sp = f.name.split(".")[0]
    rows = [dict(r, _sponsor=sp) for r in read_jsonl(f) if "ts" in r]
    if not rows:
        return None
    rows.sort(key=lambda r: r["ts"])
    part = next((r.get("part") for r in rows if r.get("part")), f.parent.name.upper())
    key = f"order:{f.parent.name}:{sp}"
    t0 = rows[0]["ts"]
    E = [ev("DataSource", t0 - 2, "agent_test" if sp == "sparta" else "real_run"), ev("Part", t0 - 2, part),
         ev("Sponsor", t0 - 2, sp)]
    by_sponsor: dict[str, list] = {}
    for r in rows:
        by_sponsor.setdefault(r["_sponsor"], []).append(r)
        ts, step, sp = r["ts"], r.get("step", ""), r["_sponsor"]
        if r.get("blanks_short") is not None or (step.endswith("gap") and r.get("qty") is not None):
            E.append(ev("BlanksShort", ts, r.get("blanks_short", r.get("qty"))))
            if r.get("material"):
                E.insert(-1, ev("Material", ts, r["material"]))
        if step.endswith(".search") and r.get("need"):
            E += [ev("SourcingNeed", ts, r["need"]), ev("SourcingStatus", ts, r.get("status", "?"))]
        if step.endswith(".search_error") and r.get("need"):
            E += [ev("SourcingNeed", ts, r["need"]), ev("SourcingStatus", ts, f"http_{r.get('http', 'error')}")]
        if step.endswith(".found") and r.get("capabilities") is not None:
            E.append(ev("SourcingCapabilitiesFound", ts, r["capabilities"]))
        if r.get("agent_s") is not None:
            E.append(ev("SourcingAgentSeconds", ts, r["agent_s"]))
        if r.get("baseline_min_estimate") is not None:
            E.append(ev("SourcingManualEstimateSeconds", ts, 60 * r["baseline_min_estimate"]))
        if r.get("supplier") and step in ("call_placed", "calling_supplier"):
            E += [ev("Supplier", ts, r["supplier"]), ev("SupplierCalled", ts)]
        if r.get("supplier") and r.get("duration_s") is not None:
            E += [ev("Supplier", ts, r["supplier"]), ev("SupplierCallOutcome", ts, r.get("termination", "?")),
                  ev("SupplierCallSeconds", ts, r["duration_s"])]
        price = next((num(r.get(k)) for k in ("landed_total", "unit_price_usd", "unit_price", "price_usd", "quote_usd", "total")
                      if num(r.get(k)) is not None), None) if r.get("supplier") and sp != "sparta" else None
        cents = num(r.get("unit_price_cents")) or (price * 100 if price is not None else None)
        if cents is not None:
            if r.get("supplier"):
                E.append(ev("Supplier", ts, r["supplier"]))
            if r.get("lead_days") is not None:
                E.append(ev("SupplierLeadDays", ts, r["lead_days"]))
            E.append(ev("SupplierQuotedCents", ts, cents))
        elif r.get("lead_days") is not None:
            if r.get("supplier"):
                E.append(ev("Supplier", ts, r["supplier"]))
            E.append(ev("SupplierLeadDays", ts, r["lead_days"]))
        amt = next((num(r.get(k)) for k in ("deposit_usd", "amount_usd", "amount", "total_usd", "total") if num(r.get(k)) is not None), None)
        if step.endswith(".verdict") and r.get("need"):
            E += [ev("SourcingNeed", ts, r["need"]), ev("SourcingVerdict", ts, r.get("verdict", "?"))]
        if sp == "sparta" and r.get("agent") and r.get("runs") is not None:
            # Sparta Worlds = simulated Stripe + ticket desk: reliability tests of the deposit-invoice agent, not real invoices
            ok = r.get("passed") == r["runs"]
            E += [ev("InvoiceAgentVersion", ts, r["agent"]), ev("InvoiceTestCondition", ts, r.get("condition", "?")),
                  ev("InvoiceTestRuns", ts, r["runs"])]
            if r.get("invoices_created") and r.get("draft_total_cents"):
                E.append(ev("DraftDepositCents", ts, r["draft_total_cents"][0]))
            E.append(ev("InvoiceTestPassed", ts, ok))
            continue
        if amt is not None and ("invoice" in step or "deposit" in step or sp == "sparta"):
            cents_amt = amt if r.get("amount_cents") else amt * 100
            E.append(ev("DepositInvoicedCents", ts, num(r.get("amount_cents")) or cents_amt))
    # per-step time: the gap before each sponsor event is charged to that event's step (append-only, so re-runs of
    # ingest never double count); gaps > 10 min mean a new agent run, not work
    for sp, rs in by_sponsor.items():
        for prev, r in zip(rs, rs[1:]):
            if r.get("agent_ms") and r.get("runs"):  # Sparta: agent time per drafted invoice
                gap = r["agent_ms"] / 1000 / r["runs"]
            else:
                gap = r["ts"] - prev["ts"]
            if 0 < gap <= 600:
                name = r.get("step", "?").split(".")[-1]
                name = f"{sp}.{STEP_GROUPS.get(sp, {}).get(name, name)}"
                E += [ev("StepName", r["ts"], name), ev("StepSeconds", r["ts"], gap)]
    E.sort(key=lambda e: e["timestamp"])
    return key, part, E


# ---------------------------------------------------------------- transport
def post(path: str, body: dict, key: str) -> dict:
    req = Request(f"{API}/{path}", data=json.dumps(body).encode(),
                  headers={"k-token": key, "Content-Type": "application/json"})
    with urlopen(req, timeout=60) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw.strip() else {}


def collect() -> list[tuple[str, str, list[dict]]]:
    out = []
    runs = sorted({p.parent for p in list(CORE_OUT.glob("*/events.jsonl")) + list(RUNS.glob("*/events.jsonl"))})
    for run in runs:
        j = job_events(run)
        if j:
            out.append(j)
    for f in sorted(SPONSOR_OUT.glob("*/*.events.jsonl")):
        s = sponsor_events(f)
        if s:
            out.append(s)
    return out


def send(entity_key: str, events: list[dict], api_key: str, ledger: dict) -> int:
    state = ledger.get(entity_key, {})
    last = state.get("last_ts", -1)
    schema_changed = bool(state) and state.get("catalog_hash") != HASH
    # A catalog migration adds telemetry to already-ingested jobs with historical
    # timestamps.  Send only the appended event types on the first run so the
    # signed-coordinate/status migration is not hidden by the timestamp ledger or
    # by duplicate replay of every legacy event.
    if schema_changed:
        new = [e for e in events if e["eventTypeId"] >= 2047]
    else:
        new = [e for e in events if e["timestamp"] > last]
    if not new:
        if schema_changed and entity_key in ledger:
            ledger[entity_key]["catalog_hash"] = HASH
        return 0
    inst = entity_uuid(entity_key)
    batch = ledger.get(entity_key, {}).get("batch", 0)
    for i in range(0, len(new), 200):
        batch += 1
        chunk = new[i:i + 200]
        post("in", {"dataSessionId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{inst}/{batch}")), "batch": batch,
                    "customEventsHash": HASH, "installId": inst, "events": chunk}, api_key)
    ledger[entity_key] = {"last_ts": max(last, max(e["timestamp"] for e in new)), "batch": batch, "installId": inst,
                          "catalog_hash": HASH,
                          "sent": ledger.get(entity_key, {}).get("sent", 0) + len(new)}
    return len(new)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="substring filter on entity key")
    a = ap.parse_args()
    ents = [e for e in collect() if not a.only or a.only in e[0]]
    if a.dry_run:
        for k, part, E in ents:
            names = {}
            for e in E:
                n = next(n for i, n, _ in CATALOG if i == e["eventTypeId"])
                names[n] = names.get(n, 0) + 1
            print(f"{k}  part={part}  events={len(E)}  {names}")
        return
    key = os.environ["KEEWANO_API_KEY"]
    print("register custom events:", post("custom", {"customEventsHash": HASH, "eventTypes": CUSTOM}, key))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {}
    total = 0
    for k, part, E in ents:
        n = send(k, E, key, ledger)
        total += n
        print(f"{k:70s} {part:14s} sent {n:4d} new events")
        LEDGER.write_text(json.dumps(ledger, indent=1))
    print(f"done: {total} new events, {len(ents)} entities, {time.strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
