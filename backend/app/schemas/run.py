"""Run DTOs (spec 25)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    agent_id: str
    input: str = Field(..., description="Task given to the agent")
    session_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    execute: bool = True


class RunResponse(BaseModel):
    run_id: str
    agent_id: str
    status: str
    session_id: Optional[int] = None
    input: Optional[str] = None
    output: Optional[str] = None
    model: Optional[str] = None
    error: Optional[str] = None
    token_usage: Dict[str, Any] = {}
    tool_call_count: int = 0
    iteration_count: int = 0
    metadata: Dict[str, Any] = {}
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_record(cls, run: Any) -> "RunResponse":
        return cls(**run.to_dict())