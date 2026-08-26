from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cancellation import CancellationToken


@dataclass
class RunContext:
    """Execution context for one Agent Run (spec Phase 1: ExecutionContext).

    Carries identity, limits, policy and shared cancellation so the
    ExecutionEngine and every Tool/Provider stay decoupled from each other.
    """

    run_id: str
    agent_id: str
    user_id: int | None = None
    session_id: int | None = None
    input_text: str = ""
    model: str | None = None
    system_prompt: str | None = None
    tools: list[str] = field(default_factory=list)
    policy: Any | None = None
    approval_waiter: Any | None = None
    cancellation: CancellationToken | None = None
    max_iterations: int = 20
    max_tool_calls: int = 50
    timeout_seconds: int = 600
    max_context_tokens: int = 8192
    max_output_tokens: int = 2048
    tool_timeout: float = 60.0
    delegation_max_depth: int = 3
    delegation_max_children: int = 5
    memory_config: dict[str, Any] | None = None
    knowledge_sources: list[str] = field(default_factory=list)
    knowledge_binding: dict[str, Any] | None = None
    contributions: list[dict[str, Any]] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0

    def elapsed(self) -> float:
        import time
        if not self.started_at:
            return 0.0
        return time.monotonic() - self.started_at

    def check_timeout(self) -> None:
        if self.timeout_seconds and self.elapsed() > self.timeout_seconds:
            from .errors import RunTimeoutError
            raise RunTimeoutError()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "input": self.input_text,
            "model": self.model,
            "tools": self.tools,
            "knowledge_binding": self.knowledge_binding or {},
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }


@dataclass
class ToolExecutionContext:
    """Per-tool-call execution context (spec 9)."""

    user_id: int | None = None
    agent_id: str = ""
    run_id: str = ""
    session_id: int | None = None
    permissions: list[str] = field(default_factory=list)
    timeout: float = 60.0
    policy: Any | None = None
    cancellation_token: CancellationToken | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def check_cancelled(self) -> None:
        if self.cancellation_token is not None:
            self.cancellation_token.check()
