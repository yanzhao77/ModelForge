"""Developer-facing OpenAI-compatible surface (V1.6).

`/v1/chat/completions` and `/v1/models` already exist. This router adds the
rest of the documented platform API: embeddings, agents, knowledge search and
workflows. Every endpoint is a thin adapter over the same services the
first-party UI uses, so third-party clients cannot drift from ModelForge's own
behaviour.
"""

from __future__ import annotations

import time

from core.api_contracts import correlation_id, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from models.records import User
from pydantic import BaseModel, Field
from services.agent_run_service import AgentRunService
from services.agent_service import AgentServiceError
from services.embedding_service import embed_texts
from services.workflow_service import WorkflowService, WorkflowServiceError
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["developer"])


class EmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str | None = Field(default=None, max_length=255)
    model_id: int | None = None


class DeveloperAgentRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    session_id: int | None = None
    metadata: dict | None = None


class DeveloperKnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    knowledge_id: str | None = None
    retrieval_mode: str | None = None


class DeveloperWorkflowRunRequest(BaseModel):
    input: dict = Field(default_factory=dict)


def _correlation(request: Request) -> str:
    return (request.headers.get("X-Request-ID") or correlation_id())[:64]


@router.post("/v1/embeddings")
def create_embeddings(
    req: EmbeddingsRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """OpenAI-compatible embeddings built from the registry's embedding model."""
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    if not texts:
        raise problem(422, "EMBEDDING_INPUT_REQUIRED", "input must not be empty.", correlation=correlation_id())
    if len(texts) > 64:
        raise problem(422, "EMBEDDING_INPUT_TOO_LARGE", "at most 64 inputs per request.", correlation=correlation_id())
    result = embed_texts(db, user.id, texts, model_id=req.model_id)
    tokens = sum(len(text.split()) for text in texts)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(result["vectors"])
        ],
        "model": req.model or result["embedding"].get("provider", "modelforge-embedding"),
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        "embedding": result["embedding"],
    }


@router.get("/v1/agents")
def developer_list_agents(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from services.agent_engine import get_engine
    from services.agent_runtime_service import get_agent_runtime
    from services.agent_service import AgentService

    service = AgentService(db, runtime=get_agent_runtime(), engine=get_engine())
    return {"object": "list", "data": service.list(user.id)}


@router.post("/v1/agents/{agent_id}/runs")
async def developer_run_agent(
    agent_id: str,
    req: DeveloperAgentRunRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = _correlation(request)
    from services.agent_runtime_service import get_agent_runtime
    from services.agent_service import AgentService

    try:
        AgentService(db, runtime=get_agent_runtime()).require(agent_id, user.id)
        run = AgentRunService(db, runtime=get_agent_runtime()).create_run(
            agent_id=agent_id,
            input_text=req.input,
            user_id=user.id,
            session_id=req.session_id,
            metadata=req.metadata,
            execute=True,
        )
    except AgentServiceError as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}, "correlation_id": corr},
            status_code=exc.http_status,
        )
    return {"object": "agent.run", "created": int(time.time()), **run}


@router.get("/v1/agents/runs/{run_id}")
def developer_get_agent_run(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return AgentRunService(db).get_run(run_id, user.id)
    except AgentServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.get("/v1/agents/runs/{run_id}/trace")
def developer_agent_trace(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return AgentRunService(db).trace(run_id, user.id)
    except AgentServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.post("/v1/knowledge/search")
def developer_knowledge_search(
    req: DeveloperKnowledgeSearchRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve knowledge chunks for an external application."""
    from api.knowledge import _get_kb

    kb = _get_kb(correlation=correlation_id())
    binding = (
        {"mode": "collections", "collection_ids": [req.knowledge_id]}
        if req.knowledge_id
        else None
    )
    result = kb.query(
        req.query,
        top_k=req.top_k,
        db=db,
        user_id=user.id,
        knowledge_binding=binding,
        retrieval_mode=req.retrieval_mode,
    )
    return {
        "object": "list",
        "data": result["results"],
        "retrieval_mode": result["retrieval_mode"],
    }


@router.post("/v1/workflows/{workflow_id}/runs")
async def developer_run_workflow(
    workflow_id: str,
    req: DeveloperWorkflowRunRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = _correlation(request)
    try:
        result = WorkflowService(db).create_run(
            user.id, workflow_id, run_input=req.input, execute=True
        )
    except WorkflowServiceError as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}, "correlation_id": corr},
            status_code=exc.http_status,
        )
    return {"object": "workflow.run", "created": int(time.time()), **result}


@router.get("/v1/workflows/runs/{run_id}")
def developer_get_workflow_run(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return WorkflowService(db).get_run(user.id, run_id)
    except WorkflowServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.get("/v1/workflows/runs/{run_id}/trace")
def developer_workflow_trace(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return WorkflowService(db).trace(user.id, run_id)
    except WorkflowServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.get("/v1/platform/capabilities")
def developer_capabilities(user: User = Depends(get_current_user)):
    """Machine-readable catalog for SDK/clients (no secrets, no user data)."""
    del user
    from runtime.tools.base import PermissionLevel
    from services.runtime_resolver import RuntimeResolver
    from services.workflow_engine import NODE_TYPES

    return {
        "object": "platform.capabilities",
        "endpoints": {
            "models": "/v1/models",
            "chat": "/v1/chat/completions",
            "embeddings": "/v1/embeddings",
            "agents": "/v1/agents",
            "knowledge": "/v1/knowledge/search",
            "workflows": "/v1/workflows/{workflow_id}/runs",
        },
        "runtimes": [
            {"id": adapter.id, "label": adapter.label, "capabilities": sorted(adapter.capabilities)}
            for adapter in RuntimeResolver.catalog()
        ],
        "workflow_node_types": list(NODE_TYPES),
        "tool_permissions": PermissionLevel.catalog(),
    }
