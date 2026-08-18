from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    """Framework-agnostic agent execution state (spec 22).

    Deliberately decoupled from ORM models and LangChain message objects:
    messages are plain {"role", "content", ...} dicts.
    """

    run_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_count: int = 0
    variables: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    status: str = "PENDING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "messages": self.messages,
            "context": self.context,
            "tool_calls": self.tool_calls,
            "tool_call_count": self.tool_call_count,
            "variables": self.variables,
            "metadata": self.metadata,
            "iteration": self.iteration,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentState:
        return cls(
            run_id=data.get("run_id", ""),
            messages=data.get("messages", []),
            context=data.get("context", {}),
            tool_calls=data.get("tool_calls", []),
            tool_call_count=data.get("tool_call_count", 0),
            variables=data.get("variables", {}),
            metadata=data.get("metadata", {}),
            iteration=data.get("iteration", 0),
            status=data.get("status", "PENDING"),
        )