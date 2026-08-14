"""Agent DTOs (spec 46)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AgentCreateRequest(BaseModel):
    name: str
    model: str
    tools: List[str] = []
    memory: Optional[Dict[str, Any]] = None
    system_prompt: Optional[str] = None
    description: Optional[str] = None
    policy: Optional[Dict[str, Any]] = None
    runtime_config: Optional[Dict[str, Any]] = None
    knowledge_config: Optional[Dict[str, Any]] = None


class AgentConfigResponse(BaseModel):
    name: str
    model: str
    tools: List[str] = []
    system_prompt: Optional[str] = None
    description: Optional[str] = None
    status: str = "active"
    memory_config: Dict[str, Any] = {}
    knowledge_config: Dict[str, Any] = {}
    policy: Dict[str, Any] = {}
    runtime_config: Dict[str, Any] = {}
    created_at: Optional[str] = None

    @classmethod
    def from_config(cls, config: Any, created_at: Optional[str] = None) -> "AgentConfigResponse":
        d = config.to_dict() if hasattr(config, "to_dict") else config
        return cls(**d, created_at=created_at)


class AgentRunSpec(BaseModel):
    """What a scheduler / delegate needs to trigger a run (spec 41 / 72)."""
    agent_id: str
    input: str
    session_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None