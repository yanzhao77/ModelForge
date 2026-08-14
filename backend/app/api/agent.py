"""Agent API routes: 2.1 agent management + 3.0 Agent Run API (spec 25)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from core.database import get_db
from core.security import get_current_user_optional
from models.records import User
from schemas.agent import AgentCreateRequest
from schemas.run import RunCreateRequest

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
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Create a new AI agent (in-memory engine + DB persistence)."""
    engine = _get_engine()
    info = engine.create_agent(
        name=req.name,
        model_name=req.model,
        tools=req.tools,
        memory_config=req.memory,
        system_prompt=req.system_prompt,
    )
    try:
        rt = _get_runtime()
        from runtime.types import AgentConfig
        rt.create_agent(AgentConfig(
            name=req.name,
            model=req.model,
            user_id=user.id if user else None,
            tools=req.tools,
            system_prompt=req.system_prompt,
            description=req.description,
            memory_config=req.memory,
            policy=req.policy,
            runtime_config=req.runtime_config,
            knowledge_config=req.knowledge_config,
        ))
    except HTTPException:
        raise
    except Exception:
        pass  # engine-only registration still succeeds
    return info


@router.post("/{name}/chat")
async def agent_chat(name: str, req: dict):
    """Send a message to an agent (2.1 LangGraph chat, policy-enforced in 3.x)."""
    message = (req or {}).get("message", "")
    engine = _get_engine()
    policy = None
    tool_registry = None
    try:
        rt = _get_runtime()
        agent = rt.get_agent(name)
        if agent is not None and rt.policy_engine is not None:
            policy = rt.policy_engine.for_agent(agent)
            tool_registry = rt.tool_registry
    except HTTPException:
        pass
    except Exception:
        pass
    result = engine.chat(name, message, llm_callback=None, policy=policy, tool_registry=tool_registry)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/list")
async def list_agents():
    """List all registered agents (engine + DB)."""
    rt = _get_runtime()
    return [a.to_dict() for a in rt.list_agents()]


@router.delete("/{name}")
async def delete_agent(name: str):
    """Delete an agent definition."""
    ok = _get_runtime().delete_agent(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Agent {name} not found")
    return {"ok": True}


# ---------------- 3.0 Agent Run API (spec 25) ----------------


@router.post("/runs")
async def create_run(
    req: RunCreateRequest,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Create an agent run; optionally start execution (async)."""
    rt = _get_runtime()
    try:
        run = rt.create_run(
            agent_id=req.agent_id,
            input_text=req.input,
            user_id=user.id if user else None,
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
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: Optional[User] = Depends(get_current_user_optional),
):
    runs = _get_runtime().list_runs(
        user_id=user.id if user else None,
        agent_id=agent_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [r.to_dict() for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    try:
        run = _get_runtime().get_run(run_id, user_id=user.id if user else None)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    try:
        run = await _get_runtime().cancel_run(run_id, user_id=user.id if user else None)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.post("/runs/{run_id}/approve")
async def approve_run(
    run_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Approve a pending human-approval request (spec 32)."""
    try:
        run = await _get_runtime().approve_run(run_id, user_id=user.id if user else None)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.post("/runs/{run_id}/reject")
async def reject_run(
    run_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Reject a pending human-approval request (spec 32)."""
    try:
        run = await _get_runtime().reject_run(run_id, user_id=user.id if user else None)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return run.to_dict()


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Persisted event list with SSE resume support (spec 30 / 31)."""
    try:
        events = _get_runtime().list_events(
            run_id, after_sequence=after_sequence, limit=limit,
            user_id=user.id if user else None,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_id": run_id, "events": [e.to_dict() for e in events]}


@router.get("/runs/{run_id}/stream")
async def run_stream(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """SSE run stream: replay persisted events then live events (spec 26 / 31)."""
    import json
    from fastapi.responses import StreamingResponse
    rt = _get_runtime()
    try:
        rt.get_run(run_id, user_id=user.id if user else None)
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
async def register_mcp(req: dict):
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
async def list_mcp_servers():
    return {"servers": _get_runtime().list_mcp_servers()}


@router.delete("/mcp/servers/{name}")
async def unregister_mcp(name: str):
    ok = await _get_runtime().unregister_mcp_server(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"MCP server {name} not found")
    return {"ok": True}


@router.get("/tools")
async def list_tools():
    """Registered tools with permissions (spec 8)."""
    return {"tools": _get_runtime().list_tools()}


@router.post("/schedules")
async def create_schedule(req: dict):
    """Schedule an agent run once or on an interval (spec 38 / 72)."""
    agent_id = (req or {}).get("agent_id")
    input_text = (req or {}).get("input", "")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    run_spec = {"agent_id": agent_id, "input": input_text, "session_id": (req or {}).get("session_id")}
    delay = (req or {}).get("delay_seconds")
    interval = (req or {}).get("interval_seconds")
    rt = _get_runtime()
    try:
        if delay is not None:
            job_id = rt.schedule_once(float(delay), run_spec)
            kind = "once"
        elif interval is not None:
            job_id = rt.schedule_interval(float(interval), run_spec)
            kind = "interval"
        else:
            raise HTTPException(status_code=400, detail="delay_seconds or interval_seconds required")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"job_id": job_id, "type": kind, "agent_id": agent_id}


@router.get("/schedules")
async def list_schedules():
    return {"schedules": _get_runtime().list_schedules()}


@router.delete("/schedules/{job_id}")
async def cancel_schedule(job_id: str):
    ok = _get_runtime().cancel_schedule(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Schedule {job_id} not found")
    return {"ok": True}


@router.get("/metrics")
async def runtime_metrics():
    """Runtime metrics snapshot (spec 49)."""
    return _get_runtime().metrics_snapshot()