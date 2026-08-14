from __future__ import annotations

from typing import Any, Dict

from ..tools.base import PermissionLevel, Tool, ToolResult


class MCPToolAdapter(Tool):
    """Exposes an MCP server tool through the unified Tool protocol (spec 36 / 80)."""

    def __init__(
        self,
        server_name: str,
        tool_def: Dict[str, Any],
        client: Any,
        timeout: float = 30.0,
    ):
        self.name = tool_def.get("name", "mcp_tool")
        self.description = tool_def.get("description", f"MCP tool from {server_name}")
        self.version = "1.0.0"
        self.timeout = timeout
        self.source = "mcp"
        self.permissions = [PermissionLevel.NETWORK]
        self.metadata = {"server": server_name}
        self._input_schema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}
        self._client = client
        self.aliases = []

    def input_schema(self) -> Dict[str, Any]:
        return self._input_schema

    async def execute(self, arguments: Dict[str, Any], context: Any = None) -> ToolResult:
        try:
            output = await self._client.call_tool(self.name, arguments)
        except Exception as e:
            return ToolResult.err(f"MCP tool {self.name} failed: {e}")
        return ToolResult.ok(output, server=self.metadata.get("server"))