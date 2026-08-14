"""Legacy adapter: run the 2.1 AGENT_TOOLS functions through the ToolRunner protocol.

AGENT_TOOLS is NOT deleted (spec 67: 禁止一次性删除). Phase 4 replaces this
with the real ToolRegistry + ToolExecutor while keeping these names working.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from services.agent_tools import AGENT_TOOLS

from ..errors import ToolNotFoundError, ToolTimeoutError


LEGACY_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "file_read": {
        "type": "object",
        "properties": {"filepath": {"type": "string", "description": "Path of the file to read"}},
        "required": ["filepath"],
    },
    "code_search": {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Directory to search in"},
            "pattern": {"type": "string", "description": "Text pattern to find"},
        },
        "required": ["directory", "pattern"],
    },
    "command_execute": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout seconds", "default": 30},
        },
        "required": ["command"],
    },
    "web_search": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    },
    "knowledge_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "top_k": {"type": "integer", "description": "Result count", "default": 3},
        },
        "required": ["query"],
    },
}


class LegacyToolRunner:
    """Runs legacy AGENT_TOOLS functions (sync) in a thread pool with timeout."""

    def names(self) -> List[str]:
        return list(AGENT_TOOLS.keys())

    def schema(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in AGENT_TOOLS:
            return None
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": (AGENT_TOOLS[name].__doc__ or name).strip(),
                "parameters": LEGACY_TOOL_SCHEMAS.get(name, {"type": "object", "properties": {}}),
            },
        }

    async def run(
        self,
        name: str,
        arguments: Dict[str, Any],
        ctx: Any = None,
    ) -> str:
        func = AGENT_TOOLS.get(name)
        if func is None:
            raise ToolNotFoundError(name)
        timeout = getattr(ctx, "timeout", None) or 60.0
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(func, **arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ToolTimeoutError(f"Tool {name} timed out after {timeout}s")
        except TypeError as e:
            return f"Error: invalid arguments for {name}: {e}"
        except Exception as e:
            return f"Error: {e}"