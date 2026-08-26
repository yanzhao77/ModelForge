"""RunStore port adapter backed by SQLAlchemy (agent_runs table)."""
from __future__ import annotations

import builtins
import datetime
import json
from typing import Any

from core.database import SessionLocal
from models.records import AgentRun
from runtime.types import RunRecord, RunStatus
from sqlalchemy import update


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
            state_version=row.state_version or 1,
            executor_lease_id=row.executor_lease_id,
            lease_expires_at=row.lease_expires_at,
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
                state_version=run.state_version or 1,
                executor_lease_id=run.executor_lease_id,
                lease_expires_at=run.lease_expires_at,
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

    def claim_execution(self, run_id: str, *, lease_id: str, lease_seconds: float = 300.0) -> RunRecord | None:
        """Atomically claim a pending Run for one local executor.

        A failed claim is expected during duplicate callbacks, cancel races, or
        restart recovery; callers must read the latest row and must not execute
        the Run merely because a process-local set is empty.
        """
        now = _now()
        expiry = now + datetime.timedelta(seconds=max(1.0, lease_seconds))
        with SessionLocal() as db:
            row = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
            if row is None or row.status != RunStatus.PENDING.value:
                return None
            expected = row.state_version or 1
            result = db.execute(
                update(AgentRun)
                .where(
                    AgentRun.run_id == run_id,
                    AgentRun.status == RunStatus.PENDING.value,
                    AgentRun.state_version == expected,
                )
                .values(
                    status=RunStatus.RUNNING.value,
                    state_version=expected + 1,
                    executor_lease_id=lease_id,
                    lease_expires_at=expiry,
                    started_at=row.started_at or now,
                )
            )
            if result.rowcount != 1:
                db.rollback()
                return None
            db.commit()
            claimed = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
            return self._to_record(claimed) if claimed else None

    def compare_and_set(
        self,
        run_id: str,
        *,
        expected_version: int,
        to_status: str,
        lease_id: str | None = None,
        terminal: bool = False,
        **fields: Any,
    ) -> RunRecord | None:
        """Advance a Run only if its persisted version and optional lease match."""
        values: dict[str, Any] = {"status": to_status, "state_version": expected_version + 1, **fields}
        for key in ("token_usage", "metadata"):
            if key in values:
                value = json.dumps(values.pop(key) or {}, ensure_ascii=False)
                values["token_usage" if key == "token_usage" else "meta"] = value
        if terminal:
            values["finished_at"] = values.get("finished_at") or _now()
            values["executor_lease_id"] = None
            values["lease_expires_at"] = None
            values["terminal_event_key"] = f"terminal:{run_id}:{expected_version + 1}"
        with SessionLocal() as db:
            filters = [AgentRun.run_id == run_id, AgentRun.state_version == expected_version]
            if lease_id is not None:
                filters.append(AgentRun.executor_lease_id == lease_id)
            result = db.execute(update(AgentRun).where(*filters).values(**values))
            if result.rowcount != 1:
                db.rollback()
                return None
            db.commit()
            row = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
            return self._to_record(row) if row else None

    def cancel_with_cas(self, run_id: str) -> RunRecord | None:
        """Persist cancellation only if a non-terminal version is still current."""
        with SessionLocal() as db:
            row = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
            if row is None or row.status in RunStatus.terminal():
                return None
            expected = row.state_version or 1
        return self.compare_and_set(
            run_id,
            expected_version=expected,
            to_status=RunStatus.CANCELLED.value,
            terminal=True,
        )

    def delete_older_than(self, days: int) -> int:
        cutoff = _now() - datetime.timedelta(days=days)
        with SessionLocal() as db:
            n = db.query(AgentRun).filter(AgentRun.created_at < cutoff).delete()
            db.commit()
            return n
