"""Schedules must be runnable on demand and deletable after they have run.

Two defects lived here: ``run-now`` called the keyword-only
``AgentRuntime.create_run`` positionally, so every manual run died with a
``TypeError`` behind a bare HTTP 500; and deleting a schedule removed the parent
row before its executions, so the FK constraint rejected the delete for any
schedule that had ever run.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import api.agent as agent_api  # noqa: E402
from core.database import Base  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from models.records import ScheduledJob, ScheduleExecution, User  # noqa: E402
from runtime.errors import AgentNotFoundError  # noqa: E402
from services.schedule_service import ScheduleService  # noqa: E402


def _session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _job_with_execution(db) -> ScheduledJob:
    user = User(username=f"probe_{os.urandom(4).hex()}", password_hash="x")
    db.add(user)
    db.commit()
    service = ScheduleService(db)
    job = service.create_draft(
        user.id,
        {
            "agent_id": "deep-agent",
            "schedule_kind": "interval",
            "interval_seconds": 3600,
            "input": "nightly",
        },
        commit=True,
    )
    service._append_execution(job, "failed", trigger_kind="manual", error=RuntimeError("boom"))
    db.commit()
    return job


def test_delete_schedule_removes_its_executions_first():
    db = _session()
    try:
        job = _job_with_execution(db)
        assert db.query(ScheduleExecution).filter_by(schedule_id=job.id).count() == 1

        ScheduleService(db).delete_desired(job, commit=True)

        assert db.query(ScheduledJob).filter_by(id=job.id).count() == 0
        assert db.query(ScheduleExecution).filter_by(schedule_id=job.id).count() == 0
    finally:
        db.close()


class _KeywordOnlyRuntime:
    """Mirrors ``AgentRuntime.create_run``'s keyword-only signature."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    def create_run(self, *, agent_id, input_text, user_id=None, session_id=None, parent_run_id=None, metadata=None, execute=True):
        self.calls.append({"agent_id": agent_id, "input_text": input_text, "execute": execute})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(run_id="run-1", status="QUEUED")


class _StubService:
    def __init__(self, _db):
        pass

    def owned(self, _user_id, schedule_id):
        return SimpleNamespace(
            id=schedule_id,
            run_spec=json.dumps({"agent_id": "deep-agent", "input": "nightly"}),
            runtime_job_id=None,
        )

    def claim_occurrence(self, _job, **_kwargs):
        return "run", None


def _run_now(monkeypatch, runtime) -> dict:
    monkeypatch.setattr(agent_api, "ScheduleService", _StubService)
    monkeypatch.setattr(agent_api, "_get_runtime", lambda: runtime)
    monkeypatch.setattr(agent_api, "record_operation", lambda *args, **kwargs: None)
    request = agent_api.ScheduleActionRequest(confirm=True)
    user = SimpleNamespace(id=1, username="qa-user")
    return asyncio.run(
        agent_api.run_schedule_now("schedule-1", idempotency_key=None, req=request, db=MagicMock(), user=user)
    )


def test_run_now_uses_the_keyword_only_runtime_api(monkeypatch):
    runtime = _KeywordOnlyRuntime()

    result = _run_now(monkeypatch, runtime)

    assert runtime.calls == [{"agent_id": "deep-agent", "input_text": "nightly", "execute": True}]
    assert result["run_id"] == "run-1"
    assert result["status"] == "QUEUED"


def test_run_now_reports_a_stable_code_when_the_runtime_fails(monkeypatch):
    runtime = _KeywordOnlyRuntime(RuntimeError("ollama is not running"))

    with pytest.raises(HTTPException) as raised:
        _run_now(monkeypatch, runtime)

    assert raised.value.status_code == 502
    assert raised.value.detail["code"] == "SCHEDULE_RUN_FAILED"
    assert raised.value.detail["correlation_id"]


def test_run_now_reports_a_missing_agent_as_404(monkeypatch):
    runtime = _KeywordOnlyRuntime(AgentNotFoundError("deep-agent"))

    with pytest.raises(HTTPException) as raised:
        _run_now(monkeypatch, runtime)

    assert raised.value.status_code == 404
    assert raised.value.detail["code"] == "AGENT_NOT_FOUND"
