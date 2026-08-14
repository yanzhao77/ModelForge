"""MCP support (spec 36 / 70): MCPRegistry + MCPClient + MCPToolAdapter.

MCP tools land in the unified Tool Registry; agents do not distinguish
builtin / plugin / MCP tools.
"""

from .client import MCPClient
from .registry import MCPRegistry
from .adapter import MCPToolAdapter

__all__ = ["MCPClient", "MCPRegistry", "MCPToolAdapter"]