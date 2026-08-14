from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .cancellation import CancellationToken


@dataclass
class RunContext:
    """Execution context for one Agent Run (spec Phase 1: ExecutionContext).

    Carries identity, limits, policy and shared cancellation so the
    ExecutionEngine and every Tool/Provider stay decoupled from each other.
    """

    run_id: str
    agent_id: str
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    input_text: str = ""
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    policy: Optional[Any] = None
    cancellation: Optional[CancellationToken] = None
    max_iterations: int = 20
    max_tool_calls: int = 50
    timeout_seconds: int = 600
    max_context_tokens: int = 8192
    max_output_tokens: int = 2048
    tool_timeout: float = 60.0
    memory_config: Optional[Dict[str, Any]] = None
    knowledge_sources: List[str] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "input": self.input_text,
            "model": self.model,
            "tools": self.tools,
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }


@dataclass
class ToolExecutionContext:
    """Per-tool-call execution context (spec 9)."""

    user_id: Optional[int] = None
    agent_id: str = ""
    run_id: str = ""
    session_id: Optional[int] = None
    permissions: List[str] = field(default_factory=list)
    timeout: float = 60.0
    cancellation_token: Optional[CancellationToken] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def check_cancelled(self) -> None:
        if self.cancellation_token is not None:
            self.cancellation_token.check()