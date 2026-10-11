"""Build demo/segment.json for the on-video Keewano segment: fixed live SQL against Keewano + the latest Shop Brain
evidence (question, the SQL it ran, the answer, the decision and its measured outcome). No LLM here; numbers are live.

    python3 segment_data.py
"""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

from kmcp import KeewanoMCP
from shop_brain import PROJECT_ID, PROJECT_NAME

HERE = Path(__file__).resolve().parent
OUT = HERE / "demo" / "segment.json"

QUERIES = {
    "totals": 'SELECT count(*) AS events, count(DISTINCT user_id) AS entities FROM events',
    "event_types": 'SELECT count(DISTINCT "Part") AS parts, count("JobStarted") AS cam_jobs, count("SupplierQuotedCents") AS quotes, '
                   'count("StrategyVerified") AS verifications FROM events',
    # before / after, measured in Keewano: programmer time (manual estimate vs agent) and machine time (manual-style vs best)
    "before_after": 'SELECT "Part" AS part, "Engine" AS engine, max("ManualProgrammingEstimateSeconds") AS manual_programming_s, '
                    'min("JobProgrammedSeconds") AS agent_programming_s, max("BaselineCycleSeconds") AS manual_cycle_s, '
                    'min("BestCycleSeconds") AS best_cycle_s FROM events WHERE "Engine" IS NOT NULL GROUP BY part, engine ORDER BY part',
    "ftc10_quotes": 'SELECT "Supplier" AS supplier, min("SupplierQuotedCents") AS delivered_cents, min("SupplierLeadDays") AS lead_days, '
                    'max("SupplierCallSeconds") AS call_s FROM events WHERE "Part" LIKE \'%FTC-10%\' AND "Supplier" IS NOT NULL '
                    'GROUP BY supplier ORDER BY delivered_cents',
    "ftc10_steps": 'SELECT "StepName" AS step, sum("StepSeconds") AS seconds FROM events WHERE "Part" LIKE \'%FTC-10%\' '
                   'AND "StepName" IS NOT NULL AND "DataSource" = \'real_run\' GROUP BY step ORDER BY seconds DESC LIMIT 8',
    "ftc10_strategies": 'SELECT "Strategy" AS strategy, min("CycleSeconds") AS cycle_s, count("VerifyCheckFailed") AS failed_checks '
                        'FROM events WHERE "Part" LIKE \'%FTC-10%\' AND "CycleSeconds" IS NOT NULL GROUP BY strategy ORDER BY cycle_s',
    "agent_vs_full_search": 'SELECT "Part" AS part, user_id, count("AgentDecision") AS agent_decisions, count("CycleSeconds") AS strategies_simulated, '
                            'min("JobProgrammedSeconds") AS programming_s, min("BestCycleSeconds") AS best_cycle_s '
                            'FROM events WHERE "Part" IN (\'SM-106\', \'SM-107\') AND "Engine" IS NOT NULL '
                            'GROUP BY part, user_id ORDER BY part, agent_decisions',
}


def parse(text: str) -> dict:
    lines = text.splitlines()
    body = "\n".join(lines[1:]) if lines and lines[0].startswith("SQL result") else text
    rows = list(csv.reader(io.StringIO(body.strip())))
    return {"columns": rows[0] if rows else [], "rows": rows[1:]}


def main() -> None:
    k = KeewanoMCP()
    data = {"project": PROJECT_NAME, "project_id": PROJECT_ID, "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "queries": {}}
    for name, sql in QUERIES.items():
        t0 = time.time()
        text, err = k.call("run_sql_query", {"projectId": PROJECT_ID, "sqlQuery": sql, "maxRows": 50})
        data["queries"][name] = {"sql": sql, "ms": int(1000 * (time.time() - t0)), "error": err, **(parse(text) if not err else {"raw": text[:500]})}
        print(f"{name:22s} {data['queries'][name].get('rows', text[:200])}")
    ev = sorted((HERE / "evidence").glob("*.json"))
    data["evidence"] = [str(p.relative_to(HERE)) for p in ev]
    for kind in ("ask", "decide"):
        last = [p for p in ev if f"-{kind}-" in p.name]
        if last:
            d = json.loads(last[-1].read_text())
            data[f"latest_{kind}"] = {"file": str(last[-1].relative_to(HERE)), "question": d["question"], "answer": d["answer"],
                                      "sql": [c["query"] for c in d["keewano_calls"] if c["tool"] == "sql"]}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
