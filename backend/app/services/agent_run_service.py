"""Agent Run creation, lookup and trace assembly (V1.1)."""

from __future__ import annotations

from repositories.event_repository import SQLAlchemyEventStore
from repositories.run_repository import SQLAlchemyRunStore
from services.agent_service import AgentServiceError
from services.agent_trace import build_trace


class AgentRunService:
    """Thin, user-scoped facade over the Agent runtime's run store."""

    def __init__(self, db, runtime=None, run_store=None, event_store=None):
        self.db = db
        self._runtime = runtime
        self.run_store = run_store or SQLAlchemyRunStore()
        self.event_store = event_store or SQLAlchemyEventStore()

    @property
    def runtime(self):
        if self._runtime is not None:
            return self._runtime
        from services.agent_runtime_service import get_agent_runtime

        runtime = get_agent_runtime()
        if runtime is None:
            raise AgentServiceError(
                "AGENT_RUNTIME_UNAVAILABLE",
                "Agent runtime is not initialized.",
                http_status=503,
            )
        return runtime

    def create_run(
        self,
        *,
        agent_id: str,
        input_text: str,
        user_id: int,
        session_id: int | None = None,
        metadata: dict | None = None,
        execute: bool = True,
    ) -> dict:
        runtime = self.runtime
        if runtime.get_agent(agent_id, user_id=user_id) is None:
            raise AgentServiceError("AGENT_NOT_FOUND", "Agent not found.", {"agent_id": agent_id}, http_status=404)
        run = runtime.create_run(
            agent_id=agent_id,
            input_text=input_text,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
            execute=execute,
        )
        return {"run_id": run.run_id, "agent_id": run.agent_id, "status": run.status}

    def get_run(self, run_id: str, user_id: int) -> dict:
        run = self.run_store.get(run_id)
        if run is None or (run.user_id is not None and run.user_id != user_id):
            raise AgentServiceError("AGENT_RUN_NOT_FOUND", "Agent Run not found.", {"run_id": run_id}, http_status=404)
        return run.to_dict()

    def list_runs(
        self,
        user_id: int,
        *,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        runs = self.run_store.list(
            user_id=user_id, agent_id=agent_id, status=status, limit=limit, offset=offset
        )
        return [run.to_dict() for run in runs]

    def trace(self, run_id: str, user_id: int) -> dict:
        run = self.get_run(run_id, user_id)
        events = [event.to_dict() for event in self.event_store.list(run_id, limit=1000)]
        return build_trace(run, events)
