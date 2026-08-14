from __future__ import annotations

from typing import Any, Dict, List, Optional

from .adapter import MCPToolAdapter


class MCPRegistry:
    """Registry of connected MCP servers (spec 36).

    Each server exposes tools; sync_tools() registers them into the unified
    ToolRegistry so agents can use them like any builtin tool.
    """

    def __init__(self):
        self._servers: Dict[str, Any] = {}

    def register(self, client: Any) -> Any:
        self._servers[client.name] = client
        return client

    def unregister(self, name: str) -> bool:
        return self._servers.pop(name, None) is not None

    def get(self, name: str) -> Optional[Any]:
        return self._servers.get(name)

    def list(self) -> List[Dict[str, Any]]:
        out = []
        for s in self._servers.values():
            entry = {"name": s.name, "endpoint": s.endpoint, "server_info": s.server_info}
            if getattr(s, "tools", None):
                entry["tools"] = [t.get("name") for t in s.tools]
            out.append(entry)
        return out

    def names(self) -> List[str]:
        return list(self._servers.keys())

    def sync_tools(self, tool_registry: Any) -> int:
        """Register adapters for every tool of every server (idempotent)."""
        count = 0
        for server in self._servers.values():
            for tool_def in getattr(server, "tools", []) or []:
                tool_registry.register(MCPToolAdapter(server.name, tool_def, server))
                count += 1
        return count