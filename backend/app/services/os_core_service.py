"""V4.0 unified OS projection service."""

from __future__ import annotations

import json
import uuid
from collections import Counter

from models.records import (
    AgentRecord,
    AgentRun,
    AgentSkill,
    AgentTeam,
    AgentTeamRun,
    EventRule,
    Goal,
    ModelRecord,
    OSEvent,
    OSProcess,
    OSResource,
    PlatformPackage,
    TaskRecord,
    ToolRecord,
    Workflow,
    WorkflowRun,
)


class OSCoreService:
    """Unified resource/process/event views layered over existing tables."""

    def __init__(self, db):
        self.db = db

    def resources(self, user_id: int, *, resource_type: str | None = None, limit: int = 200) -> list[dict]:
        items: list[dict] = []
        if resource_type in {None, "model"}:
            for row in self.db.query(ModelRecord).filter((ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))).limit(limit).all():
                items.append(_resource(str(row.id), "model", row.status, row.to_dict()))
        if resource_type in {None, "agent"}:
            for row in self.db.query(AgentRecord).filter(AgentRecord.user_id == user_id).limit(limit).all():
                items.append(_resource(row.name, "agent", row.status, row.to_dict()))
        if resource_type in {None, "team"}:
            for row in self.db.query(AgentTeam).filter(AgentTeam.user_id == user_id).limit(limit).all():
                items.append(_resource(row.id, "team", "active", row.to_dict()))
        if resource_type in {None, "workflow"}:
            for row in self.db.query(Workflow).filter(Workflow.user_id == user_id).limit(limit).all():
                items.append(_resource(row.id, "workflow", row.status, row.to_dict()))
        if resource_type in {None, "package"}:
            for row in self.db.query(PlatformPackage).filter((PlatformPackage.user_id == user_id) | (PlatformPackage.user_id.is_(None))).limit(limit).all():
                items.append(_resource(row.package_id, "package", "installed", row.to_dict()))
        if resource_type in {None, "tool"}:
            for row in self.db.query(ToolRecord).filter((ToolRecord.user_id == user_id) | (ToolRecord.user_id.is_(None))).limit(limit).all():
                items.append(_resource(row.name, "tool", "active" if row.enabled else "disabled", row.to_dict()))
        indexed = self.db.query(OSResource).filter((OSResource.user_id == user_id) | (OSResource.user_id.is_(None))).all()
        items.extend(item.to_dict() for item in indexed if resource_type in {None, item.resource_type})
        return items[: max(1, min(limit, 500))]

    def processes(self, user_id: int, *, status: str | None = None, limit: int = 200) -> list[dict]:
        items: list[dict] = []
        agent_query = self.db.query(AgentRun).filter(AgentRun.user_id == user_id)
        if status:
            agent_query = agent_query.filter(AgentRun.status == status)
        for row in agent_query.order_by(AgentRun.created_at.desc()).limit(limit).all():
            items.append(_process(row.run_id, "agent_run", row.status, row.agent_id, row.to_dict()))
        for row in self.db.query(AgentTeamRun).filter(AgentTeamRun.user_id == user_id).order_by(AgentTeamRun.created_at.desc()).limit(limit).all():
            if status and row.status != status:
                continue
            items.append(_process(row.id, "team_run", row.status, row.team_id, row.to_dict()))
        for row in self.db.query(WorkflowRun).filter(WorkflowRun.user_id == user_id).order_by(WorkflowRun.created_at.desc()).limit(limit).all():
            if status and row.status != status:
                continue
            items.append(_process(row.id, "workflow_run", row.status, row.workflow_id, row.to_dict()))
        for row in self.db.query(TaskRecord).filter(TaskRecord.user_id == user_id).order_by(TaskRecord.created_at.desc()).limit(limit).all():
            if status and row.status != status:
                continue
            items.append(_process(row.task_id, "task", row.status, row.source_task_id, row.to_dict()))
        for row in self.db.query(Goal).filter(Goal.user_id == user_id).order_by(Goal.created_at.desc()).limit(limit).all():
            if status and row.status != status:
                continue
            items.append(_process(row.id, "goal", row.status, row.agent_id, row.to_dict()))
        indexed = self.db.query(OSProcess).filter((OSProcess.user_id == user_id) | (OSProcess.user_id.is_(None))).all()
        items.extend(item.to_dict() for item in indexed if status is None or item.status == status)
        return items[: max(1, min(limit, 500))]

    def dashboard(self, user_id: int) -> dict:
        resources = self.resources(user_id, limit=500)
        processes = self.processes(user_id, limit=500)
        return {
            "resources": dict(Counter(item["type"] for item in resources)),
            "processes": dict(Counter(item["status"] for item in processes)),
            "active_agents": [item for item in resources if item["type"] == "agent" and item["status"] == "active"][:10],
            "running": [item for item in processes if item["status"] in {"RUNNING", "PENDING", "QUEUED"}][:20],
        }

    def events(self, user_id: int, *, event_type: str | None = None, limit: int = 100) -> list[dict]:
        query = self.db.query(OSEvent).filter((OSEvent.user_id == user_id) | (OSEvent.user_id.is_(None)))
        if event_type:
            query = query.filter(OSEvent.event_type == event_type)
        return [row.to_dict() for row in query.order_by(OSEvent.created_at.desc()).limit(max(1, min(limit, 500))).all()]

    def emit_event(self, user_id: int, event_type: str, subject_id: str | None, payload: dict | None = None) -> dict:
        event = OSEvent(id=uuid.uuid4().hex, user_id=user_id, event_type=event_type, subject_id=subject_id, payload_json=_dump(payload or {}))
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event.to_dict()

    def create_skill(self, user_id: int, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("SKILL_NAME_REQUIRED")
        skill = AgentSkill(
            id=uuid.uuid4().hex,
            user_id=user_id,
            name=name,
            description=payload.get("description"),
            tools_json=_dump(payload.get("tools") or []),
            prompt=payload.get("prompt"),
            knowledge_json=_dump(payload.get("knowledge") or []),
            workflow_id=payload.get("workflow_id"),
            evaluation_json=_dump(payload.get("evaluation") or {}),
        )
        self.db.add(skill)
        self.db.commit()
        self.db.refresh(skill)
        return skill.to_dict()

    def skills(self, user_id: int) -> list[dict]:
        return [row.to_dict() for row in self.db.query(AgentSkill).filter(AgentSkill.user_id == user_id).order_by(AgentSkill.created_at.desc()).all()]

    def rules(self, user_id: int) -> list[dict]:
        return [row.to_dict() for row in self.db.query(EventRule).filter(EventRule.user_id == user_id).order_by(EventRule.created_at.desc()).all()]


def _resource(resource_id: str, kind: str, status: str | None, metadata: dict) -> dict:
    return {"resource_id": resource_id, "type": kind, "owner": metadata.get("user_id"), "permissions": [], "status": status or "unknown", "metadata": metadata}


def _process(process_id: str, kind: str, status: str | None, resource_id: str | None, trace: dict) -> dict:
    return {"process_id": process_id, "type": kind, "status": status or "unknown", "priority": trace.get("priority", "normal"), "resource_id": resource_id, "runtime": trace.get("model") or trace.get("runtime"), "logs": [], "trace": trace}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["OSCoreService"]
