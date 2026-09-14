"""Sandbox diagnostics API."""
from __future__ import annotations

from core.security import get_current_user
from fastapi import APIRouter, Depends
from models.records import User
from pydantic import BaseModel, Field
from services.sandbox_provider import SandboxProviderError, SandboxProviderService

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class SandboxPythonRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20000)
    timeout_seconds: int = Field(default=10, ge=1, le=60)


@router.get("/status")
def sandbox_status(user: User = Depends(get_current_user)):  # noqa: ARG001 - authentication scopes diagnostics visibility
    return SandboxProviderService().status()


@router.post("/execute-python")
def sandbox_execute_python(
    req: SandboxPythonRequest,
    user: User = Depends(get_current_user),  # noqa: ARG001 - authenticated action, policy binding follows in M5 tool integration
):
    try:
        return SandboxProviderService().execute_python(req.code, timeout_seconds=req.timeout_seconds)
    except SandboxProviderError as exc:
        from core.api_contracts import correlation_id, problem

        raise problem(503 if exc.code != "SANDBOX_TIMEOUT" else 504, exc.code, exc.message, correlation=correlation_id()) from exc
