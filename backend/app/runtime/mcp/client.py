from __future__ import annotations

import uuid
from typing import Any

import httpx


class MCPClient:
    """JSON-RPC 2.0 client for an MCP server (spec 36).

    Phase 1 uses HTTP transport; the registry / adapter layers keep the
    transport swappable (stdio / SSE later).
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        name: str,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.name = name
        self.endpoint = endpoint
        self.headers = headers or {}
        self.timeout = timeout
        self.server_info: dict[str, Any] = {}
        self.tools: list[dict[str, Any]] = []
        self._transport: Any = None

    def with_transport(self, transport: Any) -> MCPClient:
        """Inject an httpx transport (tests / custom transports)."""
        self._transport = transport
        return self

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method}
        if params is not None:
            payload["params"] = params
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.headers, transport=self._transport,
        ) as client:
            resp = await client.post(self.endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "MCP RPC error"))
        return data.get("result") or {}

    async def initialize(self) -> dict[str, Any]:
        result = await self._rpc("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "modelforge", "version": "3.0"},
        })
        self.server_info = result.get("serverInfo") or {}
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list")
        self.tools = result.get("tools") or []
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        texts = [
            c.get("text", "")
            for c in (result.get("content") or [])
            if c.get("type") == "text"
        ]
        return "\n".join(texts) or "(no output)"