from __future__ import annotations

from typing import Any, Dict, Optional

from ..logging import get_logger, log_run


class PluginContext:
    """Per-plugin runtime handle (audit §16.4).

    Gives a plugin scoped access to: tool registration (via its scope),
    event publishing (on the single EventBus, sequenced under
    `plugin:<scope_id>`), and structured logging.
    """

    def __init__(
        self,
        scope: Any,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Any = None,
        logger: Any = None,
    ):
        self.scope = scope
        self.name = name
        self.config = config or {}
        self.event_bus = event_bus
        self._logger = logger or get_logger()
        self._published = 0

    @property
    def scope_id(self) -> str:
        return self.scope.scope_id

    # ---- event publishing (reuse single EventBus, spec 7) ----
    async def publish(self, event_type: str, payload: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None) -> Any:
        if self.event_bus is None:
            return None
        self._published += 1
        return await self.event_bus.publish(
            f"plugin:{self.scope_id}",
            event_type,
            payload=payload or {},
            correlation_id=correlation_id or self.name,
        )

    @property
    def published_count(self) -> int:
        return self._published

    # ---- scoped tool registration ----
    def register_tool(self, tool: Any, aliases: Optional[list] = None) -> Any:
        return self.scope.mount_tool(tool, aliases=aliases)

    # ---- structured logging ----
    def log(self, level: int, message: str, **fields: Any) -> None:
        log_run(self._logger, level, message, agent_id=self.scope_id, **fields)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "scope_id": self.scope_id,
            "config": self.config,
            "published": self._published,
            "tools": sorted(self.scope.tools().keys()),
        }