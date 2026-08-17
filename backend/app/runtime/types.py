from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RunStatus(str, Enum):
    """Persisted run lifecycle states (spec 4)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    WAITING_HUMAN = "WAITING_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"

    @classmethod
    def terminal(cls):
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED, cls.TIMEOUT}


@dataclass
class RunRecord:
    """Framework-agnostic persisted Run entity (spec 4 / 28).

    Handed to a RunStore adapter (SQLAlchemy) for persistence.
    """

    run_id: str
    agent_id: str
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    parent_run_id: Optional[str] = None
    status: str = RunStatus.PENDING.value
    input: Optional[str] = None
    output: Optional[str] = None
    model: Optional[str] = None
    error: Optional[str] = None
    token_usage: Dict[str, Any] = field(default_factory=dict)
    tool_call_count: int = 0
    iteration_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "parent_run_id": self.parent_run_id,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "model": self.model,
            "error": self.error,
            "token_usage": self.token_usage or {},
            "tool_call_count": self.tool_call_count,
            "iteration_count": self.iteration_count,
            "metadata": self.metadata or {},
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunRecord":
        def _dt(v):
            if isinstance(v, datetime.datetime):
                return v
            if isinstance(v, str) and v:
                try:
                    return datetime.datetime.fromisoformat(v)
                except ValueError:
                    return None
            return None
        return cls(
            run_id=data["run_id"],
            agent_id=data["agent_id"],
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            parent_run_id=data.get("parent_run_id"),
            status=data.get("status", RunStatus.PENDING.value),
            input=data.get("input"),
            output=data.get("output"),
            model=data.get("model"),
            error=data.get("error"),
            token_usage=data.get("token_usage") or {},
            tool_call_count=data.get("tool_call_count", 0),
            iteration_count=data.get("iteration_count", 0),
            metadata=data.get("metadata") or {},
            started_at=_dt(data.get("started_at")),
            finished_at=_dt(data.get("finished_at")),
            created_at=_dt(data.get("created_at")),
        )


@dataclass
class AgentConfig:
    """Persistable agent definition (spec 3.1). Resolved from the agent store."""

    name: str
    model: str
    user_id: Optional[int] = None
    tools: List[str] = field(default_factory=list)
    plugins: List[str] = field(default_factory=list)
    system_prompt: Optional[str] = None
    description: Optional[str] = None
    memory_config: Optional[Dict[str, Any]] = None
    knowledge_config: Optional[Dict[str, Any]] = None
    policy: Optional[Dict[str, Any]] = None
    runtime_config: Optional[Dict[str, Any]] = None
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "user_id": self.user_id,
            "tools": self.tools,
            "plugins": self.plugins,
            "system_prompt": self.system_prompt,
            "description": self.description,
            "memory_config": self.memory_config or {},
            "knowledge_config": self.knowledge_config or {},
            "policy": self.policy or {},
            "runtime_config": self.runtime_config or {},
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        return cls(
            name=data["name"],
            model=data.get("model", ""),
            user_id=data.get("user_id"),
            tools=data.get("tools") or [],
            plugins=data.get("plugins") or [],
            system_prompt=data.get("system_prompt"),
            description=data.get("description"),
            memory_config=data.get("memory_config"),
            knowledge_config=data.get("knowledge_config"),
            policy=data.get("policy"),
            runtime_config=data.get("runtime_config"),
            status=data.get("status", "active"),
        )