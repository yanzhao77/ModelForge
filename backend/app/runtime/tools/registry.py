from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import Tool


class ToolRegistry:
    """Central registry for Builtin / Plugin / MCP / Remote tools (spec 8 / 36).

    Agents see a unified Tool namespace: a tool can be registered under
    multiple alias names (legacy names keep working, spec 67).
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, tool: Tool, aliases: Optional[List[str]] = None) -> None:
        self._tools[tool.name] = tool
        for alias in (aliases or []) + list(getattr(tool, "aliases", []) or []):
            self._aliases[alias] = tool.name

    def unregister(self, name: str) -> bool:
        canonical = self._aliases.pop(name, name)
        removed = self._tools.pop(canonical, None) is not None
        self._aliases = {k: v for k, v in self._aliases.items() if v != canonical}
        return removed

    def get(self, name: str) -> Optional[Tool]:
        canonical = self._aliases.get(name, name)
        return self._tools.get(canonical)

    def canonical(self, name: str) -> str:
        return self._aliases.get(name, name)

    def names(self) -> List[str]:
        return sorted(self._tools.keys())

    def all_names(self) -> List[str]:
        return sorted(set(self._tools.keys()) | set(self._aliases.keys()))

    def list(self) -> List[Tool]:
        return list(self._tools.values())

    def schema(self, name: str) -> Optional[Dict[str, Any]]:
        tool = self.get(name)
        return tool.schema() if tool is not None else None

    def schemas(self, names: List[str]) -> List[Dict[str, Any]]:
        out = []
        for name in names:
            s = self.schema(name)
            if s:
                out.append(s)
        return out

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None