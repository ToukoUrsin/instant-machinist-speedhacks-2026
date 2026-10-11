"""Shop Brain: an Opus agent that answers shop questions from Keewano and makes the next decision from the answer.

    # plain-English question, answered only from live Keewano queries
    python3 shop_brain.py ask "Which strategy wins on deep pockets?"

    # decision for a new job: strategy order for the CAM search, supplier for the missing blank, bottleneck to attack
    python3 shop_brain.py decide --part runs/parts/sm-106

    # same, then run the native CAM limited to the agent's shortlist and log the outcome back to Keewano
    ... python3 shop_brain.py decide --part runs/parts/sm-106 --run

Keewano is the only memory: the agent has no local data, so without the queries it cannot rank strategies,
pick a supplier or find the bottleneck. Every answer + the exact SQL is saved to evidence/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import anthropic

from kmcp import KeewanoMCP

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1] / "instant-machinist"
PROJECT_ID = os.environ.get("KEEWANO_PROJECT_ID", "3c71f27a-eb5c-4a7d-ac74-6cab42e77661")
PROJECT_NAME = "Instant Machinist Shop Floor"
MODEL = "claude-opus-5-5"
EVIDENCE = HERE / "evidence"
GUIDE = HERE / "runtime" / "sql_guide.md"

DATA_MODEL = f"""Keewano project "{PROJECT_NAME}" (id {PROJECT_ID}) holds the shop's history as typed events.
"user_id" is an ENTITY, not a person. Two kinds:
- a CAM programming JOB (one run of the Instant Machinist pipeline). In order it emits: DataSource, Part, Material,
  Engine (native|fusion), PartQuantity, FeatureCount, PocketDepthMaxMm, HoleCount, PlateAreaCm2,
  ManualProgrammingEstimateSeconds (shop's stated manual CAM programming time, 4 h, an estimate), JobStarted,
  DrawingRead(bool), then per candidate toolpath strategy: Strategy(name) StrategyFamily(adaptive|conventional|manual)
  CycleSeconds(simulated machine time) [VerifyCheckFailed(check)] [StrategyVerified(bool: passed the G-code
  simulator's gouge/leftover/rapid/plunge/fixture/flute checks)]; OperationPlanned(op) per operation;
  then BaselineCycleSeconds (manual-style program), BestCycleSeconds, BestStrategy, MachiningSavedPct,
  JobProgrammedSeconds (agent wall time to a verified program), and StepName/StepSeconds pairs (time per pipeline step,
  names prefixed "cam.").
  Strategy "manual-baseline"/"baseline-manual" = the conservative program a human would write (the BEFORE).
- ORDER entities, one per (part, sponsor agent), each starting with Part and Sponsor:
  Sponsor "darwin" (sourcing agent): BlanksShort + Material (material gap), SourcingNeed + SourcingStatus per search,
    SourcingCapabilitiesFound, SourcingNeed + SourcingVerdict (no_fit | usable_with_human | ...), SourcingAgentSeconds
    (agent time for the sourcing plan) vs SourcingManualEstimateSeconds (estimate for doing it by hand).
  Sponsor "dial" (phone agent calling suppliers): BlanksShort, then per supplier: Supplier, SupplierCalled,
    SupplierCallOutcome, SupplierCallSeconds, SupplierLeadDays, SupplierQuotedCents (delivered price, cents).
  Sponsor "sparta" (DataSource agent_test): reliability tests of the deposit-invoice agent in a SIMULATED Stripe world,
    not real invoices: InvoiceAgentVersion (v1|v2), InvoiceTestCondition (normal|interruption|crash|crash-late|double),
    InvoiceTestRuns, DraftDepositCents (the draft it produced), InvoiceTestPassed.
  Every order entity has StepName/StepSeconds pairs = wall-clock time per phase, e.g. dial.supplier_call,
  dial.quote_extraction, darwin.agent_search, darwin.agent_connect, darwin.rank_and_plan,
  sparta.deposit_invoice_agent (per drafted invoice). CAM jobs use cam.<step>.
  The same part can appear as "NIST FTC-10" (use LIKE '%FTC-10%' when unsure).
- DECISION entities written by this agent: Part, AgentQuestionTopic, AgentDecision("key=value"). A CAM JOB whose search
  was planned by this agent also carries AgentDecision("shortlist=...") and AgentDecision("first_strategy=...") before JobStarted.
DataSource: real_run = real pipeline/sponsor run; variant_part = real CAM run on a part derived from SM-101 for the demo;
agent_test = Sparta simulated-world test.
Columns are step functions: Strategy holds until the next Strategy event, so `SELECT "Strategy", min("CycleSeconds")
... GROUP BY "Strategy"` pairs each cycle time with its strategy; Part/PocketDepthMaxMm hold for the whole job.
Filter an entity by a column set at its start (Part, Engine, Sponsor, DataSource), not by the measured column itself:
`WHERE "SupplierQuotedCents" IS NOT NULL` starts the stretch at the price event and misses the SupplierLeadDays emitted
just before it; use `WHERE "Part" LIKE '%FTC-10%' AND "Supplier" IS NOT NULL GROUP BY "Supplier"` (and group by
"Part" when comparing quotes across parts). NULL groups are dropped by GROUP BY; use count("AgentDecision") per user_id
to tell agent-planned jobs from others.
CycleSeconds/StepSeconds are seconds. Quote names with capitals in double quotes."""

SYSTEM = f"""You are Shop Brain, the planning agent of a CNC job shop running Instant Machinist (drawing + STEP in,
verified G-code out). You have NO memory of your own: every fact you state must come from a Keewano query you ran
in this conversation. Use the `sql` tool (Keewano SQL, read-only, one `events` table); use `event_types` if unsure
of a column. Prefer few, targeted queries; if a query errors, read the error and fix it. Cite numbers exactly.
Be brief: 2-5 sentences or a short table. Times in min:s when > 90 s.

{DATA_MODEL}

Keewano SQL guide (the contract):
"""

TOOLS = [
    {"name": "sql", "description": "Run a read-only Keewano SQL query on the shop's event history. Returns CSV.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"},
                                                       "why": {"type": "string", "description": "one line: what this answers"}},
                      "required": ["query", "why"]}},
    {"name": "event_types", "description": "List the project's event types (columns), optional name filter.",
     "input_schema": {"type": "object", "properties": {"nameFilter": {"type": "string"}}}},
]

DECISION_TOOL = {
    "name": "final_decision",
    "description": "Return the plan for the new job. Only call after the evidence queries ran.",
    "input_schema": {"type": "object", "properties": {
        "strategy_order": {"type": "array", "items": {"type": "string"},
                           "description": "strategies to try, best first, max 3, exact names from Keewano"},
        "skip_strategies": {"type": "array", "items": {"type": "string"}},
        "expected_cycle_s": {"type": "number"},
        "supplier": {"type": "string", "description": "supplier to order the missing blank from, or 'none'"},
        "supplier_reason": {"type": "string"},
        "bottleneck_step": {"type": "string"},
        "bottleneck_seconds": {"type": "number"},
        "before_after": {"type": "string", "description": "programming time and machine time, before vs after, from Keewano"},
        "summary": {"type": "string", "description": "3 sentences for the shop owner"}},
        "required": ["strategy_order", "supplier", "bottleneck_step", "before_after", "summary"]}}


class Brain:
    def __init__(self, verbose=True):
        self.k = KeewanoMCP()
        self.c = anthropic.Anthropic()
        self.log: list[dict] = []
        self.verbose = verbose
        if not GUIDE.exists():
            t, _ = self.k.call("get_tool_guide", {"tool": "run_sql_query", "sections": [
                "the-mental-model", "finding-out-what-columns-exist", "reference", "reading-the-result", "worked-examples"]})
            GUIDE.parent.mkdir(exist_ok=True)
            GUIDE.write_text(t)
        self.system = [{"type": "text", "text": SYSTEM + GUIDE.read_text(), "cache_control": {"type": "ephemeral"}}]

    def tool(self, name, args):
        t0 = time.time()
        if name == "sql":
            out, err = self.k.call("run_sql_query", {"projectId": PROJECT_ID, "sqlQuery": args["query"], "maxRows": 200})
        elif name == "event_types":
            out, err = self.k.call("list_event_types", {"projectId": PROJECT_ID, **({"nameFilter": args["nameFilter"]} if args.get("nameFilter") else {})})
        else:
            return "unknown tool", True
        self.log.append({"tool": name, "why": args.get("why", ""), "query": args.get("query", args.get("nameFilter", "")),
                         "error": err, "result": out[:3000], "ms": int(1000 * (time.time() - t0))})
        if self.verbose:
            print(f"  [keewano {name} {int(1000 * (time.time() - t0))} ms] {args.get('why', '')}\n    {args.get('query', '')[:300]}",
                  file=sys.stderr)
        return out[:12000], err

    def run(self, prompt, final_tool=None, max_turns=14):
        msgs = [{"role": "user", "content": prompt}]
        tools = TOOLS + ([final_tool] if final_tool else [])
        for _ in range(max_turns):
            r = self.c.messages.create(model=MODEL, max_tokens=4000, system=self.system, tools=tools, messages=msgs)
            msgs.append({"role": "assistant", "content": r.content})
            uses = [b for b in r.content if b.type == "tool_use"]
            if final_tool:
                fin = next((b for b in uses if b.name == final_tool["name"]), None)
                if fin:
                    return fin.input
            if not uses:
                text = "".join(b.text for b in r.content if b.type == "text").strip()
                if final_tool:
                    msgs.append({"role": "user", "content": f"Now call {final_tool['name']}."})
                    continue
                return text
            res = []
            for b in uses:
                out, err = self.tool(b.name, b.input)
                res.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": bool(err)})
            msgs.append({"role": "user", "content": res})
        raise RuntimeError("agent did not finish")


def save_evidence(kind: str, question: str, answer, log: list[dict]) -> Path:
    EVIDENCE.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower())[:50].strip("-")
    p = EVIDENCE / f"{time.strftime('%H%M%S')}-{kind}-{slug}.json"
    p.write_text(json.dumps({"project": PROJECT_NAME, "project_id": PROJECT_ID, "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "kind": kind, "question": question, "answer": answer, "keewano_calls": log}, indent=1))
    return p


def ask(q: str) -> str:
    b = Brain()
    a = b.run(q)
    print(a)
    print("evidence:", save_evidence("ask", q, a, b.log), file=sys.stderr)
    return a


# ---------------------------------------------------------------- decide
def part_brief(pdir: Path) -> dict:
    sys.path.insert(0, str(HERE))
    from ingest import geometry
    f = json.loads((pdir / "features.json").read_text())
    g = geometry(f)
    return {"part": f.get("part_number"), "name": f.get("name"), **g}


def log_decision(part: str, d: dict, topic: str) -> None:
    """Write the agent's decision back to Keewano so the next question can check how it played out."""
    from ingest import ev, entity_uuid, post, HASH
    key = os.environ.get("KEEWANO_API_KEY")
    if not key:
        print("(KEEWANO_API_KEY not injected: decision not logged to Keewano)", file=sys.stderr)
        return
    now = time.time()
    E = [ev("DataSource", now, "real_run"), ev("Part", now, part), ev("AgentQuestionTopic", now, topic)]
    if d.get("strategy_order"):
        E += [ev("AgentDecision", now, f"first_strategy={d['strategy_order'][0]}"),
              ev("AgentDecision", now, "shortlist=" + ",".join(d["strategy_order"]))]
    E += [ev("AgentDecision", now, f"supplier={d.get('supplier')}"),
          ev("AgentDecision", now, f"bottleneck={d.get('bottleneck_step')}")]
    inst = entity_uuid(f"decision:{part}:{int(now)}")
    post("in", {"dataSessionId": str(uuid.uuid4()), "batch": 1, "customEventsHash": HASH, "installId": inst, "events": E}, key)
    print(f"logged {len(E)} decision events to Keewano (entity decision:{part}:{int(now)})", file=sys.stderr)


def run_shortlist(pdir: Path, shortlist: list[str], out: Path) -> dict:
    """Run the real core pipeline (read-only use) with the CAM variant search limited to the agent's shortlist.
    Output (events.jsonl/summary.json) lands under runs/, so ingest.py sends the outcome to Keewano."""
    env = {**os.environ, "PYTHONPATH": str(HERE / "shim"), "IM_SHORTLIST": ",".join(shortlist)}
    t = time.time()
    r = subprocess.run([str(CORE / ".venv" / "bin" / "python"), "-m", "instant_machinist.pipeline", "--part", str(pdir.resolve()),
                        "--engine", "native", "--no-read", "--no-video", "--out", str(out.resolve())],
                       cwd=CORE, env=env, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    (out / "agent.json").write_text(json.dumps({"shortlist": shortlist, "planned_by": "shop_brain"}))
    s = json.loads((out / "summary.json").read_text())
    v = json.loads((out / "native" / "native" / "variants.json").read_text())
    return {"best": v["best"], "best_cycle_s": v["best_s"], "baseline_cycle_s": v["baseline_s"],
            "variants_tried": len(v["variants"]), "verified": bool((s.get("best") or {}).get("pass")),
            "programming_s": s["programming_s"], "wall_s": round(time.time() - t, 1), "out": str(out.relative_to(HERE))}


def decide(pdir: Path, do_run: bool) -> dict:
    brief = part_brief(pdir)
    # Require a Keewano history read before a strategy can be selected.  The
    # preflight is also captured in the evidence log for auditability.
    depth = float(brief["PocketDepthMaxMm"])
    span = max(4.0, depth * 0.5)
    lo, hi = max(0.0, depth - span), depth + span
    history_query = (
        'SELECT "Part", "PocketDepthMaxMm", "Strategy", min("CycleSeconds") AS best_cycle_s, '
        'count("StrategyVerified") AS verifications '
        'FROM events WHERE "Engine" IS NOT NULL AND "Strategy" IS NOT NULL '
        'AND "StrategyVerified" = true '
        f'AND "PocketDepthMaxMm" BETWEEN {lo:g} AND {hi:g} '
        'GROUP BY "Part", "PocketDepthMaxMm", "Strategy" ORDER BY best_cycle_s'
    )
    b = Brain()
    history, history_err = b.tool("sql", {"query": history_query, "why": "mandatory previous-run strategy history preflight"})
    if history_err:
        raise RuntimeError(f"Keewano history preflight failed; refusing to choose a strategy: {history}")
    q = (f"New job: part {brief['part']} ({brief['name']}), material {brief['Material']}, qty {brief['PartQuantity']}, "
         f"{brief['FeatureCount']} features, deepest pocket {brief['PocketDepthMaxMm']} mm, {brief['HoleCount']} holes, "
         f"plate {brief['PlateAreaCm2']:.0f} cm2. Using ONLY Keewano history: (1) which toolpath strategies should the CAM "
         f"search try first for this part (rank by simulated cycle time on the most similar past parts, especially by pocket "
         f"depth; drop strategies that failed verification or never win), (2) which supplier to buy a missing aluminum blank "
         f"from (delivered price vs lead days from past quotes), (3) which step of the order is the bottleneck (StepSeconds), "
         f"(4) before vs after: agent programming time vs the manual estimate, best vs manual-baseline machine time. "
         f"A mandatory preflight query already returned previous verified runs below; use it as evidence and run "
         f"any narrower follow-up queries needed before calling final_decision. Preflight history:\n{history}\n"
         f"Then call final_decision.")
    d = b.run(q, final_tool=DECISION_TOOL)
    d["part"] = brief
    d["history_preflight"] = {"query": history_query, "result": history}
    if do_run and d.get("strategy_order"):
        out = HERE / "runs" / f"{brief['part'].lower()}-agent-{time.strftime('%H%M%S')}"
        res = run_shortlist(pdir, d["strategy_order"], out)
        d["run"] = res
        d["run"]["matches_first_choice"] = res["best"] == d["strategy_order"][0]
    print(json.dumps({k: v for k, v in d.items() if k != "part"}, indent=1))
    print("evidence:", save_evidence("decide", q, d, b.log), file=sys.stderr)
    log_decision(brief["part"], d, "new_job_plan")
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a1 = sp.add_parser("ask")
    a1.add_argument("question", nargs="+")
    a2 = sp.add_parser("decide")
    a2.add_argument("--part", type=Path, required=True)
    a2.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "ask":
        ask(" ".join(a.question))
    else:
        decide(a.part, a.run)


if __name__ == "__main__":
    main()
