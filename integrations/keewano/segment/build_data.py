"""Build segment/data.js for segment.html from live Keewano data (demo/segment.json, rebuilt by segment_data.py) and the
Shop Brain evidence (evidence/*.json: question, every SQL call + rows, answer). No numbers are typed in by hand here.
    python3 segment/build_data.py
"""
import csv, io, json, pathlib, re, shutil

HERE = pathlib.Path(__file__).resolve().parent
K = HERE.parent
S = json.loads((K / "demo" / "segment.json").read_text())
Q = S["queries"]


def ev(prefix):
    (p,) = [p for p in (K / "evidence").glob(prefix + "*.json")]
    return json.loads(p.read_text()) | {"file": "evidence/" + p.name}


def rows(name):
    q = Q[name]
    assert not q["error"], name
    return [dict(zip(q["columns"], r)) for r in q["rows"]]


def parse_result(text):
    lines = text.splitlines()
    head = lines[0] if lines else ""
    m = re.search(r"(\d+) row\(s\)", head)
    body = list(csv.reader(io.StringIO("\n".join(lines[1:]))))
    return {"n": int(m.group(1)) if m else len(body) - 1, "columns": body[0] if body else [], "rows": body[1:]}


def call(e, i):
    c = e["keewano_calls"][i]
    return {"sql": c["query"], "ms": c["ms"], **parse_result(c["result"])}


num = lambda v: None if v in ("", None) else float(v)
tot, typ = rows("totals")[0], rows("event_types")[0]
quotes, steps, strat = rows("ftc10_quotes"), rows("ftc10_steps"), rows("ftc10_strategies")
ba, avf = rows("before_after"), rows("agent_vs_full_search")
ba_by = {(r["part"], r["engine"]): r for r in ba}

# Scene 1: real typed events (values straight from live query rows)
best_ftc, base_ftc = strat[0], [r for r in strat if int(r["failed_checks"]) > 0][0]
sm106 = ba_by[("SM-106", "native")]
chips = [
    ("Part", "String", '"NIST FTC-10"', "CAM job"),
    ("Strategy", "String", f'"{best_ftc["strategy"]}"', "CAM job"),
    ("CycleSeconds", "Integer", best_ftc["cycle_s"], "simulator"),
    ("StrategyVerified", "Boolean", "true", "simulator"),
    ("VerifyCheckFailed", "String", '"flat_plunge"', f'simulator · {base_ftc["strategy"]}'),
    ("Supplier", "String", f'"{quotes[0]["supplier"]}"', "Dial phone agent"),
    ("SupplierQuotedCents", "Price", quotes[0]["delivered_cents"], "Dial phone agent"),
    ("SupplierCallSeconds", "Integer", quotes[0]["call_s"], "Dial phone agent"),
    ("StepName", "String", f'"{steps[0]["step"]}"', "agent step"),
    ("JobProgrammedSeconds", "Integer", sm106["agent_programming_s"], "CAM job · SM-106"),
    ("BaselineCycleSeconds", "Integer", sm106["manual_cycle_s"], "CAM job · SM-106"),
    ("BestCycleSeconds", "Integer", sm106["best_cycle_s"], "CAM job · SM-106"),
    ("AgentDecision", "String", f'"supplier={quotes[0]['supplier']}"', "Shop Brain"),
]

# Scene 2: the live question
a1 = ev("211716-ask-ftc-10")
ask = {"q": a1["question"], "at": a1["at_utc"], "calls": [call(a1, 0), call(a1, 1)],
       "quotes": [{"supplier": r["supplier"], "cents": int(r["delivered_cents"]), "lead": int(r["lead_days"]), "call_s": int(r["call_s"])} for r in quotes],
       "steps": [{"step": r["step"], "s": int(r["seconds"])} for r in steps[:4]]}
assert "Bay Alloy" in a1["answer"].split("\n")[0]

# Scene 3: decision depends on the query (SM-107), plus the FTC-10 plan
d7 = ev("212033-decide-new-job-part-sm-107")
ans = d7["answer"]
full = json.loads((K / "runs" / "sm107-full" / "native" / "native" / "variants.json").read_text())
agent = json.loads((K / ans["run"]["out"] / "native" / "native" / "variants.json").read_text())
kv = {r["agent_decisions"]: r for r in avf if r["part"] == "SM-107"}  # '0' = full search job, '2' = agent-planned job
decide = {"q": d7["question"], "at": d7["at_utc"], "part": ans["part"], "order": ans["strategy_order"], "run": ans["run"],
          "call": call(d7, 1), "n_calls": len(d7["keewano_calls"]),
          "full": [{"name": v["name"], "s": v["total_s"], "ok": v.get("sim_ok")} for v in full["variants"]],
          "agent": [{"name": v["name"], "s": v["total_s"], "ok": v.get("sim_ok")} for v in agent["variants"]],
          "full_best": full["best"], "agent_best": agent["best"],
          "kw_full_sim": int(kv["0"]["strategies_simulated"]) - 1, "kw_agent_sim": int(kv["2"]["strategies_simulated"]) - 1,
          "kw_best": int(kv["2"]["best_cycle_s"]), "kw_full_best": int(kv["0"]["best_cycle_s"])}
assert decide["full_best"] == decide["agent_best"] and len(decide["agent"]) == decide["kw_agent_sim"]
d10 = ev("211824-decide-new-job-part-nist-ftc-10")
ftc = {"order": d10["answer"]["strategy_order"], "strategies": [{"name": r["strategy"], "s": int(r["cycle_s"]), "fails": int(r["failed_checks"])} for r in strat],
       "fails": ["leftover", "rapid_into_stock", "flat_plunge"]}
assert all(f in d10["answer"]["before_after"] for f in ftc["fails"])

# Scene 4: before / after measured in Keewano
before = [{"part": r["part"], "engine": r["engine"], "manual_prog": num(r["manual_programming_s"]), "agent_prog": num(r["agent_programming_s"]),
           "manual": num(r["manual_cycle_s"]), "best": num(r["best_cycle_s"])} for r in ba]
pcts = [1 - r["best"] / r["manual"] for r in before if r["manual"] and r["best"]]
native_prog = [r["agent_prog"] for r in before if r["engine"] == "native" and r["agent_prog"] is not None]
ba_out = {"sql": Q["before_after"]["sql"], "ms": Q["before_after"]["ms"], "rows": before,
          "pct_min": round(100 * min(pcts)), "pct_max": round(100 * max(pcts)),
          "native_prog_min": min(native_prog), "native_prog_max": max(native_prog),
          "fusion_prog": ba_by[("SM-101", "fusion")]["agent_programming_s"], "manual_prog": max(r["manual_prog"] for r in before)}

# Scene 5: unprepared questions
u = ev("212348-ask-if-we-run-50")
t = u["answer"]
g = lambda pat: re.search(pat, t).group(1)
unprep = {"q": u["question"], "at": u["at_utc"], "ms": [c["ms"] for c in u["keewano_calls"]], "sql": u["keewano_calls"][0]["query"],
          "saved_h": g(r"about \*\*([\d.]+) machine hours"), "manual_h": g(r"([\d.]+) h with the manual-style"),
          "agent_h": g(r"versus ([\d.]+) h with the agent"), "top_part": g(r"\*\*(SM-\d+) gains the most"),
          "top_h": g(r"gains the most\*\*, at ([\d.]+) h")}
v = ev("211742-ask-which-version")
vt = v["answer"]
inv = {"q": v["question"], "at": v["at_utc"], "ms": [c["ms"] for c in v["keewano_calls"]],
       "ship": re.search(r"shipping \*\*(v\d)\*\*", vt).group(1), "bad": re.search(r"\(\$([\d,.]+)\)\*\*", vt).group(1),
       "good": re.search(r"pass: drafted [\d,]+¢ \(\$([\d,.]+)\)", vt).group(1),
       "conds": len(re.findall(r"^\| (?!Condition|---)\**\w", vt, re.M))}

data = {"project": S["project"], "built_utc": S["built_utc"], "events": int(tot["events"]), "entities": int(tot["entities"]),
        "types": {k: int(v) for k, v in typ.items()}, "chips": chips, "ask": ask, "decide": decide, "ftc": ftc,
        "before_after": ba_out, "unprep": unprep, "inv": inv}
(HERE / "data.js").write_text("window.DATA = " + json.dumps(data) + ";\n")
assets = HERE / "assets"
assets.mkdir(exist_ok=True)
for n in ("keewano-sql-before-after.png", "keewano-sql-ftc10-quotes.png"):
    shutil.copy2(K / "demo" / n, assets / n)
print("wrote", HERE / "data.js", "| events", data["events"], "| machine time -%d..%d%%" % (ba_out["pct_min"], ba_out["pct_max"]),
      "| SM-107", decide["kw_agent_sim"], "of", decide["kw_full_sim"], decide["agent_best"], "| unprep", unprep, "| inv", inv)
