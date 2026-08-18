"""RunStore port adapter backed by SQLAlchemy (agent_runs table)."""
from __future__ import annotations

import builtins
import datetime
import json
from typing import Any

from core.database import SessionLocal
from models.records import AgentRun
from runtime.types import RunRecord, RunStatus


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


class SQLAlchemyRunStore:
    """Implements the runtime.RunStore protocol over SQLAlchemy (spec 30)."""

    def _to_record(self, row: AgentRun) -> RunRecord:
        return RunRecord(
            run_id=row.run_id,
            agent_id=row.agent_id,
            user_id=row.user_id,
            session_id=row.session_id,
            parent_run_id=row.parent_run_id,
            status=row.status or RunStatus.PENDING.value,
            input=row.input,
            output=row.output,
            model=row.model,
            error=row.error,
            token_usage=json.loads(row.token_usage) if row.token_usage else {},
            tool_call_count=row.tool_call_count or 0,
            iteration_count=row.iteration_count or 0,
            metadata=json.loads(row.meta) if row.meta else {},
            started_at=row.started_at,
            finished_at=row.finished_at,
            created_at=row.created_at,
        )

    def create(self, run: RunRecord) -> RunRecord:
        with SessionLocal() as db:
            row = AgentRun(
                run_id=run.run_id,
                agent_id=run.agent_id,
                user_id=run.user_id,
                session_id=run.session_id,
                parent_run_id=run.parent_run_id,
                status=run.status,
                input=run.input,
                output=run.output,
                model=run.model,
                error=run.error,
                token_usage=json.dumps(run.token_usage, ensure_ascii=False) if run.token_usage else None,
                tool_call_count=run.tool_call_count,
                iteration_count=run.iteration_count,
                meta=json.dumps(run.metadata, ensure_ascii=False) if run.metadata else None,
                started_at=run.started_at or _now(),
                created_at=run.created_at or _now(),
            )
            db.add(row)
            db.commit()
        return run

    def get(self, run_id: str) -> RunRecord | None:
        with SessionLocal() as db:
            row = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
            return self._to_record(row) if row else None

    def list(
        self, user_id: int | None = None, agent_id: str | None = None,
        status: str | None = None, parent_run_id: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> builtins.list[RunRecord]:
        with SessionLocal() as db:
            q = db.query(AgentRun)
            if user_id is not None:
                q = q.filter(AgentRun.user_id == user_id)
            if agent_id:
                q = q.filter(AgentRun.agent_id == agent_id)
            if status:
                q = q.filter(AgentRun.status == status)
            if parent_run_id:
                q = q.filter(AgentRun.parent_run_id == parent_run_id)
            rows = q.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit).all()
            return [self._to_record(r) for r in rows]

    def update(self, run_id: str, **fields: Any) -> RunRecord | None:
        with SessionLocal() as db:
            row = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
            if row is None:
                return None
            for key, value in fields.items():
                if key in ("token_usage", "metadata"):
                    value = json.dumps(value or {}, ensure_ascii=False)
                    if key == "token_usage":
                        row.token_usage = value
                    else:
                        row.meta = value
                elif key == "meta":
                    row.meta = json.dumps(value or {}, ensure_ascii=False) if value else None
                elif hasattr(row, key):
                    setattr(row, key, value)
            db.commit()
            db.refresh(row)
            return self._to_record(row)

    def delete_older_than(self, days: int) -> int:
        cutoff = _now() - datetime.timedelta(days=days)
        with SessionLocal() as db:
            n = db.query(AgentRun).filter(AgentRun.created_at < cutoff).delete()
            db.commit()
            return n