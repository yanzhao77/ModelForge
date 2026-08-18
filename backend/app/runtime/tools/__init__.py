"""Tool Registry (spec 8). Builtin + Plugin + MCP tools behind one protocol."""

from .base import PermissionLevel, Tool, ToolResult
from .executor import ToolExecutor
from .registry import ToolRegistry

__all__ = ["PermissionLevel", "Tool", "ToolExecutor", "ToolRegistry", "ToolResult"]