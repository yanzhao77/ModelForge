from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from ..errors import ToolNotFoundError, ToolTimeoutError
from .base import Tool, ToolResult
from .registry import ToolRegistry


class ToolExecutor:
    """Executes tools with timeout + retry (spec 11 / 12) and satisfies the
    runner protocol used by the ExecutionEngine (names/schema/run).
    """

    def __init__(self, registry: ToolRegistry, default_timeout: float = 60.0):
        self.registry = registry
        self.default_timeout = default_timeout

    def names(self) -> List[str]:
        return self.registry.names()

    def schema(self, name: str) -> Optional[Dict[str, Any]]:
        return self.registry.schema(name)

    async def run(
        self,
        name: str,
        arguments: Dict[str, Any],
        ctx: Any = None,
    ) -> str:
        """Run one tool call; returns a text result for the LLM loop."""
        tool = self.registry.get(name)
        if tool is None:
            raise ToolNotFoundError(name)
        timeout = tool.timeout or getattr(ctx, "timeout", None) or self.default_timeout
        attempts = tool.retry_count + 1
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    tool.execute(arguments, ctx),
                    timeout=timeout,
                )
                if isinstance(result, ToolResult):
                    return result.to_text()
                return str(result)
            except asyncio.TimeoutError:
                if attempt < tool.retry_count:
                    await asyncio.sleep(tool.retry_delay)
                    continue
                raise ToolTimeoutError(f"Tool {name} timed out after {timeout}s")
            except ToolTimeoutError:
                raise
            except Exception as e:
                last_exc = e
                if attempt < tool.retry_count and self._retryable(tool, e):
                    await asyncio.sleep(tool.retry_delay)
                    continue
                return f"Error: {e}"
        return f"Error: {last_exc}" if last_exc else f"Error: tool {name} failed"

    @staticmethod
    def _retryable(tool: Tool, exc: Exception) -> bool:
        if not tool.retryable_errors:
            return False
        if "*" in tool.retryable_errors:
            return True
        msg = str(exc)
        return any(err in msg for err in tool.retryable_errors)