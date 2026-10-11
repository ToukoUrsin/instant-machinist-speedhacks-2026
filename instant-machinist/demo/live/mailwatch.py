"""Email intake for the live demo: an RFQ forwarded to the agent's address starts a run; the agent replies in the thread
with the verified G-code and the simulation video."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

ADDRESS = "rfq@example.com"
CREDS = Path(os.environ.get("IM_GMAIL_CREDENTIALS", str(Path.home() / ".config/gmail/credentials.json")))  # OAuth token for the RFQ inbox
API = "https://gmail.googleapis.com/gmail/v1/users/me"
_tok = {"v": None, "exp": 0.0}


def token() -> str:
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    c = json.loads(CREDS.read_text())
    body = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    r = json.loads(urllib.request.urlopen(c.get("token_uri", "https://oauth2.googleapis.com/token"), body, timeout=20).read())
    _tok.update(v=r["access_token"], exp=time.time() + r.get("expires_in", 3000))
    return _tok["v"]


def api(path: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def walk(part: dict):
    yield part
    for p in part.get("parts", []) or []:
        yield from walk(p)


def fetch(mid: str) -> tuple[dict, dict]:
    m = api(f"/messages/{mid}?format=full")
    hdr = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
    files = {}
    for p in walk(m["payload"]):
        name = p.get("filename")
        if not name:
            continue
        body = p.get("body", {})
        data = body.get("data") or api(f"/messages/{mid}/attachments/{body['attachmentId']}")["data"]
        files[name] = b64d(data)
    mail = {"id": mid, "threadId": m["threadId"], "subject": hdr.get("subject", ""), "from": hdr.get("from", ""),
            "reply_to": hdr.get("reply-to") or hdr.get("from", ""), "message_id": hdr.get("message-id", ""),
            "files": sorted(files)}
    return mail, files


def query() -> list[str]:
    q = urllib.parse.quote(f"to:{ADDRESS} has:attachment newer_than:1d")
    return [m["id"] for m in api(f"/messages?q={q}&maxResults=20").get("messages", [])]


def watch(start_job, live: Path) -> None:
    seen_f = live / "seen.json"
    seen = set(json.loads(seen_f.read_text())) if seen_f.exists() else set(query())
    seen_f.write_text(json.dumps(sorted(seen)))
    while True:
        try:
            for mid in query():
                if mid in seen:
                    continue
                seen.add(mid)
                seen_f.write_text(json.dumps(sorted(seen)))
                mail, files = fetch(mid)
                try:
                    job = start_job(files, mail)
                    print(f"mail {mid} -> job {job.name}", flush=True)
                except ValueError as e:
                    print(f"mail {mid} skipped: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"watch error: {e!r}", flush=True)
        time.sleep(4)


def mmss(s: float) -> str:
    s = int(round(s))
    h, rem = divmod(s, 3600)
    return f"{h} h {rem // 60} min" if h else f"{rem // 60} min {rem % 60:02d} s"


def reply(job: Path) -> None:
    mail = json.loads((job / "mail.json").read_text())
    run = job / "run"
    s = json.loads((run / "summary.json").read_text())
    best, base = s["best"], s["baseline"]
    questions = []
    for line in (run / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("questions"):
            questions = e["questions"]
            break
    subj = mail["subject"]
    subj = subj if subj.lower().startswith("re:") else "Re: " + subj.removeprefix("Fwd: ").removeprefix("Fw: ")
    lines = [
        "Hi,",
        "",
        f"The CNC program for {s['part']} is done and verified. G-code and the simulation are attached.",
        "",
        f"- Programmed in {mmss(s['programming_s'])}, from your drawing and 3D model",
        f"- Machine time {mmss(best['cycle_s'])} per part, vs {mmss(base['cycle_s'])} for a typical manual program "
        f"({s.get('machining_saved_pct', 0):.0f}% less)",
        f"- Simulated before sending: {best['checks']}",
        f"- {len(s['variants']) - 1} strategies tried in Autodesk Fusion, fastest safe one kept; the editable Fusion file "
        "is saved in Fusion Team",
        "- Scope: OP1, top side (bottom pocket and cross holes are later setups)",
    ]
    if questions:
        lines += ["", "Open questions from the drawing:"] + [f"{i}. {q}" for i, q in enumerate(questions[:4], 1)]
    lines += ["", "AGI Machinist"]
    msg = EmailMessage()
    msg["To"] = mail["reply_to"]
    msg["From"] = f"AGI Machinist <{ADDRESS}>"
    msg["Subject"] = subj
    if mail.get("message_id"):
        msg["In-Reply-To"] = mail["message_id"]
        msg["References"] = mail["message_id"]
    msg.set_content("\n".join(lines))
    nc = Path(best["dir"]) / "1001.nc"
    msg.add_attachment(nc.read_bytes(), maintype="text", subtype="plain", filename="1001.nc")
    if (run / "simulation.mp4").exists():
        msg.add_attachment((run / "simulation.mp4").read_bytes(), maintype="video", subtype="mp4", filename="simulation.mp4")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    api("/messages/send", {"raw": raw, "threadId": mail["threadId"]})
