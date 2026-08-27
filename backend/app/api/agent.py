"""Agent API routes: 2.1 agent management + 3.0 Agent Run API (spec 25)."""

from typing import Any

from core.api_contracts import correlation_id, operation_result, problem
from core.database import SessionLocal, get_db
from core.security import get_current_user, get_runtime_admin
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from models.records import KnowledgeCollection, User
from models.records import AgentDefinitionVersion, AgentTemplate
from pydantic import BaseModel, ConfigDict, Field
from schemas.agent import AgentCreateRequest
from schemas.run import RunCreateRequest
from services.model_readiness_service import ModelReadinessService
from services.schedule_service import ScheduleService
from services.audit_log import record_operation
from sqlalchemy.orm import Session as DBSession
import json
import uuid

router = APIRouter(prefix="/agent", tags=["agent"])

_agent_engine = None
_runtime = None


class AgentTemplateRequest(BaseModel):
    """Compatible, audited request payload for a persisted template."""

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    definition: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=64)


class MCPServerRequest(BaseModel):
    """Administrator-controlled MCP registration payload."""

    name: str = Field(min_length=1, max_length=160)
    endpoint: str = Field(min_length=1, max_length=2048)
    request_id: str | None = Field(default=None, max_length=64)


class ScheduleDraftRequest(BaseModel):
    """Compatible typed schedule payload that preserves existing draft fields."""

    model_config = ConfigDict(extra="allow")

    agent_id: str | None = Field(default=None, min_length=1, max_length=160)
    schedule_kind: str | None = Field(default=None, max_length=32)
    delay_seconds: int | None = Field(default=None, ge=0)
    request_id: str | None = Field(default=None, max_length=64)

    def schedule_payload(self, *, partial: bool = False) -> dict[str, Any]:
        fields = self.model_fields_set if partial else None
        payload = self.model_dump(exclude_none=True, exclude=({"request_id"}))
        if fields is not None:
            payload = {key: value for key, value in payload.items() if key in fields}
        return payload


class ScheduleActionRequest(BaseModel):
    """Explicit confirmation boundary for schedule state transitions."""

    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


def set_agent_engine(engine):
    global _agent_engine
    _agent_engine = engine


def set_agent_runtime(runtime):
    global _runtime
    _runtime = runtime


def _get_runtime():
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return _runtime


def _get_engine():
    if _agent_engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not initialized")
    return _agent_engine


# ---------------- 2.1 agent management ----------------


@router.post("/create")
async def create_agent(
    req: AgentCreateRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create an owned agent definition before exposing it to the legacy engine."""
    corr = correlation_id()
    rt = _get_runtime()
    from runtime.types import AgentConfig
    model, target = req.model, None
    if req.model_target is not None:
        target = ModelReadinessService(db).target_for(
            user.id,
            kind=req.model_target.kind,
            model_ref=req.model_target.model_ref,
            provider_id=req.model_target.provider_id,
        )
        if target is None or target.get("model_name") != req.model_target.model_name:
            raise problem(422, "MODEL_TARGET_NOT_READY", "Selected Agent model target is not ready for this user.", correlation=corr)
        model = target["model_name"]
    knowledge_config = dict(req.knowledge_config or {})
    collection_ids = list(knowledge_config.get("collection_ids") or [])
    if collection_ids:
        owned_count = db.query(KnowledgeCollection).filter(
            KnowledgeCollection.user_id == user.id,
            KnowledgeCollection.id.in_(collection_ids),
        ).count()
        if owned_count != len(set(collection_ids)):
            raise problem(422, "KNOWLEDGE_COLLECTION_UNAVAILABLE", "Selected knowledge collection is not available to this user.", correlation=corr)
        knowledge_config["collection_ids"] = list(dict.fromkeys(collection_ids))
    try:
        rt.create_agent(AgentConfig(
            name=req.name,
            model=model,
            user_id=user.id,
            tools=req.tools,
            plugins=req.plugins,
            system_prompt=req.system_prompt,
            description=req.description,
            memory_config=req.memory,
            policy=req.policy,
            runtime_config=req.runtime_config,
            model_target=target,
            knowledge_config=knowledge_config,
        ))
    except PermissionError:
        raise problem(404, "AGENT_NOT_FOUND", "Agent not found", correlation=corr)
    except Exception as exc:
        raise problem(500, "AGENT_DEFINITION_PERSIST_FAILED", "Failed to persist agent definition", correlation=corr)
    result = _get_engine().create_agent(
        name=req.name,
        model_name=model,
        tools=req.tools,
        plugins=req.plugins,
        memory_config=req.memory,
        system_prompt=req.system_prompt,
        user_id=user.id,
    )
    result["model_target"] = target or {}
    previous = db.query(AgentDefinitionVersion).filter(AgentDefinitionVersion.user_id == user.id, AgentDefinitionVersion.agent_name == req.name).count()
    db.add(AgentDefinitionVersion(id=uuid.uuid4().hex, user_id=user.id, agent_name=req.name, version=previous + 1, snapshot_json=json.dumps(result, ensure_ascii=False), change_note="Initial definition"))
    record_operation(
        db,
        user_id=user.id,
        action="agent.create",
        object_type="agent",
        object_id=req.name,
        correlation_id=corr,
        metadata={"model": model, "tool_count": len(req.tools or []), "plugin_count": len(req.plugins or [])},
    )
    db.commit()
    return operation_result(result, corr)


@router.get("/templates")
async def list_agent_templates(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"templates": [item.to_dict() for item in db.query(AgentTemplate).filter(AgentTemplate.user_id == user.id).order_by(AgentTemplate.updated_at.desc()).all()]}


@router.post("/templates")
async def create_agent_template(req: AgentTemplateRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = req.request_id or correlation_id()
    name = req.name.strip()
    definition = dict(req.definition or {})
    for key in ("api_key", "token", "authorization", "password"):
        definition.pop(key, None)
    item = AgentTemplate(id=uuid.uuid4().hex, user_id=user.id, name=name, description=req.description, definition_json=json.dumps(definition, ensure_ascii=False))
    db.add(item)
    record_operation(
        db,
        user_id=user.id,
        action="agent_template.create",
        object_type="agent_template",
        object_id=item.id,
        correlation_id=corr,
        metadata={"name": name, "definition_keys": sorted(definition)[:40]},
    )
    db.commit()
    return operation_result(item.to_dict(), corr)


@router.delete("/templates/{template_id}")
async def delete_agent_template(template_id: str, request_id: str | None = Header(default=None, alias="X-Request-ID"), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = request_id or correlation_id()
    item = db.query(AgentTemplate).filter(AgentTemplate.id == template_id, AgentTemplate.user_id == user.id).first()
    if item is None:
        raise problem(404, "AGENT_TEMPLATE_NOT_FOUND", "Template not found", correlation=corr)
    db.delete(item)
    record_operation(db, user_id=user.id, action="agent_template.delete", object_type="agent_template", object_id=template_id, correlation_id=corr, metadata={"name": item.name})
    db.commit()
    return operation_result({"ok": True}, corr)


@router.get("/{name}/versions")
async def agent_versions(name: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    items = db.query(AgentDefinitionVersion).filter(AgentDefinitionVersion.user_id == user.id, AgentDefinitionVersion.agent_name == name).order_by(AgentDefinitionVersion.version.desc()).all()
    return {"agent_name": name, "versions": [item.to_dict() for item in items]}

@router.post("/{name}/chat")
async def agent_chat(name: str, req: dict, user: User = Depends(get_current_user)):
    """Send a message to an agent owned by the requesting user."""
    rt = _get_runtime()
    agent = rt.get_agent(name, user_id=user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    policy = rt.policy_engine.for_agent(agent) if rt.policy_engine is not None else None
    result = _get_engine().chat(
        name,
        (req or {}).get("message", ""),
        llm_callback=None,
        policy=policy,
        tool_registry=rt.tool_registry,
        user_id=user.id,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.get("/list")
async def list_agents(user: User = Depends(get_current_user)):
    """List only agents owned by the current user."""
    return [a.to_dict() for a in _get_runtime().list_agents(user_id=user.id)]


@router.delete("/{name}")
async def delete_agent(name: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete an owned agent definition."""
    corr = correlation_id()
    ok = _get_runtime().delete_agent(name, user_id=user.id)
    if not ok:
        raise problem(404, "AGENT_NOT_FOUND", "Agent not found", correlation=corr)
    _get_engine().delete_agent(name, user_id=user.id)
    record_operation(db, user_id=user.id, action="agent.delete", object_type="agent", object_id=name, correlation_id=corr)
    db.commit()
    return operation_result({"ok": True}, corr)


# ---------------- 3.0 Agent Run API (spec 25) ----------------


@router.post("/runs")
async def create_run(
    req: RunCreateRequest,
    user: User = Depends(get_current_user),
):
    """Create an agent run; optionally start execution (async)."""
    rt = _get_runtime()
    if rt.get_agent(req.agent_id, user_id=user.id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        run = rt.create_run(
            agent_id=req.agent_id,
            input_text=req.input,
            user_id=user.id,
            session_id=req.session_id,
            metadata=req.metadata,
            execute=req.execute,
        )
    except Exception as e:
        code = getattr(e, "code", None)
        if code == "AGENT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    return {"run_id": run.run_id, "status": run.status, "agent_id": run.agent_id}


@router.get("/runs")
async def list_runs(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    runs = _get_runtime().list_runs(
        user_id=user.id,
        agent_id=agent_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [r.to_dict() for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
):
    try:
        run = _get_runtime().get_run(run_id, user_id=user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    user: User = Depends(get_current_user),
):
    try:
        run = await _get_runtime().cancel_run(run_id, user_id=user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.post("/runs/{run_id}/approve")
async def approve_run(
    run_id: str,
    user: User = Depends(get_current_user),
):
    """Approve a pending human-approval request (spec 32)."""
    try:
        run = await _get_runtime().approve_run(run_id, user_id=user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.post("/runs/{run_id}/reject")
async def reject_run(
    run_id: str,
    user: User = Depends(get_current_user),
):
    """Reject a pending human-approval request (spec 32)."""
    try:
        run = await _get_runtime().reject_run(run_id, user_id=user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    user: User = Depends(get_current_user),
):
    """Persisted event list with SSE resume support (spec 30 / 31)."""
    try:
        events = _get_runtime().list_events(
            run_id, after_sequence=after_sequence, limit=limit,
            user_id=user.id,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_id": run_id, "events": [e.to_dict() for e in events]}


@router.get("/runs/{run_id}/stream")
async def run_stream(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    """SSE run stream: replay persisted events then live events (spec 26 / 31)."""
    import json

    from fastapi.responses import StreamingResponse
    rt = _get_runtime()
    try:
        rt.get_run(run_id, user_id=user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    async def event_generator():
        async for ev in rt.stream_events(
            run_id, after_sequence=after_sequence, user_id=user.id if user else None,
        ):
            if ev is None:
                yield ": keepalive\n\n"
            else:
                yield f"event: {ev.event_type}\ndata: {json.dumps(ev.to_dict(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/mcp/servers")
async def register_mcp(req: MCPServerRequest, db: DBSession = Depends(get_db), user: User = Depends(get_runtime_admin)):
    """Register an MCP server; its tools land in the Tool Registry (spec 70)."""
    corr = req.request_id or correlation_id()
    name = req.name
    endpoint = req.endpoint
    try:
        result = await _get_runtime().register_mcp_server(name, endpoint)
    except Exception:
        raise problem(400, "MCP_REGISTER_FAILED", "MCP register failed", correlation=corr)
    record_operation(db, user_id=user.id, action="mcp.register", object_type="mcp_server", object_id=name, correlation_id=corr, metadata={"endpoint_configured": True})
    db.commit()
    return operation_result(result if isinstance(result, dict) else {"ok": True, "name": name}, corr)


@router.get("/mcp/servers")
async def list_mcp_servers(user: User = Depends(get_runtime_admin)):
    return {"servers": _get_runtime().list_mcp_servers()}


@router.delete("/mcp/servers/{name}")
async def unregister_mcp(name: str, request_id: str | None = Header(default=None, alias="X-Request-ID"), db: DBSession = Depends(get_db), user: User = Depends(get_runtime_admin)):
    corr = request_id or correlation_id()
    ok = await _get_runtime().unregister_mcp_server(name)
    if not ok:
        raise problem(404, "MCP_SERVER_NOT_FOUND", "MCP server not found", correlation=corr)
    record_operation(db, user_id=user.id, action="mcp.unregister", object_type="mcp_server", object_id=name, correlation_id=corr)
    db.commit()
    return operation_result({"ok": True}, corr)


@router.get("/tools")
async def list_tools(user: User = Depends(get_current_user)):
    """Registered tools with permissions (spec 8)."""
    return {"tools": _get_runtime().list_tools()}


def _persistent_schedule_callback(schedule_id: str):
    """Bind a durable schedule identifier without persisting a callable."""
    return lambda run_spec: _persistent_schedule_trigger(schedule_id, run_spec)


async def _persistent_schedule_trigger(schedule_id: str, run_spec: dict) -> None:
    """Create a scheduled run and write an audit record in a fresh DB session."""
    db = SessionLocal()
    try:
        service = ScheduleService(db)
        job = service.owned(int(run_spec.get("user_id") or 0), schedule_id)
        if job is None or not job.enabled:
            return
        rt = _get_runtime()
        is_queue_recheck = bool(run_spec.get("_schedule_queue_recheck"))
        trigger_kind = "queue_recheck" if is_queue_recheck else "schedule"
        decision, claim = service.claim_occurrence(job, trigger_kind=trigger_kind)
        if not is_queue_recheck:
            service.advance_after_callback(job, rt, _persistent_schedule_callback)
        if decision == "pending" and is_queue_recheck:
            service.defer_pending(job, rt, _persistent_schedule_callback)
            return
        if decision in {"disabled", "skipped", "pending", "duplicate"}:
            return
        if decision == "queued":
            service.defer_pending(job, rt, _persistent_schedule_callback)
            return
        run = rt.create_run(
            agent_id=run_spec.get("agent_id", ""),
            input_text=run_spec.get("input", ""),
            user_id=job.user_id,
            session_id=run_spec.get("session_id"),
            metadata={**(run_spec.get("metadata") or {}), "schedule_id": schedule_id},
            execute=True,
        )
        if claim is not None:
            service.bind_claim_to_run(claim, run.run_id)
    except Exception as exc:
        job = ScheduleService(db).owned(int(run_spec.get("user_id") or 0), schedule_id)
        if job is not None and "claim" in locals() and claim is not None:
            ScheduleService(db).fail_claim(claim, exc)
        elif job is not None:
            ScheduleService(db).record_execution(job, None, "failed", error=exc)
    finally:
        db.close()


@router.post("/schedules")
async def create_schedule(
    req: ScheduleDraftRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a disabled schedule draft; enable is always a separate action."""
    corr = req.request_id or correlation_id()
    payload = req.schedule_payload()
    if "schedule_kind" not in payload:
        payload["schedule_kind"] = "once" if payload.get("delay_seconds") is not None else "interval"
    agent_id = payload.get("agent_id")
    rt = _get_runtime()
    if not agent_id or rt.get_agent(agent_id, user_id=user.id) is None:
        raise problem(404, "AGENT_NOT_FOUND", "Agent not found", correlation=corr)
    try:
        item = ScheduleService(db).create_draft(user.id, payload, commit=False)
    except ValueError as exc:
        raise problem(422, "SCHEDULE_DRAFT_INVALID", "Schedule draft is invalid", correlation=corr) from exc
    try:
        record_operation(
            db,
            user_id=user.id,
            action="schedule.draft.create",
            object_type="schedule",
            object_id=item.id,
            correlation_id=corr,
            metadata={"agent_id": agent_id, "schedule_kind": payload.get("schedule_kind"), "enabled": False},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "SCHEDULE_DRAFT_PERSIST_FAILED", "Schedule draft could not be persisted", correlation=corr) from exc
    return operation_result(item.to_dict(), corr)


@router.get("/schedules")
async def list_schedules(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"schedules": [item.to_dict() for item in ScheduleService(db).list(user.id)]}


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, req: ScheduleDraftRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = req.request_id or correlation_id()
    job = ScheduleService(db).owned(user.id, schedule_id)
    if job is None:
        raise problem(404, "SCHEDULE_NOT_FOUND", "Schedule not found", correlation=corr)
    try:
        item = ScheduleService(db).update_draft(job, req.schedule_payload(partial=True), commit=False)
    except ValueError as exc:
        raise problem(409, "SCHEDULE_DRAFT_CONFLICT", "Schedule draft cannot be updated", correlation=corr) from exc
    try:
        record_operation(
            db,
            user_id=user.id,
            action="schedule.draft.update",
            object_type="schedule",
            object_id=item.id,
            correlation_id=corr,
            metadata={"updated_fields": sorted(req.model_fields_set - {"request_id"})[:40]},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "SCHEDULE_DRAFT_PERSIST_FAILED", "Schedule draft could not be persisted", correlation=corr) from exc
    return operation_result(item.to_dict(), corr)


@router.post("/schedules/{schedule_id}/enable")
async def enable_schedule(schedule_id: str, req: ScheduleActionRequest | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "CONFIRM_REQUIRED", "Explicit confirmation is required to enable a schedule", correlation=corr)
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise problem(404, "SCHEDULE_NOT_FOUND", "Schedule not found", correlation=corr)
    try:
        item = service.enable_desired(job, commit=False)
        record_operation(db, user_id=user.id, action="schedule.enable", object_type="schedule", object_id=item.id, correlation_id=corr, metadata={"explicit_confirm": True, "runtime_sync": "requested"})
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "SCHEDULE_ENABLE_PERSIST_FAILED", "Schedule enable state could not be persisted", correlation=corr) from exc
    runtime_sync = "pending"
    try:
        item = service.arm_enabled(item, _get_runtime(), _persistent_schedule_callback)
        runtime_sync = "armed" if item.runtime_job_id else "not_required"
    except Exception:
        # The committed desired state is safe: a future callback sees it, while
        # no new run is created by this error path.
        runtime_sync = "pending"
    return operation_result({**item.to_dict(), "runtime_sync": runtime_sync}, corr)


@router.post("/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str, req: ScheduleActionRequest | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "CONFIRM_REQUIRED", "Explicit confirmation is required to pause a schedule", correlation=corr)
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise problem(404, "SCHEDULE_NOT_FOUND", "Schedule not found", correlation=corr)
    try:
        item, runtime_job_id = service.pause_desired(job, commit=False)
        record_operation(db, user_id=user.id, action="schedule.pause", object_type="schedule", object_id=item.id, correlation_id=corr, metadata={"explicit_confirm": True, "runtime_sync": "requested"})
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "SCHEDULE_PAUSE_PERSIST_FAILED", "Schedule pause state could not be persisted", correlation=corr) from exc
    runtime_sync = "not_required"
    if runtime_job_id:
        try:
            cancelled = _get_runtime().cancel_schedule(runtime_job_id, user_id=user.id)
            runtime_sync = "cancelled" if cancelled else "pending"
        except Exception:
            # A stale callback is still harmless: it rechecks the committed
            # disabled job state before attempting any Run creation.
            runtime_sync = "pending"
    return operation_result({**item.to_dict(), "runtime_sync": runtime_sync}, corr)


@router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(
    schedule_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    req: ScheduleActionRequest | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "CONFIRM_REQUIRED", "Explicit confirmation is required to run a schedule", correlation=corr)
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise problem(404, "SCHEDULE_NOT_FOUND", "Schedule not found", correlation=corr)
    spec = __import__("json").loads(job.run_spec or "{}")
    decision, claim = service.claim_occurrence(
        job,
        trigger_kind="manual",
        operation_id=idempotency_key,
        require_enabled=False,
    )
    if decision != "run":
        return operation_result({
            "schedule_id": job.id,
            "run_id": claim.agent_run_id if claim else None,
            "status": claim.outcome if claim else decision,
            "duplicate": decision == "duplicate",
        }, corr)
    rt = _get_runtime()
    try:
        run = rt.create_run(spec.get("agent_id", ""), spec.get("input", ""), user.id, spec.get("session_id"), {**(spec.get("metadata") or {}), "schedule_id": job.id, "trigger_kind": "manual"}, execute=True)
        if claim is not None:
            service.bind_claim_to_run(claim, run.run_id)
    except Exception as exc:
        if claim is not None:
            service.fail_claim(claim, exc)
        raise
    record_operation(db, user_id=user.id, action="schedule.run_now", object_type="schedule", object_id=job.id, correlation_id=corr, metadata={"operation_id_supplied": bool(idempotency_key), "explicit_confirm": True})
    db.commit()
    return operation_result({"schedule_id": job.id, "run_id": run.run_id, "status": run.status}, corr)


@router.get("/schedules/{schedule_id}/executions")
async def schedule_executions(schedule_id: str, limit: int = Query(100, ge=1, le=500), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"schedule_id": job.id, "executions": [item.to_dict() for item in service.executions(job, limit)]}


@router.get("/schedules/{schedule_id}/preview")
async def schedule_preview(schedule_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"schedule_id": job.id, "timezone": job.timezone, "next_runs": service.preview(job)}


def restore_persistent_schedules() -> int:
    """Called once during backend lifespan; never enables draft schedules."""
    db = SessionLocal()
    try:
        return ScheduleService(db).restore_enabled(_get_runtime(), _persistent_schedule_callback)
    finally:
        db.close()


@router.delete("/schedules/{job_id}")
async def cancel_schedule(job_id: str, req: ScheduleActionRequest | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    corr = (req.request_id if req else None) or correlation_id()
    if req is None or not req.confirm:
        raise problem(409, "CONFIRM_REQUIRED", "Explicit confirmation is required to delete a schedule", correlation=corr)
    service = ScheduleService(db)
    job = service.owned(user.id, job_id)
    if job is None:
        raise problem(404, "SCHEDULE_NOT_FOUND", "Schedule not found", correlation=corr)
    try:
        runtime_job_id = service.delete_desired(job, commit=False)
        record_operation(db, user_id=user.id, action="schedule.delete", object_type="schedule", object_id=job_id, correlation_id=corr, metadata={"explicit_confirm": True, "runtime_sync": "requested"})
        db.commit()
    except Exception as exc:
        db.rollback()
        raise problem(500, "SCHEDULE_DELETE_PERSIST_FAILED", "Schedule deletion could not be persisted", correlation=corr) from exc
    runtime_sync = "not_required"
    if runtime_job_id:
        try:
            cancelled = _get_runtime().cancel_schedule(runtime_job_id, user_id=user.id)
            runtime_sync = "cancelled" if cancelled else "pending"
        except Exception:
            runtime_sync = "pending"
    return operation_result({"ok": True, "runtime_sync": runtime_sync}, corr)


@router.get("/metrics")
async def runtime_metrics(user: User = Depends(get_runtime_admin)):
    """Runtime metrics snapshot (spec 49)."""
    return _get_runtime().metrics_snapshot()
