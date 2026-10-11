"""Fusion Compute session helpers: run TypeScript in a cloud Fusion instance."""
from __future__ import annotations

import json
import time

from .mcp_client import FusionError, FusionMCP


class FusionSession:
    def __init__(self, session_id: str = "im-1", mcp: FusionMCP | None = None) -> None:
        self.mcp = mcp or FusionMCP()
        self.sid = session_id

    def start(self) -> str:
        out = self.mcp.call("start_fusion", {"engine_session_id": self.sid})
        for _ in range(60):
            st = self.mcp.call("fusion_status", {"engine_session_id": self.sid})
            if '"status": "active"' in st.lower().replace('"status":"active"', '"status": "active"'):
                break
            time.sleep(5)
        return out

    def stop(self) -> str:
        return self.mcp.call("stop_fusion", {"engine_session_id": self.sid})

    def invoke(self, tool: str, arguments: dict, timeout: float = 600) -> str:
        return self.mcp.call("invoke_fusion", {"engine_session_id": self.sid, "tool": tool, "arguments": arguments}, timeout)

    def ts(self, code: str, timeout: float = 600, retries: int = 3) -> dict:
        """Run TypeScript in Fusion. The script sets `adsk.result = JSON.stringify(...)`.
        Long calls sometimes lose the HTTP stream while Fusion keeps working; our scripts are safe to re-run."""
        import requests
        for attempt in range(retries + 1):
            try:
                raw = self.invoke("MCP.ExecuteTypeScript", {"code": code}, timeout)
                break
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError):
                if attempt == retries:
                    raise
                time.sleep(5)
        try:
            res = json.loads(raw)
        except json.JSONDecodeError:
            raise FusionError(raw[:2000])
        if not res.get("ok", True) or res.get("error"):
            raise FusionError(json.dumps(res.get("error") or res)[:3000] + "\nlogs: " + str(res.get("logs"))[:2000])
        txt = res.get("resultText") or ""
        try:
            return json.loads(txt) if txt else {}
        except json.JSONDecodeError:
            return {"text": txt}
