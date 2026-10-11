"""Build segment/data.js for segment.html from the real Sparta evidence (no hand-typed numbers).
  python3 sparta/segment/build_data.py
Sources: evidence/segment-data.json, evidence/v1-deposit-double.json, evidence/v2-deposit-double-x3.json (run 1),
evidence/traces/v1-deposit-double.jsonl, evidence/traces/v2-deposit-double-x3.jsonl (run 1).
"""
import json, pathlib

HERE = pathlib.Path(__file__).resolve().parent
EV = HERE.parent / "evidence"
seg = json.loads((EV / "segment-data.json").read_text())
v1 = json.loads((EV / "v1-deposit-double.json").read_text())
v2 = json.loads((EV / "v2-deposit-double-x3.json").read_text())
v2r1 = v2["runs"][0]


def diff_summary(run):
    d = run["snapshot"]["diff"]
    c, u = d.get("created", {}), d.get("updated", {})
    t = (u.get("tickets") or [None])[0]
    agent = [x for x in (t or {}).get("comments", []) if x["author"] == "agent"]
    return {
        "items": [{"id": i["id"], "amount": i["amount"], "invoice": i.get("invoice")} for i in c.get("invoiceitems", [])],
        "invoices": [{"id": i["id"], "total": i["total"], "status": i["status"], "lines": len(i["lines"]["data"]),
                      "customer": i["customer"]} for i in c.get("invoices", [])],
        "ticket": t and {"id": t["id"], "status": t["status"], "tags": t["tags"],
                         "public_replies": sum(x["public"] for x in agent),
                         "internal_notes": sum(not x["public"] for x in agent)},
        "before_ticket": {k: v1["snapshot"]["diff"]["before"]["tickets"]["1"][k] for k in ("status", "tags")},
        "other_changes": sorted(set(c) - {"invoiceitems", "invoices"}) + sorted(set(u) - {"tickets"})
                         + sorted(d.get("deleted", {})),
    }


def v1_timeline():
    rows = [json.loads(l) for l in (EV / "traces" / "v1-deposit-double.jsonl").read_text().splitlines() if l.strip()]
    t0 = rows[0]["t"]
    return [{"t": round((r["t"] - t0) / 1000, 2), "m": r["method"], "p": r["path"], "s": r["status"]}
            for r in rows if r["kind"] == "connector"]


def v2_timeline():
    rows = [json.loads(l) for l in (EV / "traces" / "v2-deposit-double-x3.jsonl").read_text().splitlines() if l.strip()]
    out, done, t0 = [], 0, rows[0]["t"]
    for r in rows:  # run 1 ends when both deliveries report done
        if r["kind"] == "connector" and r.get("label") in ("write",):
            out.append({"t": round((r["t"] - t0) / 1000, 2), "d": r["delivery"], "m": r["method"], "p": r["path"],
                        "s": r["status"], "replayed": bool(r.get("replayed"))})
        if r["kind"] == "skip":
            out.append({"t": round((r["t"] - t0) / 1000, 2), "d": r["delivery"], "skip": r.get("why")})
        if r["kind"] == "done":
            done += 1
            if done == 2:
                break
    return out


v1f = seg["v1_double_failure"]
v2f = seg["v2_double_fixed_run1"]
data = {
    "package": v1["package"], "seed_hash": v1["seedHash"], "input_digest": v1["inputDigest"],
    "same_inputs": v1["seedHash"] == v2r1["seedHash"] and v1["inputDigest"] == v2r1["inputDigest"]
                   and v1["missionId"] == v2r1["missionId"],
    "task": seg["task"],
    "n_checks": len(v1f["checks"]),
    "v1": {"invoice": v1f["invoices"][0], "ticket": v1f["ticket_1"], "checks": v1f["checks"],
           "diff": diff_summary(v1), "timeline": v1_timeline()},
    "v2": {"invoice": v2f["invoices"][0], "ticket": v2f["ticket_1"], "checks": v2f["checks"],
           "diff": diff_summary(v2r1), "timeline": v2_timeline(),
           "runs": v2["completedRuns"], "passed_runs": sum(r["grade"]["passed"] for r in v2["runs"])},
    "scoreboard": seg["scoreboard"],
}
assert data["same_inputs"], "v1 and v2 double runs must share seed, inputs and mission"
(HERE / "data.js").write_text("window.DATA = " + json.dumps(data) + ";\n")
print("wrote", HERE / "data.js", len((HERE / "data.js").read_text()), "bytes;",
      "v1 diff", len(data["v1"]["diff"]["items"]), "items", data["v1"]["diff"]["invoices"],
      "| v2 diff", len(data["v2"]["diff"]["items"]), "items", data["v2"]["diff"]["invoices"],
      "| v2 timeline", len(data["v2"]["timeline"]))
