from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool invocation requested by the model (OpenAI-compatible shape)."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    type: str = "tool_call"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "type": self.type,
        }


@dataclass
class ModelResult:
    """A single model completion (spec 14)."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("total_tokens") or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "model": self.model,
            "usage": self.usage,
        }


class ModelProvider(ABC):
    """Unified provider interface; business code never touches concrete providers."""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> ModelResult:
        """Complete a chat with optional tool schemas (spec 14)."""
        ...

    def capabilities(self) -> set:
        return {"CHAT"}