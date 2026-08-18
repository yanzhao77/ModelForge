"""Agent DTOs (spec 46)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentCreateRequest(BaseModel):
    name: str
    model: str
    tools: list[str] = []
    plugins: list[str] = []
    memory: dict[str, Any] | None = None
    system_prompt: str | None = None
    description: str | None = None
    policy: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None
    knowledge_config: dict[str, Any] | None = None


class AgentConfigResponse(BaseModel):
    name: str
    model: str
    tools: list[str] = []
    plugins: list[str] = []
    system_prompt: str | None = None
    description: str | None = None
    status: str = "active"
    memory_config: dict[str, Any] = {}
    knowledge_config: dict[str, Any] = {}
    policy: dict[str, Any] = {}
    runtime_config: dict[str, Any] = {}
    created_at: str | None = None

    @classmethod
    def from_config(cls, config: Any, created_at: str | None = None) -> AgentConfigResponse:
        d = config.to_dict() if hasattr(config, "to_dict") else config
        return cls(**d, created_at=created_at)


class AgentRunSpec(BaseModel):
    """What a scheduler / delegate needs to trigger a run (spec 41 / 72)."""
    agent_id: str
    input: str
    session_id: int | None = None
    metadata: dict[str, Any] | None = None