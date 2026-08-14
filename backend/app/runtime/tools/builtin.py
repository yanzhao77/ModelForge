"""Builtin tools wrapping the 2.1 AGENT_TOOLS functions (spec 8 / 67).

The legacy function dict stays; these Tool objects add schema, permissions,
timeout and retry. Legacy names (file_read, ...) remain as aliases.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from services.agent_tools import (
    tool_code_search, tool_command_execute, tool_file_read,
    tool_knowledge_search, tool_web_search,
)

from .base import PermissionLevel, Tool, ToolResult
from .registry import ToolRegistry


class FunctionTool(Tool):
    """Adapter: a plain sync function becomes a Tool (spec 80 BuiltinToolAdapter)."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Any,
        input_schema: Dict[str, Any],
        permissions: Optional[List[str]] = None,
        timeout: float = 60.0,
        source: str = "builtin",
        aliases: Optional[List[str]] = None,
        retry_count: int = 0,
        retry_delay: float = 1.0,
        retryable_errors: Optional[List[str]] = None,
    ):
        self.name = name
        self.description = description
        self.func = func
        self._input_schema = input_schema
        self.permissions = permissions or [PermissionLevel.READ]
        self.timeout = timeout
        self.source = source
        self.aliases = aliases or []
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.retryable_errors = retryable_errors or []

    def input_schema(self) -> Dict[str, Any]:
        return self._input_schema

    async def execute(
        self,
        arguments: Dict[str, Any],
        context: Any = None,
    ) -> ToolResult:
        try:
            output = await asyncio.to_thread(self.func, **arguments)
        except TypeError as e:
            return ToolResult.err(f"invalid arguments for {self.name}: {e}")
        except Exception as e:
            return ToolResult.err(str(e))
        return ToolResult.ok(str(output))


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register the five 2.1 tools under canonical + legacy names."""
    registry.register(FunctionTool(
        "filesystem.read",
        "Read the contents of a file",
        tool_file_read,
        _schema({"filepath": {"type": "string", "description": "Path of the file to read"}}, ["filepath"]),
        permissions=[PermissionLevel.READ], timeout=10.0,
        aliases=["file_read"],
    ))
    registry.register(FunctionTool(
        "code.search",
        "Search for a text pattern in code files within a directory",
        tool_code_search,
        _schema({
            "directory": {"type": "string", "description": "Directory to search in"},
            "pattern": {"type": "string", "description": "Text pattern to find"},
        }, ["directory", "pattern"]),
        permissions=[PermissionLevel.READ], timeout=30.0,
        aliases=["code_search"],
    ))
    registry.register(FunctionTool(
        "shell.execute",
        "Execute a shell command and return its output",
        tool_command_execute,
        _schema({
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout seconds", "default": 30},
        }, ["command"]),
        permissions=[PermissionLevel.EXECUTE], timeout=60.0,
        aliases=["command_execute"],
    ))
    registry.register(FunctionTool(
        "web.search",
        "Search the web (DuckDuckGo) and return formatted results",
        tool_web_search,
        _schema({"query": {"type": "string", "description": "Search query"}}, ["query"]),
        permissions=[PermissionLevel.NETWORK], timeout=30.0,
        aliases=["web_search"],
    ))
    registry.register(FunctionTool(
        "knowledge.search",
        "Query the knowledge base and return matching chunks",
        tool_knowledge_search,
        _schema({
            "query": {"type": "string", "description": "Search query"},
            "top_k": {"type": "integer", "description": "Result count", "default": 3},
        }, ["query"]),
        permissions=[PermissionLevel.READ], timeout=30.0,
        aliases=["knowledge_search"],
    ))
    return registry