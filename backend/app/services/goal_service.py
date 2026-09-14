"""Autonomous Goal and human approval service (V3.4)."""

from __future__ import annotations

import datetime
import json
import uuid

from models.records import AgentRecord, ApprovalDecision, ApprovalRequest, Goal, SubGoal

GOAL_STATUSES = {"CREATED", "PLANNED", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"}
RISKS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
DECISIONS = {"APPROVE", "REJECT", "MODIFY"}


class GoalServiceError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


class GoalService:
    """Persistent autonomous goals with approval boundaries."""

    def __init__(self, db):
        self.db = db

    def create(self, user_id: int, payload: dict) -> dict:
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise GoalServiceError("GOAL_AGENT_REQUIRED", "agent_id is required.")
        if self.db.query(AgentRecord.id).filter(AgentRecord.name == agent_id, AgentRecord.user_id == user_id).first() is None:
            raise GoalServiceError("AGENT_NOT_FOUND", "Agent not found.", {"agent_id": agent_id}, 404)
        title = str(payload.get("title") or "").strip()
        if not title:
            raise GoalServiceError("GOAL_TITLE_REQUIRED", "Goal title is required.")
        deadline = _parse_deadline(payload.get("deadline"))
        goal = Goal(
            id=uuid.uuid4().hex,
            user_id=user_id,
            agent_id=agent_id,
            title=title,
            description=payload.get("description"),
            priority=str(payload.get("priority") or "normal"),
            deadline=deadline,
            constraints_json=_dump(payload.get("constraints") or []),
            success_criteria_json=_dump(payload.get("success_criteria") or []),
            status="PLANNED" if payload.get("decompose", True) else "CREATED",
        )
        self.db.add(goal)
        self.db.flush()
        if payload.get("decompose", True):
            for index, item in enumerate(self.decompose(goal, payload), start=1):
                self.db.add(SubGoal(id=uuid.uuid4().hex, goal_id=goal.id, user_id=user_id, title=item["title"], objective=item["objective"], sequence=index))
        self.db.commit()
        self.db.refresh(goal)
        return self.get(user_id, goal.id)

    def list(self, user_id: int, *, status: str | None = None, limit: int = 100) -> list[dict]:
        query = self.db.query(Goal).filter(Goal.user_id == user_id)
        if status:
            query = query.filter(Goal.status == status.upper())
        rows = query.order_by(Goal.created_at.desc()).limit(max(1, min(limit, 200))).all()
        return [self._payload(row) for row in rows]

    def get(self, user_id: int, goal_id: str) -> dict:
        return self._payload(self._require_goal(user_id, goal_id))

    def transition(self, user_id: int, goal_id: str, status: str) -> dict:
        goal = self._require_goal(user_id, goal_id)
        target = status.upper()
        if target not in GOAL_STATUSES:
            raise GoalServiceError("GOAL_STATUS_INVALID", "Unsupported goal status.", {"status": status})
        goal.status = target
        goal.updated_at = datetime.datetime.utcnow()
        self.db.commit()
        return self.get(user_id, goal_id)

    def create_approval(self, user_id: int, payload: dict) -> dict:
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise GoalServiceError("APPROVAL_AGENT_REQUIRED", "agent_id is required.")
        risk = str(payload.get("risk") or "HIGH").strip().upper()
        if risk not in RISKS:
            raise GoalServiceError("APPROVAL_RISK_INVALID", "Unsupported approval risk.", {"risk": risk})
        goal_id = payload.get("goal_id")
        if goal_id:
            self._require_goal(user_id, str(goal_id))
        request = ApprovalRequest(
            id=uuid.uuid4().hex,
            user_id=user_id,
            goal_id=str(goal_id) if goal_id else None,
            agent_id=agent_id,
            action=str(payload.get("action") or "").strip() or "unspecified",
            risk=risk,
            details_json=_dump(payload.get("details") or {}),
            status="PENDING",
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request.to_dict()

    def decide_approval(self, user_id: int, approval_id: str, payload: dict) -> dict:
        request = self.db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id, ApprovalRequest.user_id == user_id).first()
        if request is None:
            raise GoalServiceError("APPROVAL_NOT_FOUND", "Approval request not found.", {"approval_id": approval_id}, 404)
        if request.status != "PENDING":
            raise GoalServiceError("APPROVAL_ALREADY_DECIDED", "Approval request is already decided.", http_status=409)
        decision = str(payload.get("decision") or "").strip().upper()
        if decision not in DECISIONS:
            raise GoalServiceError("APPROVAL_DECISION_INVALID", "Unsupported approval decision.", {"decision": decision})
        request.status = "APPROVED" if decision == "APPROVE" else "REJECTED" if decision == "REJECT" else "MODIFIED"
        request.decided_at = datetime.datetime.utcnow()
        row = ApprovalDecision(
            id=uuid.uuid4().hex,
            approval_id=request.id,
            user_id=user_id,
            decision=decision,
            modifications_json=_dump(payload.get("modifications") or {}),
            comment=payload.get("comment"),
        )
        self.db.add(row)
        self.db.commit()
        return {"approval": request.to_dict(), "decision": row.to_dict()}

    def decompose(self, goal: Goal, payload: dict) -> list[dict]:
        explicit = payload.get("sub_goals") or []
        if explicit:
            return [{"title": str(item.get("title") or f"Step {idx}"), "objective": str(item.get("objective") or item.get("title") or "")} for idx, item in enumerate(explicit, start=1) if isinstance(item, dict)]
        return [
            {"title": "Observe", "objective": "Gather current project, task and knowledge context."},
            {"title": "Plan", "objective": "Create an ordered task plan with dependencies and risk levels."},
            {"title": "Execute", "objective": "Run low-risk actions and request approval for high-risk actions."},
            {"title": "Evaluate", "objective": "Compare outputs against success criteria."},
            {"title": "Reflect", "objective": "Record reusable experience without changing system code or permissions."},
        ]

    def _payload(self, goal: Goal) -> dict:
        sub_goals = self.db.query(SubGoal).filter(SubGoal.goal_id == goal.id, SubGoal.user_id == goal.user_id).order_by(SubGoal.sequence.asc()).all()
        payload = goal.to_dict()
        payload["sub_goals"] = [item.to_dict() for item in sub_goals]
        return payload

    def _require_goal(self, user_id: int, goal_id: str) -> Goal:
        goal = self.db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user_id).first()
        if goal is None:
            raise GoalServiceError("GOAL_NOT_FOUND", "Goal not found.", {"goal_id": goal_id}, 404)
        return goal


def _parse_deadline(value) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise GoalServiceError("GOAL_DEADLINE_INVALID", "Deadline must be ISO-8601.") from exc
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["DECISIONS", "GOAL_STATUSES", "GoalService", "GoalServiceError", "RISKS"]
