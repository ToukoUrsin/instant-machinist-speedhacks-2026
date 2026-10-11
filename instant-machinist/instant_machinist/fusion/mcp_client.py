"""Minimal Streamable-HTTP MCP client for Autodesk Fusion Compute MCP (cloud, headless Fusion)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

ENDPOINT = "https://developer.api.autodesk.com/da/v3/mcp/fusion"
TOKEN_URL = "https://developer.api.autodesk.com/mcpauth/v1/token"
CLIENT_ID = "https://claude.ai/oauth/claude-code-client-metadata"
TOKEN_PATH = Path(os.environ.get("IM_FUSION_TOKEN", Path.home() / ".adsk" / "token.json"))


class FusionError(RuntimeError):
    """Raised when a Fusion MCP call fails or returns an error."""
    pass


def _load_token() -> dict:
    tok = json.loads(TOKEN_PATH.read_text())
    if time.time() > tok["obtained"] + tok["expires_in"] - 120:
        r = requests.post(TOKEN_URL, data=dict(grant_type="refresh_token", refresh_token=tok["refresh_token"],
                                                client_id=CLIENT_ID, resource=ENDPOINT), timeout=30)
        r.raise_for_status()
        tok = {**tok, **r.json(), "obtained": time.time()}
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, json.dumps(tok).encode())
        os.close(fd)
    return tok


class FusionMCP:
    """JSON-RPC client for the Autodesk Fusion Compute MCP endpoint."""
    def __init__(self) -> None:
        self.session_id: str | None = None
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "instant-machinist", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, msg: dict, timeout: float = 600) -> dict | None:
        h = {"Authorization": f"Bearer {_load_token()['access_token']}", "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        if self.session_id:
            h["mcp-session-id"] = self.session_id
        r = requests.post(ENDPOINT, json=msg, headers=h, timeout=timeout)
        if r.status_code >= 400:
            raise FusionError(f"HTTP {r.status_code}: {r.text[:500]}")
        self.session_id = r.headers.get("mcp-session-id", self.session_id)
        if "id" not in msg:
            return None
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    d = json.loads(line[5:])
                    if d.get("id") == msg["id"]:
                        return d
            raise FusionError("no response in SSE stream")
        return r.json()

    def _rpc(self, method: str, params: dict, timeout: float = 600) -> dict:
        self._id += 1
        d = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}, timeout)
        if "error" in d:
            raise FusionError(json.dumps(d["error"]))
        return d["result"]

    def tools(self) -> list[dict]:
        """List the MCP server's tools."""
        return self._rpc("tools/list", {})["tools"]

    def call(self, name: str, args: dict | None = None, timeout: float = 600) -> str:
        """Call MCP tool ``name`` and return its text content; raise FusionError on error."""
        res = self._rpc("tools/call", {"name": name, "arguments": args or {}}, timeout)
        text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise FusionError(text)
        return text
