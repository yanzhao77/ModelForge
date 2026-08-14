from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """A tool invocation requested by the model (OpenAI-compatible shape)."""

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    type: str = "tool_call"

    def to_dict(self) -> Dict[str, Any]:
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
    tool_calls: List[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    raw: Any = None

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("total_tokens") or 0)

    def to_dict(self) -> Dict[str, Any]:
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
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> ModelResult:
        """Complete a chat with optional tool schemas (spec 14)."""
        ...

    def capabilities(self) -> set:
        return {"CHAT"}