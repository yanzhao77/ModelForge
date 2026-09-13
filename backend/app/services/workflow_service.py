"""Workflow persistence and execution service (V1.5).

The engine (``services/workflow_engine.py``) is pure interpreter logic; this
service owns the database rows, the durable per-run event stream, the
background execution task and the human-approval resume point.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import uuid

from core.api_contracts import problem
from core.database import SessionLocal
from models.records import Workflow, WorkflowRun, WorkflowRunEvent
from services.workflow_engine import (
    NodeState,
    WorkflowEngine,
    WorkflowError,
    WorkflowExecution,
    WorkflowPaused,
    new_run_id,
    validate_definition,
)

_ACTIVE_STATUSES = {"PENDING", "RUNNING", "WAITING_HUMAN"}


class WorkflowServiceError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status

    def to_problem(self, correlation: str | None = None):
        return problem(
            self.http_status,
            self.code,
            self.message,
            correlation=correlation,
            details=self.details or None,
        )


class WorkflowService:
    """CRUD + run management for workflows."""

    def __init__(self, db, *, engine_factory=None, run_executor=None):
        self.db = db
        self._engine_factory = engine_factory
        self._executor = run_executor

    # -- definitions --------------------------------------------------------

    def list(self, user_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = (
            self.db.query(Workflow)
            .filter(Workflow.user_id == user_id)
            .order_by(Workflow.updated_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [row.to_dict() for row in rows]

    def require(self, user_id: int, workflow_id: str) -> Workflow:
        row = (
            self.db.query(Workflow)
            .filter(Workflow.id == workflow_id, Workflow.user_id == user_id)
            .first()
        )
        if row is None:
            raise WorkflowServiceError(
                "WORKFLOW_NOT_FOUND",
                "Workflow not found.",
                {"workflow_id": workflow_id},
                http_status=404,
            )
        return row

    def get(self, user_id: int, workflow_id: str) -> dict:
        return self.require(user_id, workflow_id).to_dict()

    def create(self, user_id: int, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise WorkflowServiceError("WORKFLOW_NAME_REQUIRED", "Workflow name is required.")
        definition = payload.get("definition") or {}
        problems = validate_definition(definition)
        if problems:
            raise WorkflowServiceError(
                "WORKFLOW_DEFINITION_INVALID",
                "Workflow definition is invalid.",
                {"problems": problems},
            )
        row = Workflow(
            id=uuid.uuid4().hex[:32],
            user_id=user_id,
            name=name[:200],
            description=payload.get("description"),
            definition_json=json.dumps(definition, ensure_ascii=False),
            version=1,
            status=str(payload.get("status") or "active"),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row.to_dict()

    def update(self, user_id: int, workflow_id: str, payload: dict) -> dict:
        row = self.require(user_id, workflow_id)
        if payload.get("name") is not None:
            name = str(payload["name"]).strip()
            if not name:
                raise WorkflowServiceError("WORKFLOW_NAME_REQUIRED", "Workflow name is required.")
            row.name = name[:200]
        if payload.get("description") is not None:
            row.description = payload["description"]
        if payload.get("definition") is not None:
            problems = validate_definition(payload["definition"])
            if problems:
                raise WorkflowServiceError(
                    "WORKFLOW_DEFINITION_INVALID",
                    "Workflow definition is invalid.",
                    {"problems": problems},
                )
            row.definition_json = json.dumps(payload["definition"], ensure_ascii=False)
            row.version = int(row.version or 1) + 1
        if payload.get("status") is not None:
            row.status = str(payload["status"])
        self.db.commit()
        self.db.refresh(row)
        return row.to_dict()

    def delete(self, user_id: int, workflow_id: str) -> bool:
        row = self.require(user_id, workflow_id)
        run_ids = [
            run_id
            for (run_id,) in self.db.query(WorkflowRun.id).filter(WorkflowRun.workflow_id == workflow_id)
        ]
        if run_ids:
            self.db.query(WorkflowRunEvent).filter(WorkflowRunEvent.run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
            self.db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
        self.db.delete(row)
        self.db.commit()
        return True

    # -- runs ---------------------------------------------------------------

    def create_run(self, user_id: int, workflow_id: str, *, run_input: dict | None = None, execute: bool = True) -> dict:
        workflow = self.require(user_id, workflow_id)
        run_id = new_run_id()
        row = WorkflowRun(
            id=run_id,
            workflow_id=workflow.id,
            user_id=user_id,
            status="PENDING",
            input_json=json.dumps(run_input or {}, ensure_ascii=False),
            state_json=json.dumps({"variables": {"user_id": user_id}, "nodes": {}}, ensure_ascii=False),
        )
        self.db.add(row)
        self.db.commit()
        if execute:
            self._spawn(run_id, start_at=None)
        return {"run_id": run_id, "workflow_id": workflow.id, "status": row.status}

    def _spawn(self, run_id: str, *, start_at: str | None) -> None:
        """Schedule execution on a session owned by the background task.

        The request-scoped session that created the run is closed as soon as the
        HTTP response is sent, so the task must open its own.
        """
        if self._executor is not None:
            self._executor(run_id, start_at)
            return
        engine_factory = self._engine_factory

        async def runner() -> None:
            with SessionLocal() as session:
                service = WorkflowService(session, engine_factory=engine_factory)
                await service.execute_run(run_id, start_at=start_at)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            import threading

            threading.Thread(
                target=lambda: asyncio.run(runner()), daemon=True
            ).start()
        else:
            loop.create_task(runner())

    def _engine(self, run_id: str) -> WorkflowEngine:
        if self._engine_factory is not None:
            return self._engine_factory(run_id, self)

        async def emit(event_type: str, payload: dict) -> None:
            self._record_event(run_id, event_type, payload)
            self._assert_not_cancelled(run_id)

        return WorkflowEngine(emit=emit)

    async def execute_run(self, run_id: str, *, start_at: str | None = None) -> dict:
        run = self._load_run(run_id)
        if run is None:
            return {"run_id": run_id, "status": "MISSING"}
        workflow = self.db.get(Workflow, run.workflow_id)
        if workflow is None:
            self._finish(run_id, "FAILED", error="WORKFLOW_NOT_FOUND")
            return {"run_id": run_id, "status": "FAILED"}

        execution = self._build_execution(run, workflow)
        self._set_status(run_id, "RUNNING", started=True)
        self._record_event(run_id, "workflow.run.started", {"workflow_id": workflow.id, "start_at": start_at})
        engine = self._engine(run_id)
        try:
            await engine.execute(execution, start_at=start_at)
        except WorkflowPaused:
            self._persist_state(run_id, execution, status="WAITING_HUMAN")
            self._record_event(run_id, "workflow.run.waiting_human", {"node_id": execution.current_node})
            return {"run_id": run_id, "status": "WAITING_HUMAN"}
        except WorkflowError as exc:
            self._fail(run_id, execution, exc)
            return {"run_id": run_id, "status": "FAILED", "error": exc.code}
        except asyncio.CancelledError:
            self._persist_state(run_id, execution, status="CANCELLED")
            raise
        except Exception as exc:
            self._fail(
                run_id,
                execution,
                WorkflowError("WORKFLOW_RUN_FAILED", f"workflow failed: {type(exc).__name__}"),
            )
            del exc
            return {"run_id": run_id, "status": "FAILED"}
        self._persist_state(run_id, execution, status="COMPLETED")
        self._record_event(run_id, "workflow.run.completed", {"output": _preview(execution.output)})
        return {"run_id": run_id, "status": "COMPLETED", "output": execution.output}

    async def approve_run(self, user_id: int, run_id: str) -> dict:
        run = self._require_run(user_id, run_id)
        if run.status != "WAITING_HUMAN":
            raise WorkflowServiceError(
                "WORKFLOW_NOT_WAITING",
                "Workflow run is not waiting for approval.",
                {"run_id": run_id, "status": run.status},
                http_status=409,
            )
        state = json.loads(run.state_json or "{}")
        paused_node = state.get("current_node")
        workflow = self.db.get(Workflow, run.workflow_id)
        definition = workflow.definition() if workflow is not None else {}
        next_node = None
        for node in definition.get("nodes") or []:
            if isinstance(node, dict) and node.get("id") == paused_node:
                value = node.get("next")
                next_node = value[0] if isinstance(value, list) and value else value if isinstance(value, str) else None
                break
        self._record_event(run_id, "workflow.approval.granted", {"node_id": paused_node, "user_id": user_id})
        self._set_status(run_id, "RUNNING")
        if next_node:
            self._spawn(run_id, start_at=next_node)
            return {"run_id": run_id, "status": "RUNNING", "resumed_at": next_node}
        # Approval was the last step: finish the run as completed.
        self._set_status(run_id, "COMPLETED", finished=True)
        return {"run_id": run_id, "status": "COMPLETED"}

    def cancel_run(self, user_id: int, run_id: str) -> dict:
        run = self._require_run(user_id, run_id)
        if run.status not in _ACTIVE_STATUSES:
            return {"run_id": run_id, "status": run.status, "cancelled": False}
        self._record_event(run_id, "workflow.run.cancelled", {"user_id": user_id})
        self._set_status(run_id, "CANCELLED", finished=True)
        return {"run_id": run_id, "status": "CANCELLED", "cancelled": True}

    def get_run(self, user_id: int, run_id: str) -> dict:
        return self._require_run(user_id, run_id).to_dict()

    def list_runs(self, user_id: int, workflow_id: str | None = None, *, limit: int = 50) -> list[dict]:
        query = self.db.query(WorkflowRun).filter(WorkflowRun.user_id == user_id)
        if workflow_id:
            query = query.filter(WorkflowRun.workflow_id == workflow_id)
        rows = query.order_by(WorkflowRun.created_at.desc()).limit(max(1, min(limit, 200))).all()
        return [row.to_dict() for row in rows]

    def events(self, user_id: int, run_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[dict]:
        self._require_run(user_id, run_id)
        rows = (
            self.db.query(WorkflowRunEvent)
            .filter(WorkflowRunEvent.run_id == run_id, WorkflowRunEvent.sequence > int(after_sequence))
            .order_by(WorkflowRunEvent.sequence)
            .limit(max(1, min(limit, 2000)))
            .all()
        )
        return [row.to_dict() for row in rows]

    def trace(self, user_id: int, run_id: str) -> dict:
        from services.workflow_trace import build_workflow_trace

        run = self._require_run(user_id, run_id).to_dict()
        return build_workflow_trace(run, self.events(user_id, run_id, limit=2000))

    # -- internals ----------------------------------------------------------

    def _load_run(self, run_id: str) -> WorkflowRun | None:
        return self.db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()

    def _require_run(self, user_id: int, run_id: str) -> WorkflowRun:
        run = self._load_run(run_id)
        if run is None or run.user_id != user_id:
            raise WorkflowServiceError(
                "WORKFLOW_RUN_NOT_FOUND", "Workflow run not found.", {"run_id": run_id}, http_status=404
            )
        return run

    def _build_execution(self, run: WorkflowRun, workflow: Workflow) -> WorkflowExecution:
        try:
            state = json.loads(run.state_json or "{}")
        except (TypeError, ValueError):
            state = {}
        nodes = {
            node_id: NodeState(**payload)
            for node_id, payload in (state.get("nodes") or {}).items()
            if isinstance(payload, dict)
        }
        try:
            run_input = json.loads(run.input_json or "{}")
        except (TypeError, ValueError):
            run_input = {}
        return WorkflowExecution(
            run_id=run.id,
            definition=workflow.definition(),
            input=run_input if isinstance(run_input, dict) else {},
            variables=dict(state.get("variables") or {"user_id": run.user_id}),
            nodes=nodes,
            output=state.get("output"),
            current_node=state.get("current_node"),
        )

    def _persist_state(self, run_id: str, execution: WorkflowExecution, *, status: str) -> None:
        row = self._load_run(run_id)
        if row is None:
            return
        row.status = status
        row.state_json = json.dumps(execution.to_state(), ensure_ascii=False, default=str)
        row.output_json = json.dumps(execution.output, ensure_ascii=False, default=str)
        row.current_node = execution.current_node
        if status in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}:
            row.finished_at = datetime.datetime.utcnow()
        self.db.commit()

    def _set_status(self, run_id: str, status: str, *, started: bool = False, finished: bool = False) -> None:
        row = self._load_run(run_id)
        if row is None:
            return
        row.status = status
        if started and row.started_at is None:
            row.started_at = datetime.datetime.utcnow()
        if finished:
            row.finished_at = datetime.datetime.utcnow()
        self.db.commit()

    def _finish(self, run_id: str, status: str, *, error: str | None = None) -> None:
        row = self._load_run(run_id)
        if row is None:
            return
        row.status = status
        row.error = error
        row.finished_at = datetime.datetime.utcnow()
        self.db.commit()

    def _fail(self, run_id: str, execution: WorkflowExecution, error: WorkflowError) -> None:
        row = self._load_run(run_id)
        if row is None:
            return
        row.error = f"{error.code}: {error.message}"[:1000]
        self._persist_state(run_id, execution, status="FAILED")
        self._record_event(run_id, "workflow.run.failed", {"code": error.code, "message": error.message})

    def _record_event(self, run_id: str, event_type: str, payload: dict) -> None:
        """Append one durable event with a strictly increasing sequence."""
        try:
            with SessionLocal() as session:
                run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
                if run is None:
                    return
                last = (
                    session.query(WorkflowRunEvent.sequence)
                    .filter(WorkflowRunEvent.run_id == run_id)
                    .order_by(WorkflowRunEvent.sequence.desc())
                    .first()
                )
                sequence = (last[0] if last else 0) + 1
                session.add(
                    WorkflowRunEvent(
                        run_id=run_id,
                        sequence=sequence,
                        event_type=event_type,
                        payload_json=json.dumps(payload, ensure_ascii=False, default=str)[:8000],
                    )
                )
                session.commit()
        except Exception:
            # Event durability must never break the run itself.
            return

    def _assert_not_cancelled(self, run_id: str) -> None:
        row = self._load_run(run_id)
        if row is not None and row.status == "CANCELLED":
            raise WorkflowError("WORKFLOW_CANCELLED", "workflow run was cancelled")


def _preview(value, limit: int = 500):
    from services.workflow_engine import _preview as engine_preview

    return engine_preview(value, limit)
