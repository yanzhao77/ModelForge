from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from .base import ModelProvider, ModelResult, ToolCall


class MockProvider(ModelProvider):
    """Scriptable provider for tests (spec 54: MockLLM).

    Either pass a list of ModelResult script entries (popped in order) or a
    callback fn(messages, tools, call_index) -> ModelResult.
    """

    name = "mock"

    def __init__(
        self,
        script: list[ModelResult] | None = None,
        callback: Callable | None = None,
    ):
        self.script = list(script or [])
        self.callback = callback
        self.calls: list[dict[str, Any]] = []
        self.call_count = 0

    @staticmethod
    def tool_call(name: str, arguments: dict[str, Any], call_id: str | None = None) -> ModelResult:
        return ModelResult(
            content="",
            tool_calls=[ToolCall(id=call_id or f"call_{name}", name=name, arguments=arguments)],
            model="mock",
        )

    @staticmethod
    def final(content: str, usage: dict[str, int] | None = None) -> ModelResult:
        return ModelResult(
            content=content,
            model="mock",
            usage=usage or {"prompt_tokens": 0, "completion_tokens": len(content), "total_tokens": len(content)},
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> ModelResult:
        self.call_count += 1
        self.calls.append({"messages": messages, "tools": tools, "index": self.call_count})
        if self.callback is not None:
            result = self.callback(messages, tools, self.call_count)
            if asyncio.iscoroutine(result) or inspect.isawaitable(result):
                result = await result
            return result
        if self.script:
            return self.script.pop(0)
        return ModelResult(content="", model="mock")

    def __repr__(self) -> str:
        return "<MockProvider calls=" + str(self.call_count) + ">"