"""Run DTOs (spec 25)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    agent_id: str
    input: str = Field(..., description="Task given to the agent")
    session_id: int | None = None
    metadata: dict[str, Any] | None = None
    execute: bool = False
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


class RunResponse(BaseModel):
    run_id: str
    agent_id: str
    status: str
    session_id: int | None = None
    input: str | None = None
    output: str | None = None
    model: str | None = None
    error: str | None = None
    token_usage: dict[str, Any] = {}
    tool_call_count: int = 0
    iteration_count: int = 0
    metadata: dict[str, Any] = {}
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None

    @classmethod
    def from_record(cls, run: Any) -> RunResponse:
        return cls(**run.to_dict())
