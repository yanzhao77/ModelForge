from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..logging import get_logger, log_run


class PluginScope:
    """A named scope owning plugin-registered resources (audit §13.3 / §16).

    Tools mounted under a scope are registered into the shared ToolRegistry
    (single registry per spec) but ownership is tracked here so unmount() can
    cleanly remove exactly the plugin contribution.
    """

    def __init__(
        self,
        scope_id: str,
        name: Optional[str] = None,
        tool_registry: Any = None,
        event_bus: Any = None,
        logger: Any = None,
    ):
        self.scope_id = scope_id
        self.name = name or scope_id
        self._tool_registry = tool_registry
        self._event_bus = event_bus
        self._logger = logger or get_logger()
        self._owned_tools: Dict[str, Any] = {}
        self._mounted = False

    # ---- tool ownership ----
    def mount_tool(self, tool: Any, aliases: Optional[List[str]] = None) -> Any:
        if self._tool_registry is None:
            raise RuntimeError("scope has no tool registry")
        self._tool_registry.register(tool, aliases=aliases)
        names = [tool.name] + list(aliases or []) + list(getattr(tool, "aliases", []) or [])
        for n in names:
            self._owned_tools[n] = tool
        self._mounted = True
        return tool

    def tools(self) -> Dict[str, Any]:
        return dict(self._owned_tools)

    def unmount(self) -> None:
        """Unregister every tool owned by this scope (scoped cleanup)."""
        for name in list(self._owned_tools):
            if self._tool_registry is not None:
                self._tool_registry.unregister(name)
        self._owned_tools.clear()
        self._mounted = False

    @property
    def mounted(self) -> bool:
        return self._mounted

    def context(self, plugin_name: str, config: Optional[Dict[str, Any]] = None) -> "PluginContext":
        from .context import PluginContext
        return PluginContext(
            scope=self,
            name=plugin_name,
            config=config or {},
            event_bus=self._event_bus,
            logger=self._logger,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "name": self.name,
            "mounted": self._mounted,
            "tools": sorted(self._owned_tools.keys()),
        }