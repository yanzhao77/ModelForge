"""Agent experience learning service (V3.3)."""

from __future__ import annotations

import json
import uuid

from models.records import (
    AgentExperience,
    AgentRecord,
    ExperienceEvaluation,
    ExperienceOutcome,
    ExperienceStep,
)

OUTCOMES = {"SUCCESS", "FAILURE", "PARTIAL_SUCCESS"}


class AgentLearningError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


class AgentLearningService:
    """Records, reflects on and retrieves Agent experience."""

    def __init__(self, db):
        self.db = db

    def record(self, user_id: int, payload: dict) -> dict:
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise AgentLearningError("AGENT_ID_REQUIRED", "agent_id is required.")
        if self.db.query(AgentRecord.id).filter(AgentRecord.name == agent_id, AgentRecord.user_id == user_id).first() is None:
            raise AgentLearningError("AGENT_NOT_FOUND", "Agent not found.", {"agent_id": agent_id}, 404)
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise AgentLearningError("EXPERIENCE_GOAL_REQUIRED", "Experience goal is required.")
        outcome = str(payload.get("outcome") or "PARTIAL_SUCCESS").strip().upper()
        if outcome not in OUTCOMES:
            raise AgentLearningError("EXPERIENCE_OUTCOME_INVALID", "Unsupported experience outcome.", {"outcome": outcome})
        reflection = payload.get("reflection") or self.reflect(payload)
        experience = AgentExperience(
            id=uuid.uuid4().hex,
            user_id=user_id,
            agent_id=agent_id,
            task_id=payload.get("task_id"),
            goal=goal,
            context_json=_dump(payload.get("context") or {}),
            strategy_json=_dump(payload.get("strategy") or {}),
            steps_json=_dump(payload.get("steps") or []),
            tools_json=_dump(payload.get("tools") or []),
            result_json=_dump(payload.get("result")),
            outcome=outcome,
            score=payload.get("score"),
            failure_reason=payload.get("failure_reason"),
            reflection=reflection,
        )
        self.db.add(experience)
        self.db.flush()
        for index, step in enumerate(payload.get("steps") or [], start=1):
            if isinstance(step, dict):
                action = str(step.get("action") or step.get("name") or step)
                observation = step.get("observation")
            else:
                action = str(step)
                observation = None
            self.db.add(ExperienceStep(id=uuid.uuid4().hex, experience_id=experience.id, user_id=user_id, sequence=index, action=action, observation=observation))
        self.db.add(ExperienceOutcome(id=uuid.uuid4().hex, experience_id=experience.id, user_id=user_id, outcome=outcome, result_json=_dump(payload.get("result"))))
        metrics = payload.get("metrics") or self.metrics_for(payload)
        self.db.add(ExperienceEvaluation(id=uuid.uuid4().hex, experience_id=experience.id, user_id=user_id, metrics_json=_dump(metrics), human_rating=payload.get("human_rating")))
        self.db.commit()
        self.db.refresh(experience)
        return experience.to_dict()

    def list(self, user_id: int, *, agent_id: str | None = None, outcome: str | None = None, limit: int = 50) -> list[dict]:
        query = self.db.query(AgentExperience).filter(AgentExperience.user_id == user_id)
        if agent_id:
            query = query.filter(AgentExperience.agent_id == agent_id)
        if outcome:
            query = query.filter(AgentExperience.outcome == outcome.upper())
        rows = query.order_by(AgentExperience.created_at.desc()).limit(max(1, min(limit, 200))).all()
        return [row.to_dict() for row in rows]

    def recommend(self, user_id: int, *, agent_id: str, goal: str, limit: int = 5) -> dict:
        terms = {term.lower() for term in goal.split() if len(term) > 2}
        candidates = self.list(user_id, agent_id=agent_id, limit=100)
        ranked = []
        for item in candidates:
            haystack = " ".join([item.get("goal") or "", item.get("reflection") or "", item.get("failure_reason") or ""]).lower()
            overlap = sum(1 for term in terms if term in haystack)
            score = float(item.get("score") or 0) + overlap + (2 if item.get("outcome") == "SUCCESS" else 0)
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        recommendations = [item for _, item in ranked[: max(1, min(limit, 20))]]
        return {
            "agent_id": agent_id,
            "goal": goal,
            "recommendations": recommendations,
            "policy": {
                "allowed": ["experience_learning", "memory_learning", "strategy_recommendation"],
                "blocked": ["system_code_change", "permission_change", "package_publish", "core_prompt_change", "model_training"],
            },
        }

    def reflect(self, payload: dict) -> str:
        outcome = str(payload.get("outcome") or "PARTIAL_SUCCESS").upper()
        failure = payload.get("failure_reason") or "No failure reason recorded."
        tools = ", ".join(str(tool) for tool in (payload.get("tools") or [])) or "No tools recorded."
        worked = "The recorded strategy produced a usable result." if outcome in {"SUCCESS", "PARTIAL_SUCCESS"} else "No successful strategy was recorded."
        failed = failure if outcome == "FAILURE" else "No blocking failure recorded."
        change = "Prefer similar strategy for matching tasks." if outcome == "SUCCESS" else "Avoid repeating the failed step and request more context before execution."
        return f"What worked? {worked}\nWhat failed? {failed}\nWhy? Outcome={outcome}; tools={tools}.\nWhat should change? {change}\nWhat should be remembered? {payload.get('goal') or 'Task pattern.'}"

    def metrics_for(self, payload: dict) -> dict:
        outcome = str(payload.get("outcome") or "PARTIAL_SUCCESS").upper()
        return {
            "task_success_rate": 1.0 if outcome == "SUCCESS" else 0.0 if outcome == "FAILURE" else 0.5,
            "tool_success_rate": payload.get("tool_success_rate"),
            "quality_score": payload.get("score"),
            "latency": payload.get("latency"),
            "cost": payload.get("cost"),
            "error_rate": 1.0 if outcome == "FAILURE" else 0.0,
            "human_rating": payload.get("human_rating"),
        }


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["AgentLearningError", "AgentLearningService", "OUTCOMES"]
