"""Tool Registry (spec 8). Builtin + Plugin + MCP tools behind one protocol."""

from .base import PermissionLevel, Tool, ToolResult
from .registry import ToolRegistry
from .executor import ToolExecutor

__all__ = ["PermissionLevel", "Tool", "ToolResult", "ToolRegistry", "ToolExecutor"]