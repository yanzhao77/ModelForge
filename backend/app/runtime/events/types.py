from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


class EventType:
    """Canonical agent event types (spec 6)."""

    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_TIMEOUT = "run.timeout"
    MODEL_REQUEST_STARTED = "model.request.started"
    MODEL_REQUEST_COMPLETED = "model.request.completed"
    MODEL_REQUEST_FAILED = "model.request.failed"
    AGENT_MESSAGE = "agent.message"
    AGENT_RESPONSE = "agent.response"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    KNOWLEDGE_SEARCH_STARTED = "knowledge.search.started"
    KNOWLEDGE_SEARCH_COMPLETED = "knowledge.search.completed"
    HUMAN_APPROVAL_REQUIRED = "human.approval.required"
    HUMAN_APPROVAL_GRANTED = "human.approval.granted"
    HUMAN_APPROVAL_DENIED = "human.approval.denied"
    RUNTIME_ERROR = "runtime.error"
    RUNTIME_WARNING = "runtime.warning"

    ALL = (
        RUN_CREATED, RUN_STARTED, RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED, RUN_TIMEOUT,
        MODEL_REQUEST_STARTED, MODEL_REQUEST_COMPLETED, MODEL_REQUEST_FAILED,
        AGENT_MESSAGE, AGENT_RESPONSE,
        TOOL_CALL_STARTED, TOOL_CALL_COMPLETED, TOOL_CALL_FAILED,
        MEMORY_READ, MEMORY_WRITE,
        KNOWLEDGE_SEARCH_STARTED, KNOWLEDGE_SEARCH_COMPLETED,
        HUMAN_APPROVAL_REQUIRED, HUMAN_APPROVAL_GRANTED, HUMAN_APPROVAL_DENIED,
        RUNTIME_ERROR, RUNTIME_WARNING,
    )


@dataclass
class AgentEvent:
    """One fact in a run lifecycle (spec 6). sequence is per-run and strictly increasing."""

    id: str
    run_id: str
    event_type: str
    sequence: int
    timestamp: datetime.datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: int | None = None
    correlation_id: str | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "payload": self.payload,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
        }