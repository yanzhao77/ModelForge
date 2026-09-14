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
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from services.local_api_service import (
    LocalApiError,
    LocalApiPrincipal,
    LocalApiService,
    SCOPE_AGENTS,
    SCOPE_EMBEDDINGS,
    SCOPE_KNOWLEDGE,
    SCOPE_MODELS_READ,
    SCOPE_WORKFLOWS,
    authenticate_local_api_key,
    openai_error_payload,
)
from services.model_capabilities import ModelCapability
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


def _auth(db: DBSession, authorization: str | None, scope: str) -> LocalApiPrincipal | JSONResponse:
    try:
        return authenticate_local_api_key(db, authorization, required_scope=scope)
    except LocalApiError as exc:
        corr = correlation_id()[:64]
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, corr, param=exc.param),
            status_code=exc.status_code,
            headers={"X-Request-ID": corr, "X-Correlation-ID": corr},
        )


@router.post("/v1/embeddings")
def create_embeddings(
    req: EmbeddingsRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    """OpenAI-compatible embeddings built from the registry's embedding model."""
    principal = _auth(db, authorization, SCOPE_EMBEDDINGS)
    if isinstance(principal, JSONResponse):
        return principal
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    if not texts:
        raise problem(422, "EMBEDDING_INPUT_REQUIRED", "input must not be empty.", correlation=correlation_id())
    if len(texts) > 64:
        raise problem(422, "EMBEDDING_INPUT_TOO_LARGE", "at most 64 inputs per request.", correlation=correlation_id())
    model_id = req.model_id
    if req.model and model_id is None:
        try:
            model_id = LocalApiService(db).require_model(principal.user_id, req.model, capability=ModelCapability.EMBEDDING.value).id
        except LocalApiError as exc:
            return JSONResponse(
                openai_error_payload(exc.code, exc.message, correlation_id()[:64], param=exc.param),
                status_code=exc.status_code,
            )
    result = embed_texts(db, principal.user_id, texts, model_id=model_id)
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
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    principal = _auth(db, authorization, SCOPE_AGENTS)
    if isinstance(principal, JSONResponse):
        return principal
    from services.agent_engine import get_engine
    from services.agent_runtime_service import get_agent_runtime
    from services.agent_service import AgentService

    service = AgentService(db, runtime=get_agent_runtime(), engine=get_engine())
    return {"object": "list", "data": service.list(principal.user_id)}


@router.post("/v1/agents/{agent_id}/runs")
async def developer_run_agent(
    agent_id: str,
    req: DeveloperAgentRunRequest,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    corr = _correlation(request)
    principal = _auth(db, authorization, SCOPE_AGENTS)
    if isinstance(principal, JSONResponse):
        return principal
    from services.agent_runtime_service import get_agent_runtime
    from services.agent_service import AgentService

    try:
        AgentService(db, runtime=get_agent_runtime()).require(agent_id, principal.user_id)
        run = AgentRunService(db, runtime=get_agent_runtime()).create_run(
            agent_id=agent_id,
            input_text=req.input,
            user_id=principal.user_id,
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
    run_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    principal = _auth(db, authorization, SCOPE_AGENTS)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        return AgentRunService(db).get_run(run_id, principal.user_id)
    except AgentServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.get("/v1/agents/runs/{run_id}/trace")
def developer_agent_trace(
    run_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    principal = _auth(db, authorization, SCOPE_AGENTS)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        return AgentRunService(db).trace(run_id, principal.user_id)
    except AgentServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.post("/v1/knowledge/search")
def developer_knowledge_search(
    req: DeveloperKnowledgeSearchRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    """Retrieve knowledge chunks for an external application."""
    principal = _auth(db, authorization, SCOPE_KNOWLEDGE)
    if isinstance(principal, JSONResponse):
        return principal
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
        user_id=principal.user_id,
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
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    corr = _correlation(request)
    principal = _auth(db, authorization, SCOPE_WORKFLOWS)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = WorkflowService(db).create_run(
            principal.user_id, workflow_id, run_input=req.input, execute=True
        )
    except WorkflowServiceError as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}, "correlation_id": corr},
            status_code=exc.http_status,
        )
    return {"object": "workflow.run", "created": int(time.time()), **result}


@router.get("/v1/workflows/runs/{run_id}")
def developer_get_workflow_run(
    run_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    principal = _auth(db, authorization, SCOPE_WORKFLOWS)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        return WorkflowService(db).get_run(principal.user_id, run_id)
    except WorkflowServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.get("/v1/workflows/runs/{run_id}/trace")
def developer_workflow_trace(
    run_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    principal = _auth(db, authorization, SCOPE_WORKFLOWS)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        return WorkflowService(db).trace(principal.user_id, run_id)
    except WorkflowServiceError as exc:
        raise problem(exc.http_status, exc.code, exc.message, correlation=correlation_id()) from exc


@router.get("/v1/platform/capabilities")
def developer_capabilities(authorization: str | None = Header(default=None, alias="Authorization"), db: DBSession = Depends(get_db)):
    """Machine-readable catalog for SDK/clients (no secrets, no user data)."""
    principal = _auth(db, authorization, SCOPE_MODELS_READ)
    if isinstance(principal, JSONResponse):
        return principal
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
