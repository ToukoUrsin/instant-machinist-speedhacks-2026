"""Minimal read client for the Alike MCP server (streamable HTTP, JSON-RPC).

Auth: the OAuth access token Codex stored after `codex mcp login alike`
(~/.codex/.credentials.json). The token is read in-process and never printed or written.

    python3 alike_mcp.py tools                 # list tool names
    python3 alike_mcp.py call NAME '{"k": 1}'  # call one tool, print JSON result
"""
import json
import sys
import urllib.request
from pathlib import Path

URL = "https://alike.network/api-general/mcp"
CREDS = Path.home() / ".codex" / ".credentials.json"


def _token() -> str:
    data = json.loads(CREDS.read_text())
    for key, entry in data.items():
        if key.startswith("alike|") and isinstance(entry, dict) and entry.get("access_token"):
            return entry["access_token"]
    raise SystemExit("no Alike OAuth token in ~/.codex/.credentials.json; run `codex mcp login alike`")


class Alike:
    def __init__(self):
        self.token = _token()
        self.session = None
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "instant-machinist-alike-stats", "version": "0.1"},
        })
        self._rpc("notifications/initialized", None, notify=True)

    def _rpc(self, method, params, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "instant-machinist-alike-stats/0.1",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:
            self.session = resp.headers.get("Mcp-Session-Id") or self.session
            raw = resp.read().decode()
        if notify or not raw.strip():
            return None
        if raw.lstrip().startswith("data:") or "\ndata:" in raw:
            msgs = [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:")]
            msg = next(m for m in msgs if m.get("id") == body.get("id"))
        else:
            msg = json.loads(raw)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    def tools(self):
        return self._rpc("tools/list", {})["tools"]

    def call(self, name, args=None):
        res = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except ValueError:
            return joined


if __name__ == "__main__":
    a = Alike()
    if sys.argv[1] == "tools":
        for t in a.tools():
            print(t["name"])
    elif sys.argv[1] == "schema":
        for t in a.tools():
            if t["name"] == sys.argv[2]:
                print(json.dumps(t, indent=2))
    elif sys.argv[1] == "call":
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(a.call(sys.argv[2], args), indent=2, default=str))
