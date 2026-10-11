"""Minimal Dial REST client (https://api.getdial.ai/api/v1). Key comes from env DIAL_API_KEY (inject via the environment)."""
import os, time, requests

API = os.environ.get("DIAL_API_URL", "https://api.getdial.ai") + "/api/v1"


class DialError(RuntimeError):
    def __init__(self, status, body):
        super().__init__(f"Dial {status}: {body}")
        self.status, self.body = status, body


def _h():
    return {"Authorization": f"Bearer {os.environ['DIAL_API_KEY']}", "Content-Type": "application/json",
            "User-Agent": "instant-machinist/0.1"}


def req(method, path, body=None, params=None, timeout=60):
    r = requests.request(method, API + path, json=body, params=params, headers=_h(), timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:500]}
    if r.status_code >= 400:
        raise DialError(r.status_code, data)
    return data


def account():
    return req("GET", "/account")


def billing():
    return req("GET", "/billing")


def numbers():
    d = req("GET", "/numbers")
    return d.get("numbers", d.get("data", [])) if isinstance(d, dict) else d


def number_by_nickname(nick):
    for n in numbers():
        if n.get("nickname") == nick:
            return n
    return None


def provision(nickname, inbound_instruction, consent, area_code=None, voice="female"):
    body = {"explicitProgrammaticConsent": consent, "inboundInstruction": inbound_instruction,
            "inboundVoiceGender": voice, "inboundLanguage": "en-US"}
    if area_code:
        body["areaCode"] = area_code
    n = req("POST", "/numbers", body)
    n = n["number"] if isinstance(n.get("number"), dict) else n
    req("PATCH", f"/numbers/{n['id']}", {"nickname": nickname})
    return n


def update_number(num_id, **fields):
    return req("PATCH", f"/numbers/{num_id}", fields)


def make_call(to, from_number_id, instruction, max_s=300, voice="male"):
    """NOT idempotent: never retry blindly. Caller must check list_calls before any retry."""
    body = {"to": to, "fromNumberId": from_number_id, "outboundInstruction": instruction,
            "language": "en-US", "maxCallDurationSeconds": max_s, "voiceGender": voice}
    d = req("POST", "/calls", body, timeout=90)
    return d.get("call", d)


def get_call(call_id):
    d = req("GET", f"/calls/{call_id}")
    return d.get("call", d)


def list_calls(**params):
    d = req("GET", "/calls", params=params)
    return d.get("calls", d.get("data", [])) if isinstance(d, dict) else d


def wait_call(call_id, timeout_s=480, poll_s=4, on_state=None):
    """Poll until the call is Terminated and its transcript is present (or timeout)."""
    t0, last, ended_at = time.time(), None, None
    while time.time() - t0 < timeout_s:
        c = get_call(call_id)
        st = (c.get("status") or {}).get("state")
        if st != last:
            last = st
            if on_state:
                on_state(st, c)
        if st == "Terminated":
            ended_at = ended_at or time.time()
            if c.get("transcriptTurns") or c.get("transcript") or time.time() - ended_at > 60:
                return c
        time.sleep(poll_s)
    return get_call(call_id)


def download_recording(call_id, path_base):
    """Dial serves the call audio via a 302 to signed storage (WAV). Saves MP3 if ffmpeg exists, else WAV."""
    import subprocess, shutil
    r = requests.get(f"{API}/calls/{call_id}/recording", headers=_h(), timeout=30, allow_redirects=False)
    if r.status_code not in (301, 302, 303, 307) or "location" not in r.headers:
        return None
    a = requests.get(r.headers["location"], timeout=180)
    a.raise_for_status()
    wav = f"{path_base}.wav"
    open(wav, "wb").write(a.content)
    if shutil.which("ffmpeg"):
        mp3 = f"{path_base}.mp3"
        subprocess.run(["nice", "ffmpeg", "-v", "error", "-y", "-i", wav, "-ac", "1", "-b:a", "64k", mp3], check=True)
        os.remove(wav)
        return mp3
    return wav
