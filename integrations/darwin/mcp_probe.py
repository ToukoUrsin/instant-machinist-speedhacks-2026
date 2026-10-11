"""Minimal read-only MCP (streamable HTTP) client: initialize, tools/list, one tools/call.
Used only for read-only operations (search/list). Never calls quote/order tools."""
import json, sys, urllib.request, urllib.error

UA = "instant-machinist-darwin/0.1 (+hackathon read-only probe)"


class MCP:
    def __init__(self, url, timeout=40):
        self.url, self.timeout, self.sid, self.n = url, timeout, None, 0

    def _post(self, payload, notify=False):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "User-Agent": UA, "MCP-Protocol-Version": "2025-06-18"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=h)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self.sid = r.headers.get("Mcp-Session-Id") or self.sid
            body = r.read().decode("utf-8", "replace")
            if notify or not body.strip():
                return None
            if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                msgs = [json.loads(l[5:]) for l in body.splitlines() if l.startswith("data:") and l[5:].strip()]
                msgs = [m for m in msgs if m.get("id") == payload.get("id")] or msgs
                return msgs[-1] if msgs else None
            return json.loads(body)

    def rpc(self, method, params=None):
        self.n += 1
        out = self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        if out and "error" in out:
            raise RuntimeError(f"{method}: {out['error']}")
        return (out or {}).get("result")

    def initialize(self):
        res = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "instant-machinist-darwin", "version": "0.1"}})
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)
        except urllib.error.HTTPError:
            pass
        return res

    def tools(self):
        return (self.rpc("tools/list") or {}).get("tools", [])

    def call(self, name, args):
        return self.rpc("tools/call", {"name": name, "arguments": args})


if __name__ == "__main__":
    m = MCP(sys.argv[1])
    info = m.initialize()
    print(json.dumps((info or {}).get("serverInfo")))
    for t in m.tools():
        print("-", t["name"], "|", (t.get("description") or "")[:110].replace("\n", " "), "|", list((t.get("inputSchema") or {}).get("properties", {}))[:8],
              "| ro" if (t.get("annotations") or {}).get("readOnlyHint") else "")
