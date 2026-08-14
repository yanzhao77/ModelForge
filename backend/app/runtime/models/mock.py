from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional

from .base import ModelProvider, ModelResult, ToolCall


class MockProvider(ModelProvider):
    """Scriptable provider for tests (spec 54: MockLLM).

    Either pass a list of ModelResult script entries (popped in order) or a
    callback fn(messages, tools, call_index) -> ModelResult.
    """

    name = "mock"

    def __init__(
        self,
        script: Optional[List[ModelResult]] = None,
        callback: Optional[Callable] = None,
    ):
        self.script = list(script or [])
        self.callback = callback
        self.calls: List[Dict[str, Any]] = []
        self.call_count = 0

    @staticmethod
    def tool_call(name: str, arguments: Dict[str, Any], call_id: Optional[str] = None) -> ModelResult:
        return ModelResult(
            content="",
            tool_calls=[ToolCall(id=call_id or f"call_{name}", name=name, arguments=arguments)],
            model="mock",
        )

    @staticmethod
    def final(content: str, usage: Optional[Dict[str, int]] = None) -> ModelResult:
        return ModelResult(
            content=content,
            model="mock",
            usage=usage or {"prompt_tokens": 0, "completion_tokens": len(content), "total_tokens": len(content)},
        )

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
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