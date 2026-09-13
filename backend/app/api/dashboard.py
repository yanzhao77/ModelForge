"""Platform dashboard + unified event feed (V2.0)."""

from __future__ import annotations

import datetime
import json

from core.api_contracts import correlation_id, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import (
    AgentEventRecord,
    AgentRun,
    Dataset,
    KnowledgeCollection,
    KnowledgeDocument,
    Message,
    ModelRecord,
    Session,
    TaskEvent,
    TaskRecord,
    TrainTask,
    User,
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
)
from services.model_capabilities import READY_STATUSES
from services.model_registry import ModelRegistry
from services.model_runtime_manager import get_model_runtime_manager
from services.resource_manager import get_resource_manager
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["platform"])


def _iso(value) -> str | None:
    return value.isoformat() if value else None


@router.get("/dashboard")
def dashboard(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Everything the home screen shows, in one round trip."""
    manager = get_model_runtime_manager()
    registry = ModelRegistry(db)
    models = registry.list_models(user.id)
    ready_models = [record for record in models if registry.is_ready(record)]

    sessions = (
        db.query(Session)
        .filter(Session.user_id == user.id, Session.is_active.is_(True))
        .order_by(Session.updated_at.desc())
        .limit(5)
        .all()
    )
    agent_runs = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(5)
        .all()
    )
    training = (
        db.query(TrainTask)
        .filter(TrainTask.user_id == user.id)
        .order_by(TrainTask.created_at.desc())
        .limit(5)
        .all()
    )
    knowledge_bases = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.user_id == user.id)
        .order_by(KnowledgeCollection.created_at.desc())
        .limit(10)
        .all()
    )
    workflows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user.id)
        .order_by(Workflow.updated_at.desc())
        .limit(5)
        .all()
    )
    failed_tasks = (
        db.query(TaskRecord)
        .filter(TaskRecord.user_id == user.id, TaskRecord.status == "FAILED")
        .order_by(TaskRecord.updated_at.desc())
        .limit(5)
        .all()
    )
    failed_runs = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user.id, AgentRun.status == "FAILED")
        .order_by(AgentRun.created_at.desc())
        .limit(5)
        .all()
    )
    failed_workflows = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.user_id == user.id, WorkflowRun.status == "FAILED")
        .order_by(WorkflowRun.created_at.desc())
        .limit(5)
        .all()
    )

    instance = manager.get_current()
    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "system": {
            "status": "ok",
            "user": user.username,
            "model_root_records": len(models),
            "ready_models": len(ready_models),
            "datasets": db.query(Dataset).filter(Dataset.user_id == user.id).count(),
            "knowledge_documents": db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == user.id).count(),
            "knowledge_bases": len(knowledge_bases),
            "workflows": db.query(Workflow).filter(Workflow.user_id == user.id).count(),
            "messages": (
                db.query(Message)
                .join(Session, Session.id == Message.session_id)
                .filter(Session.user_id == user.id)
                .count()
            ),
        },
        "runtime": {
            "active": instance is not None,
            "instance": instance.to_dict() if instance is not None else None,
            "instances": manager.instances_payload(),
            "queue": manager.queue_snapshot(),
            "loaded_count": len(manager.list_loaded()),
            "max_instances": manager.max_instances,
        },
        "resources": get_resource_manager().status(),
        "loaded_models": [
            {"model_id": item.model_id, "name": item.model_name, "runtime": item.runtime_type, "status": item.status}
            for item in manager.list_loaded()
        ],
        "recent_chats": [
            {"session_id": row.id, "title": row.title, "updated_at": _iso(row.updated_at)} for row in sessions
        ],
        "recent_agent_runs": [
            {
                "run_id": row.run_id,
                "agent_id": row.agent_id,
                "status": row.status,
                "created_at": _iso(row.created_at),
            }
            for row in agent_runs
        ],
        "training_tasks": [
            {
                "task_id": row.task_id,
                "base_model": row.base_model,
                "status": row.status,
                "progress": round(row.progress or 0, 1),
            }
            for row in training
        ],
        "knowledge_bases": [
            {"knowledge_id": row.id, "name": row.name} for row in knowledge_bases
        ],
        "workflows": [
            {"workflow_id": row.id, "name": row.name, "version": row.version} for row in workflows
        ],
        "errors": {
            "tasks": [
                {"task_id": row.task_id, "title": row.title, "error": row.error_code or row.status}
                for row in failed_tasks
            ],
            "agent_runs": [
                {"run_id": row.run_id, "agent_id": row.agent_id, "error": row.error} for row in failed_runs
            ],
            "workflow_runs": [
                {"run_id": row.id, "workflow_id": row.workflow_id, "error": row.error}
                for row in failed_workflows
            ],
        },
        "task_summary": {
            "total": db.query(TaskRecord).filter(TaskRecord.user_id == user.id).count(),
            "failed": db.query(TaskRecord)
            .filter(TaskRecord.user_id == user.id, TaskRecord.status == "FAILED")
            .count(),
            "active": db.query(TaskRecord)
            .filter(TaskRecord.user_id == user.id, TaskRecord.status.in_(("QUEUED", "RUNNING", "PAUSED")))
            .count(),
        },
        "ready_statuses": sorted(READY_STATUSES),
    }


@router.get("/events")
def unified_events(
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One feed across model runtime, agent, workflow and task events."""
    events: list[dict] = []

    def allowed(name: str) -> bool:
        return kind in (None, "", name)

    if allowed("agent"):
        rows = (
            db.query(AgentEventRecord, AgentRun.agent_id)
            .join(AgentRun, AgentRun.run_id == AgentEventRecord.run_id)
            .filter(AgentRun.user_id == user.id)
            .order_by(AgentEventRecord.timestamp.desc())
            .limit(limit)
            .all()
        )
        for row, agent_id in rows:
            events.append(
                {
                    "kind": "agent",
                    "type": row.event_type,
                    "timestamp": _iso(row.timestamp),
                    "subject": {"run_id": row.run_id, "agent_id": agent_id},
                    "payload": _safe_json(row.payload),
                }
            )
    if allowed("workflow"):
        rows = (
            db.query(WorkflowRunEvent, WorkflowRun.workflow_id)
            .join(WorkflowRun, WorkflowRun.id == WorkflowRunEvent.run_id)
            .filter(WorkflowRun.user_id == user.id)
            .order_by(WorkflowRunEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        for row, workflow_id in rows:
            events.append(
                {
                    "kind": "workflow",
                    "type": row.event_type,
                    "timestamp": _iso(row.created_at),
                    "subject": {"run_id": row.run_id, "workflow_id": workflow_id, "sequence": row.sequence},
                    "payload": _safe_json(row.payload_json),
                }
            )
    if allowed("task"):
        rows = (
            db.query(TaskEvent)
            .filter(TaskEvent.user_id == user.id)
            .order_by(TaskEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            events.append(
                {
                    "kind": "task",
                    "type": row.event_type,
                    "timestamp": _iso(row.created_at),
                    "subject": {"task_id": row.task_id, "version": row.version},
                    "payload": _safe_json(row.payload),
                }
            )
    if allowed("runtime"):
        manager = get_model_runtime_manager()
        for event in manager.recent_events(limit):
            events.append(
                {
                    "kind": "runtime",
                    "type": event.get("event"),
                    "timestamp": event.get("at"),
                    "subject": {"model_id": event.get("model_id")},
                    "payload": {key: value for key, value in event.items() if key not in {"event", "at"}},
                }
            )
    events.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return {"events": events[:limit], "kinds": ["runtime", "agent", "workflow", "task"]}


def _safe_json(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
