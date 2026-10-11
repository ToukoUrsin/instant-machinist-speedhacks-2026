"""Broad Darwin coverage scan for machine-shop needs (read-only). Writes evidence/explore.json.
Usage (from integrations/): python3 darwin/explore.py"""
import json, os, sys, time, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_sources import darwin_search, cap_details  # noqa: E402

QUERIES = {
    "metal stock": ["Buy aluminum bar stock cut to size online", "metal service center quote for aluminum plate"],
    "industrial supply": ["Industrial MRO supply catalog search for fasteners and shop supplies"],
    "cutting tools": ["Buy carbide end mills and drills for aluminum CNC machining", "speeds and feeds calculator for end mills"],
    "finishing": ["Anodizing service quote for aluminum parts", "heat treating service for steel parts"],
    "contract machining": ["CNC machining quote for an aluminum part from a STEP file", "Instant quote for sheet metal or machined parts"],
    "freight": ["Get live parcel shipping rates", "LTL freight quote for a pallet of metal"],
    "cost / pricing": ["Estimate manufacturing cost of a machined part", "Current aluminum price per kg"],
    "CAD/CAM": ["Analyze a STEP CAD file and extract features", "Generate CNC toolpaths or G-code from a CAD model", "Simulate or verify CNC G-code"],
    "shop software": ["Machine shop ERP job scheduling", "Create an invoice for a customer order"],
}


def main():
    out, t0 = {}, time.time()
    for cat, qs in QUERIES.items():
        out[cat] = []
        for q in qs:
            for attempt in range(3):
                try:
                    d = darwin_search(q, max_results=6)
                    break
                except urllib.error.HTTPError as e:
                    d = {"status": f"http_{e.code}", "response": {}, "_elapsed_s": None}
                    time.sleep(2)
            ags = []
            for a in (d.get("response") or {}).get("agents") or []:
                cap = cap_details(a["capabilityId"])
                o = cap.get("owningAi") or {}
                ags.append({"rank": a["rank"], "tool": a["name"], "provider": o.get("name"), "site": o.get("websiteUrl"),
                            "protocols": cap.get("protocols"), "readiness": a.get("readiness"), "canStartThread": a.get("canStartThread"),
                            "threadUnavailableReason": cap.get("threadUnavailableReason"),
                            "payment": ((a.get("executionRequirements") or {}).get("payment") or {}).get("state"),
                            "reasons": a.get("reasons")})
            out[cat].append({"query": q, "status": d.get("status"), "elapsed_s": d.get("_elapsed_s"),
                             "question": (d.get("response") or {}).get("question"),
                             "noMatchReason": (d.get("response") or {}).get("noMatchReason"), "agents": ags})
            print(f"{cat:18s} {d.get('status'):12s} {len(ags)}  {q[:55]:55s} " + " | ".join(f"{x['tool'][:28]} ({(x['provider'] or '')[:22]})" for x in ags[:3]), flush=True)
    total = sum(len(r["agents"]) for v in out.values() for r in v)
    ready = sum(1 for v in out.values() for r in v for a in r["agents"] if a["canStartThread"])
    errors = sum(1 for v in out.values() for r in v if str(r["status"]).startswith("http_"))
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "auth": "key" if os.environ.get("DARWIN_API_KEY") else "anonymous",
           "elapsed_s": round(time.time() - t0, 1), "queries": sum(len(v) for v in QUERIES.values()), "agent_results": total,
           "thread_ready": ready, "http_errors": errors, "results": out}
    p = Path(__file__).resolve().parent / "evidence" / "explore.json"
    p.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "results"}))


if __name__ == "__main__":
    main()
