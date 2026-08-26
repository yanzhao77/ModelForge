"""Agent API routes: 2.1 agent management + 3.0 Agent Run API (spec 25)."""

from core.database import SessionLocal, get_db
from core.security import get_current_user, get_runtime_admin
from fastapi import APIRouter, Depends, HTTPException, Query
from models.records import KnowledgeCollection, User
from models.records import AgentDefinitionVersion, AgentTemplate
from schemas.agent import AgentCreateRequest
from schemas.run import RunCreateRequest
from services.model_readiness_service import ModelReadinessService
from services.schedule_service import ScheduleService
from sqlalchemy.orm import Session as DBSession
import json
import uuid

router = APIRouter(prefix="/agent", tags=["agent"])

_agent_engine = None
_runtime = None


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
            raise HTTPException(status_code=422, detail="Selected Agent model target is not ready for this user.")
        model = target["model_name"]
    knowledge_config = dict(req.knowledge_config or {})
    collection_ids = list(knowledge_config.get("collection_ids") or [])
    if collection_ids:
        owned_count = db.query(KnowledgeCollection).filter(
            KnowledgeCollection.user_id == user.id,
            KnowledgeCollection.id.in_(collection_ids),
        ).count()
        if owned_count != len(set(collection_ids)):
            raise HTTPException(status_code=422, detail="Selected knowledge collection is not available to this user.")
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
        raise HTTPException(status_code=404, detail="Agent not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to persist agent definition: {exc}")
    result = _get_engine().create_agent(
        name=req.name,
        model_name=model,
        tools=req.tools,
        plugins=req.plugins,
        memory_config=req.memory,
        system_prompt=req.system_prompt,
    )
    result["model_target"] = target or {}
    previous = db.query(AgentDefinitionVersion).filter(AgentDefinitionVersion.user_id == user.id, AgentDefinitionVersion.agent_name == req.name).count()
    db.add(AgentDefinitionVersion(id=uuid.uuid4().hex, user_id=user.id, agent_name=req.name, version=previous + 1, snapshot_json=json.dumps(result, ensure_ascii=False), change_note="Initial definition"))
    db.commit()
    return result


@router.get("/templates")
async def list_agent_templates(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"templates": [item.to_dict() for item in db.query(AgentTemplate).filter(AgentTemplate.user_id == user.id).order_by(AgentTemplate.updated_at.desc()).all()]}


@router.post("/templates")
async def create_agent_template(req: dict, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    name = str((req or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="template name required")
    definition = dict((req or {}).get("definition") or {})
    for key in ("api_key", "token", "authorization", "password"):
        definition.pop(key, None)
    item = AgentTemplate(id=uuid.uuid4().hex, user_id=user.id, name=name, description=(req or {}).get("description"), definition_json=json.dumps(definition, ensure_ascii=False))
    db.add(item)
    db.commit()
    return item.to_dict()


@router.delete("/templates/{template_id}")
async def delete_agent_template(template_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(AgentTemplate).filter(AgentTemplate.id == template_id, AgentTemplate.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


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
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.get("/list")
async def list_agents(user: User = Depends(get_current_user)):
    """List only agents owned by the current user."""
    return [a.to_dict() for a in _get_runtime().list_agents(user_id=user.id)]


@router.delete("/{name}")
async def delete_agent(name: str, user: User = Depends(get_current_user)):
    """Delete an owned agent definition."""
    ok = _get_runtime().delete_agent(name, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    return {"ok": True}


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
async def register_mcp(req: dict, user: User = Depends(get_runtime_admin)):
    """Register an MCP server; its tools land in the Tool Registry (spec 70)."""
    name = (req or {}).get("name")
    endpoint = (req or {}).get("endpoint")
    if not name or not endpoint:
        raise HTTPException(status_code=400, detail="name and endpoint required")
    try:
        return await _get_runtime().register_mcp_server(name, endpoint)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"MCP register failed: {e}")


@router.get("/mcp/servers")
async def list_mcp_servers(user: User = Depends(get_runtime_admin)):
    return {"servers": _get_runtime().list_mcp_servers()}


@router.delete("/mcp/servers/{name}")
async def unregister_mcp(name: str, user: User = Depends(get_runtime_admin)):
    ok = await _get_runtime().unregister_mcp_server(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"MCP server {name} not found")
    return {"ok": True}


@router.get("/tools")
async def list_tools(user: User = Depends(get_current_user)):
    """Registered tools with permissions (spec 8)."""
    return {"tools": _get_runtime().list_tools()}


async def _persistent_schedule_trigger(schedule_id: str, run_spec: dict) -> None:
    """Create a scheduled run and write an audit record in a fresh DB session."""
    db = SessionLocal()
    try:
        service = ScheduleService(db)
        job = service.owned(int(run_spec.get("user_id") or 0), schedule_id)
        if job is None or not job.enabled:
            return
        rt = _get_runtime()
        run = rt.create_run(
            agent_id=run_spec.get("agent_id", ""),
            input_text=run_spec.get("input", ""),
            user_id=job.user_id,
            session_id=run_spec.get("session_id"),
            metadata={**(run_spec.get("metadata") or {}), "schedule_id": schedule_id},
            execute=True,
        )
        service.record_execution(job, run.run_id, "triggered")
    except Exception as exc:
        job = ScheduleService(db).owned(int(run_spec.get("user_id") or 0), schedule_id)
        if job is not None:
            ScheduleService(db).record_execution(job, None, "failed", error=exc)
    finally:
        db.close()


@router.post("/schedules")
async def create_schedule(
    req: dict,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a disabled schedule draft; ``enabled=true`` is an explicit opt-in."""
    payload = dict(req or {})
    if "schedule_kind" not in payload:
        payload["schedule_kind"] = "once" if payload.get("delay_seconds") is not None else "interval"
    agent_id = payload.get("agent_id")
    rt = _get_runtime()
    if not agent_id or rt.get_agent(agent_id, user_id=user.id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        job = ScheduleService(db).create_draft(user.id, payload)
        if payload.get("enabled") is True:
            callback = lambda spec: _persistent_schedule_trigger(job.id, spec)
            job = ScheduleService(db).enable(job, rt, callback)
        return job.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/schedules")
async def list_schedules(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {"schedules": [item.to_dict() for item in ScheduleService(db).list(user.id)]}


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, req: dict, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    job = ScheduleService(db).owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    try:
        return ScheduleService(db).update_draft(job, req or {}).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/schedules/{schedule_id}/enable")
async def enable_schedule(schedule_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    callback = lambda spec: _persistent_schedule_trigger(job.id, spec)
    try:
        return service.enable(job, _get_runtime(), callback).to_dict()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return service.pause(job, _get_runtime()).to_dict()


@router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    spec = __import__("json").loads(job.run_spec or "{}")
    rt = _get_runtime()
    run = rt.create_run(spec.get("agent_id", ""), spec.get("input", ""), user.id, spec.get("session_id"), {**(spec.get("metadata") or {}), "schedule_id": job.id, "trigger_kind": "manual"}, execute=True)
    service.record_execution(job, run.run_id, "triggered", trigger_kind="manual")
    return {"schedule_id": job.id, "run_id": run.run_id, "status": run.status}


@router.get("/schedules/{schedule_id}/executions")
async def schedule_executions(schedule_id: str, limit: int = Query(100, ge=1, le=500), db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, schedule_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"schedule_id": job.id, "executions": [item.to_dict() for item in service.executions(job, limit)]}


@router.delete("/schedules/{job_id}")
async def cancel_schedule(job_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = ScheduleService(db)
    job = service.owned(user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    service.delete(job, _get_runtime())
    return {"ok": True}


@router.get("/metrics")
async def runtime_metrics(user: User = Depends(get_runtime_admin)):
    """Runtime metrics snapshot (spec 49)."""
    return _get_runtime().metrics_snapshot()
