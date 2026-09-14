"""Multi-Agent Team orchestration service (V3.1).

The first V3.1 implementation intentionally uses the existing Agent Runtime and
Task OS instead of inventing a second executor. Team runs create auditable task
records, persist team trace events, and delegate member work as normal Agent
runs so model access remains routed through the unified Runtime layer.
"""

from __future__ import annotations

import datetime
import json
import uuid

from models.records import (
    AgentDelegation,
    AgentTeam,
    AgentTeamEvent,
    AgentTeamMember,
    AgentTeamMessage,
    AgentTeamRun,
    AgentTeamTask,
)
from services.agent_run_service import AgentRunService
from services.agent_service import AgentService, AgentServiceError
from services.task_service import TaskConflict, TaskService

TEAM_ROLES = {"MANAGER", "RESEARCHER", "CODER", "TESTER", "REVIEWER", "WRITER", "SPECIALIST"}
TEAM_STRATEGIES = {"SEQUENTIAL", "PARALLEL", "PIPELINE", "HIERARCHICAL", "DELEGATION", "CONSENSUS"}
MESSAGE_TYPES = {"REQUEST", "RESPONSE", "RESULT", "ERROR", "STATUS", "HANDOFF", "CANCEL"}
TERMINAL_TASK_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


class AgentTeamError(ValueError):
    """Stable team-service error mapped by the API layer."""

    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


class AgentTeamService:
    """CRUD and run orchestration for Agent Teams."""

    def __init__(self, db, *, agent_service: AgentService | None = None, run_service: AgentRunService | None = None):
        self.db = db
        self.agent_service = agent_service or AgentService(db)
        self.run_service = run_service or AgentRunService(db)
        self.task_service = TaskService()

    # -- teams -------------------------------------------------------------

    def list(self, user_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = (
            self.db.query(AgentTeam)
            .filter(AgentTeam.user_id == user_id)
            .order_by(AgentTeam.created_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [self._team_payload(row) for row in rows]

    def require_team(self, team_id: str, user_id: int) -> AgentTeam:
        row = self.db.query(AgentTeam).filter(AgentTeam.id == team_id, AgentTeam.user_id == user_id).first()
        if row is None:
            raise AgentTeamError("AGENT_TEAM_NOT_FOUND", "Agent team not found.", {"team_id": team_id}, 404)
        return row

    def create_team(self, user_id: int, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise AgentTeamError("AGENT_TEAM_NAME_REQUIRED", "Team name is required.")
        manager_agent_id = str(payload.get("manager_agent_id") or "").strip()
        if not manager_agent_id:
            raise AgentTeamError("TEAM_MANAGER_REQUIRED", "manager_agent_id is required.")
        self._require_agent(manager_agent_id, user_id)
        strategy = self._strategy(payload.get("strategy"))
        members = payload.get("members") or []
        normalized_members = self._normalize_members(user_id, manager_agent_id, members)

        existing = self.db.query(AgentTeam).filter(AgentTeam.user_id == user_id, AgentTeam.name == name).first()
        if existing is not None:
            raise AgentTeamError("AGENT_TEAM_NAME_TAKEN", "Team name is already in use.", {"name": name}, 409)

        team = AgentTeam(
            id=uuid.uuid4().hex,
            user_id=user_id,
            name=name,
            description=payload.get("description"),
            manager_agent_id=manager_agent_id,
            strategy=strategy,
            max_concurrency=max(1, min(int(payload.get("max_concurrency") or 1), 32)),
            timeout=payload.get("timeout"),
            retry_policy=json.dumps(payload.get("retry_policy") or {}, ensure_ascii=False),
            shared_memory_id=payload.get("shared_memory_id"),
            permission_policy_id=payload.get("permission_policy_id"),
        )
        self.db.add(team)
        self.db.flush()
        for member in normalized_members:
            self.db.add(
                AgentTeamMember(
                    id=uuid.uuid4().hex,
                    team_id=team.id,
                    user_id=user_id,
                    agent_id=member["agent_id"],
                    role=member["role"],
                    config_json=json.dumps(member.get("config") or {}, ensure_ascii=False),
                )
            )
        self.db.commit()
        self.db.refresh(team)
        return self._team_payload(team)

    def get_team(self, user_id: int, team_id: str) -> dict:
        return self._team_payload(self.require_team(team_id, user_id))

    # -- runs --------------------------------------------------------------

    def create_run(self, user_id: int, team_id: str, payload: dict) -> dict:
        team = self.require_team(team_id, user_id)
        input_text = str(payload.get("input") or "").strip()
        if not input_text:
            raise AgentTeamError("TEAM_RUN_INPUT_REQUIRED", "Team run input is required.")

        task = self.task_service.create(
            self.db,
            user_id=user_id,
            task_type="agent_team_run",
            source="agent_team",
            title=f"Agent Team: {team.name}",
            summary=input_text[:2000],
            metadata={"team_id": team.id, "manager_agent_id": team.manager_agent_id, "strategy": team.strategy},
            cancelable=True,
            retryable=True,
            priority=str(payload.get("priority") or "normal"),
            idempotency_key=payload.get("idempotency_key"),
        )

        now = datetime.datetime.utcnow()
        run = AgentTeamRun(
            id=uuid.uuid4().hex,
            team_id=team.id,
            user_id=user_id,
            manager_agent_id=team.manager_agent_id,
            task_id=task.task_id,
            status="RUNNING" if payload.get("execute", True) else "PENDING",
            input=input_text,
            started_at=now if payload.get("execute", True) else None,
        )
        self.db.add(run)
        self.db.flush()
        self._event(team.id, run.id, "team.started", {"team_id": team.id, "task_id": task.task_id})
        self._message(team.id, run.id, None, "user", team.manager_agent_id, "REQUEST", {"input": input_text})

        member_tasks = self._build_team_tasks(team, run, user_id, input_text)
        execute = bool(payload.get("execute", True))
        if execute:
            self._execute_sequential(run, member_tasks, user_id)
            run.status = "COMPLETED" if all(task.status == "COMPLETED" for task in member_tasks) else "FAILED"
            run.finished_at = datetime.datetime.utcnow()
            result = {
                "strategy": team.strategy,
                "tasks": [task.to_dict() for task in member_tasks],
                "final_result": member_tasks[-1].output if member_tasks else None,
            }
            run.result_json = json.dumps(result, ensure_ascii=False)
            self._event(team.id, run.id, "team.completed" if run.status == "COMPLETED" else "team.failed", result)
            try:
                self.task_service.transition(
                    self.db,
                    task,
                    "SUCCEEDED" if run.status == "COMPLETED" else "FAILED",
                    result={"team_run_id": run.id, "status": run.status},
                    summary="Team run completed." if run.status == "COMPLETED" else "Team run failed.",
                )
            except TaskConflict:
                pass
        self.db.commit()
        return self.get_run(user_id, run.id)

    def get_run(self, user_id: int, run_id: str) -> dict:
        run = self._require_run(run_id, user_id)
        tasks = (
            self.db.query(AgentTeamTask)
            .filter(AgentTeamTask.run_id == run_id, AgentTeamTask.user_id == user_id)
            .order_by(AgentTeamTask.sequence.asc())
            .all()
        )
        payload = run.to_dict()
        payload["tasks"] = [task.to_dict() for task in tasks]
        return payload

    def trace(self, user_id: int, run_id: str) -> dict:
        run = self._require_run(run_id, user_id)
        events = (
            self.db.query(AgentTeamEvent)
            .filter(AgentTeamEvent.run_id == run.id)
            .order_by(AgentTeamEvent.sequence.asc())
            .all()
        )
        messages = (
            self.db.query(AgentTeamMessage)
            .filter(AgentTeamMessage.run_id == run.id)
            .order_by(AgentTeamMessage.created_at.asc(), AgentTeamMessage.id.asc())
            .all()
        )
        return {
            "run": run.to_dict(),
            "events": [event.to_dict() for event in events],
            "messages": [message.to_dict() for message in messages],
        }

    # -- delegation --------------------------------------------------------

    def delegate(self, user_id: int, manager_agent_id: str, payload: dict) -> dict:
        self._require_agent(manager_agent_id, user_id)
        delegate_agent_id = str(payload.get("delegate_agent_id") or payload.get("to_agent_id") or "").strip()
        if not delegate_agent_id:
            raise AgentTeamError("DELEGATE_AGENT_REQUIRED", "delegate_agent_id is required.")
        self._require_agent(delegate_agent_id, user_id)
        instruction = str(payload.get("instruction") or payload.get("input") or "").strip()
        if not instruction:
            raise AgentTeamError("DELEGATION_INSTRUCTION_REQUIRED", "Delegation instruction is required.")

        team_id = payload.get("team_id")
        if team_id:
            self.require_team(str(team_id), user_id)

        task = self.task_service.create(
            self.db,
            user_id=user_id,
            task_type="agent_delegation",
            source="agent_team",
            title=f"Delegation: {manager_agent_id} -> {delegate_agent_id}",
            summary=instruction[:2000],
            metadata={"manager_agent_id": manager_agent_id, "delegate_agent_id": delegate_agent_id, "team_id": team_id},
            cancelable=True,
            retryable=True,
            priority=str(payload.get("priority") or "normal"),
        )
        team_task = None
        if team_id:
            run = AgentTeamRun(
                id=uuid.uuid4().hex,
                team_id=str(team_id),
                user_id=user_id,
                manager_agent_id=manager_agent_id,
                task_id=task.task_id,
                status="RUNNING",
                input=instruction,
                started_at=datetime.datetime.utcnow(),
            )
            self.db.add(run)
            self.db.flush()
            team_task = AgentTeamTask(
                id=uuid.uuid4().hex,
                team_id=str(team_id),
                run_id=run.id,
                user_id=user_id,
                task_record_id=task.task_id,
                agent_id=delegate_agent_id,
                role="SPECIALIST",
                status="PENDING",
                input=instruction,
                sequence=1,
            )
            self.db.add(team_task)
            self.db.flush()
        delegation = AgentDelegation(
            id=uuid.uuid4().hex,
            user_id=user_id,
            manager_agent_id=manager_agent_id,
            delegate_agent_id=delegate_agent_id,
            team_id=str(team_id) if team_id else None,
            team_task_id=team_task.id if team_task else None,
            status="PENDING",
            instruction=instruction,
        )
        self.db.add(delegation)
        self.db.commit()
        return {"task": task.to_dict(), "delegation": delegation.to_dict()}

    def get_team_task(self, user_id: int, task_id: str) -> dict:
        row = self.db.query(AgentTeamTask).filter(AgentTeamTask.id == task_id, AgentTeamTask.user_id == user_id).first()
        if row is None:
            task_record = self.task_service.get(self.db, task_id, user_id)
            if task_record is None:
                raise AgentTeamError("AGENT_TASK_NOT_FOUND", "Agent task not found.", {"task_id": task_id}, 404)
            return task_record.to_dict()
        return row.to_dict()

    def cancel_team_task(self, user_id: int, task_id: str) -> dict:
        row = self.db.query(AgentTeamTask).filter(AgentTeamTask.id == task_id, AgentTeamTask.user_id == user_id).first()
        if row is None:
            task_record = self.task_service.get(self.db, task_id, user_id)
            if task_record is None:
                raise AgentTeamError("AGENT_TASK_NOT_FOUND", "Agent task not found.", {"task_id": task_id}, 404)
            try:
                cancelled = self.task_service.transition(self.db, task_record, "CANCELLED", summary="Agent task cancelled.")
            except TaskConflict as exc:
                raise AgentTeamError("AGENT_TASK_CANCEL_REJECTED", "Agent task cannot be cancelled.", http_status=409) from exc
            self.db.commit()
            return cancelled.to_dict()
        if row.status in TERMINAL_TASK_STATUSES:
            raise AgentTeamError("AGENT_TASK_ALREADY_TERMINAL", "Agent task is already terminal.", http_status=409)
        row.status = "CANCELLED"
        row.finished_at = datetime.datetime.utcnow()
        self._event(row.team_id, row.run_id, "task.cancelled", {"task_id": row.id, "agent_id": row.agent_id})
        self._message(row.team_id, row.run_id, row.id, row.agent_id, row.agent_id, "CANCEL", {"task_id": row.id})
        self.db.commit()
        return row.to_dict()

    # -- internals ---------------------------------------------------------

    def _team_payload(self, team: AgentTeam) -> dict:
        members = (
            self.db.query(AgentTeamMember)
            .filter(AgentTeamMember.team_id == team.id, AgentTeamMember.user_id == team.user_id)
            .order_by(AgentTeamMember.created_at.asc())
            .all()
        )
        payload = team.to_dict()
        payload["members"] = [member.to_dict() for member in members]
        return payload

    def _build_team_tasks(self, team: AgentTeam, run: AgentTeamRun, user_id: int, input_text: str) -> list[AgentTeamTask]:
        members = (
            self.db.query(AgentTeamMember)
            .filter(AgentTeamMember.team_id == team.id, AgentTeamMember.user_id == user_id)
            .order_by(AgentTeamMember.created_at.asc())
            .all()
        )
        tasks: list[AgentTeamTask] = []
        for index, member in enumerate(members, start=1):
            if member.role == "MANAGER":
                continue
            task = AgentTeamTask(
                id=uuid.uuid4().hex,
                team_id=team.id,
                run_id=run.id,
                user_id=user_id,
                task_record_id=run.task_id,
                agent_id=member.agent_id,
                role=member.role,
                status="PENDING",
                input=input_text,
                sequence=index,
            )
            self.db.add(task)
            self.db.flush()
            tasks.append(task)
            self._event(team.id, run.id, "task.created", task.to_dict())
        return tasks

    def _execute_sequential(self, run: AgentTeamRun, tasks: list[AgentTeamTask], user_id: int) -> None:
        context = run.input or ""
        for task in tasks:
            task.status = "RUNNING"
            task.started_at = datetime.datetime.utcnow()
            self._event(task.team_id, task.run_id, "task.started", task.to_dict())
            self._message(task.team_id, task.run_id, task.id, run.manager_agent_id, task.agent_id, "REQUEST", {"input": context})
            try:
                agent_run = self.run_service.create_run(
                    agent_id=task.agent_id,
                    input_text=context,
                    user_id=user_id,
                    metadata={"team_id": task.team_id, "team_run_id": task.run_id, "team_task_id": task.id, "role": task.role},
                    execute=True,
                )
                task.output = json.dumps(agent_run, ensure_ascii=False)
                task.status = "COMPLETED"
                task.finished_at = datetime.datetime.utcnow()
                context = task.output
                self._message(task.team_id, task.run_id, task.id, task.agent_id, run.manager_agent_id, "RESULT", agent_run)
                self._event(task.team_id, task.run_id, "task.completed", task.to_dict())
            except AgentServiceError as exc:
                task.status = "FAILED"
                task.error = exc.message
                task.finished_at = datetime.datetime.utcnow()
                self._message(task.team_id, task.run_id, task.id, task.agent_id, run.manager_agent_id, "ERROR", {"code": exc.code, "message": exc.message})
                self._event(task.team_id, task.run_id, "task.failed", {"task": task.to_dict(), "code": exc.code})
                break

    def _normalize_members(self, user_id: int, manager_agent_id: str, members: list) -> list[dict]:
        normalized = [{"agent_id": manager_agent_id, "role": "MANAGER", "config": {}}]
        for item in members:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id") or "").strip()
            if not agent_id:
                continue
            self._require_agent(agent_id, user_id)
            role = str(item.get("role") or "SPECIALIST").strip().upper()
            if role not in TEAM_ROLES:
                raise AgentTeamError("TEAM_ROLE_UNSUPPORTED", "Unsupported team member role.", {"role": role})
            normalized.append({"agent_id": agent_id, "role": role, "config": item.get("config") or {}})
        return normalized

    def _strategy(self, value) -> str:
        strategy = str(value or "SEQUENTIAL").strip().upper()
        if strategy not in TEAM_STRATEGIES:
            raise AgentTeamError("TEAM_STRATEGY_UNSUPPORTED", "Unsupported team strategy.", {"strategy": strategy})
        return strategy

    def _require_agent(self, agent_id: str, user_id: int) -> None:
        try:
            self.agent_service.require(agent_id, user_id)
        except AgentServiceError as exc:
            raise AgentTeamError(exc.code, exc.message, exc.details, exc.http_status) from exc

    def _require_run(self, run_id: str, user_id: int) -> AgentTeamRun:
        row = self.db.query(AgentTeamRun).filter(AgentTeamRun.id == run_id, AgentTeamRun.user_id == user_id).first()
        if row is None:
            raise AgentTeamError("AGENT_TEAM_RUN_NOT_FOUND", "Agent team run not found.", {"run_id": run_id}, 404)
        return row

    def _event(self, team_id: str, run_id: str, event_type: str, payload: dict) -> AgentTeamEvent:
        current = self.db.query(AgentTeamEvent).filter(AgentTeamEvent.run_id == run_id).count()
        event = AgentTeamEvent(
            team_id=team_id,
            run_id=run_id,
            sequence=current + 1,
            event_type=event_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        self.db.add(event)
        return event

    def _message(
        self,
        team_id: str,
        run_id: str,
        task_id: str | None,
        from_agent_id: str | None,
        to_agent_id: str | None,
        message_type: str,
        content,
    ) -> AgentTeamMessage:
        message = AgentTeamMessage(
            message_id=uuid.uuid4().hex,
            team_id=team_id,
            run_id=run_id,
            task_id=task_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            message_type=message_type if message_type in MESSAGE_TYPES else "STATUS",
            content=json.dumps(content, ensure_ascii=False),
        )
        self.db.add(message)
        return message


__all__ = ["AgentTeamError", "AgentTeamService", "MESSAGE_TYPES", "TEAM_ROLES", "TEAM_STRATEGIES"]
