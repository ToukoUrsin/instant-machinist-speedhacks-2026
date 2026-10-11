"""Minimal Keewano MCP client (Streamable HTTP, JSON-RPC). Token from env KEEWANO_PAT (injected by the environment)."""
import json, os, urllib.request

URL = "https://api.keewano.com/mcp"


class KeewanoMCP:
    def __init__(self, token=None):
        self.token = token or os.environ["KEEWANO_PAT"]
        self.sid = None
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "instant-machinist-shop-brain", "version": "1.0"}})
        self._rpc("notifications/initialized", None, notify=True)

    def _rpc(self, method, params, notify=False, timeout=180):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        h = {"k-token": self.token, "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            self.sid = r.headers.get("mcp-session-id") or self.sid
            raw = r.read().decode()
        if notify or not raw.strip():
            return None
        if raw.lstrip().startswith("{"):
            msg = json.loads(raw)
        else:  # SSE: take the last data: line carrying our id
            msg = None
            for line in raw.splitlines():
                if line.startswith("data:"):
                    d = json.loads(line[5:])
                    if d.get("id") == body.get("id"):
                        msg = d
        if msg is None:
            raise RuntimeError("no MCP response")
        if "error" in msg:
            raise RuntimeError(f"MCP error: {msg['error']}")
        return msg["result"]

    def tools(self):
        return self._rpc("tools/list", {})["tools"]

    def call(self, name, args):
        res = self._rpc("tools/call", {"name": name, "arguments": args})
        parts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        return "\n".join(parts), bool(res.get("isError"))


if __name__ == "__main__":
    m = KeewanoMCP()
    for t in m.tools():
        print("##", t["name"], "\n", t.get("description", "")[:1500], "\n", json.dumps(t.get("inputSchema", {}))[:800])
