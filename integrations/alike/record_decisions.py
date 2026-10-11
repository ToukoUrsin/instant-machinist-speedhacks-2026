"""Record the team's real 2026-10-11 decisions (from ../../DECISIONS.md and sponsors/README.md) in Alike.
Run once; writes evidence/recorded_decisions.json (titles + URNs only)."""
import json
from pathlib import Path
from alike_mcp import Alike

ROOT = "~/work/speedruninstanmachinist"
WORK_ITEM = "urn:alike:task:ee8b63e72435ee2164e6cbe6a7bb4fbe9d72bd2bdf8d14ebc2d0938597683e01"  # "Work on .../speedruninstanmachinist"


def mp(path):
    return {"kind": "machine_path", "label": "governs", "path": f"{ROOT}/{path}"}


WI = {"kind": "entity", "label": "work_item", "ref": WORK_ITEM}

DECISIONS = [
    dict(title="Sponsor code stays isolated in sponsors/; core instant-machinist/ is read-only for sponsor agents",
         outcome="Each sponsor agent writes only sponsors/<sponsor>/ (own README, SEGMENT.md, evidence/); sponsor code only reads core outputs (out/<run>/spec.json, events.jsonl, summary.json). shared sponsors/shop/ is changed only by the orchestrator. Credentials come from environment variables.",
         rationale="the team: 'go all in on all, using sub agents make sure they don't bloat the actual project.' Five sponsor agents run in parallel with the core CAM build thread; this keeps them from colliding with core code or each other.",
         decision_type="standing",
         anchors=[WI, mp("sponsors/"), mp("instant-machinist/")]),
    dict(title="CAM runs through Autodesk Fusion Compute MCP (cloud, headless)",
         outcome="Fusion Compute MCP generates setups, toolpaths and posted NC; own 2.5D CAM + simulator is the second path.",
         rationale="the team: 'I think with Fusion the videos are going to look better.'",
         anchors=[WI, mp("instant-machinist/")]),
    dict(title="Demo part is the NIST FTC-10 housing, not SM-101",
         outcome="Problem deck, product segment and film use the NIST FTC-10 housing; SM-101 numbers removed from the deck.",
         rationale="the team: 'get the cool part in there I don't want the new part.' Supersedes the earlier SM-101 choice.",
         anchors=[WI, mp("demo/"), mp("instant-machinist/")]),
    dict(title="Video sponsor minute = Darwin + Keewano; Dial is repo/backup",
         outcome="Last minute of the 3-min video shows Darwin and Keewano. Extra-award own work: Darwin Search in the material step and the Sparta-tested deposit-invoice agent. Dial drops to repo/backup.",
         rationale="the team picked the two most competitive sponsor segments after all five were checked; Dial was the earlier front-runner.",
         anchors=[WI, mp("sponsors/"), mp("demo/")]),
    dict(title="Demo video structure: 3 min = problem deck, product, sponsors",
         outcome="~1 min problem as a slide deck spoken by the team or Joel (a16z article stats), product segment 1:00-2:00 (drawing in, programming sped up, G-code, simulation video; two time saves: programming ~4 h to minutes and shorter machining time), last minute two sponsors. Don't explain tool choices.",
         rationale="the team: 'I think that's going to look better than a film' (deck), 'the last minute should be dedicated fully to the two sponsors', 'use a16z article as a source in the a16z hackathon'.",
         anchors=[WI, mp("demo/")]),
    dict(title="Repo offers two paths and docs never say 'it doesn't work'",
         outcome="Customer picks: get the Fusion file to edit themselves, or get it done end to end in our own CAD/CAM simulator. README/docs must look good.",
         rationale="the team: 'the customer can pick whether they want to get the Fusion file so they can edit on their own or get it all the way done in our own CAD/CAM simulator.'",
         decision_type="standing",
         anchors=[WI, mp("instant-machinist/")]),
    dict(title="All hackathon compute runs on AWS boxes, never the team's computer",
         outcome="Builds, renders and swarms run on the the build server box or cloud sandboxes (Daytona); headless browsers only.",
         rationale="the team: 'Don't use the team's computer; run on AWS machines.'",
         decision_type="standing",
         anchors=[WI, {"kind": "situation", "label": "applies_when", "text": "launching renders, builds, browsers or agent swarms for Instant Machinist"}]),
]

if __name__ == "__main__":
    a = Alike()
    out = []
    for d in DECISIONS:
        args = {"status": "made", "decision_type": d.pop("decision_type", "one_time"), "decision_date": "2026-10-11", **d}
        r = a.call("record_decision", args)
        out.append({"title": d["title"], "urn": r.get("urn") if isinstance(r, dict) else None,
                    "ok": isinstance(r, dict) and bool(r.get("urn"))})
        print(out[-1])
    Path("evidence/recorded_decisions.json").write_text(json.dumps(out, indent=2) + "\n")
