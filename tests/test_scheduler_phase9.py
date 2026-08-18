"""Phase 9: Scheduler tests - schedule_once / schedule_interval / cancel (spec 72)."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.scheduler import Scheduler


class TestScheduler:
    @pytest.mark.asyncio
    async def test_schedule_once_fires(self):
        fired = []
        async def trigger(spec):
            fired.append(spec)
        sched = Scheduler(trigger=trigger)
        sched.start()
        job_id = sched.schedule_once(0.05, {"agent_id": "a", "input": "hi"})
        assert job_id.startswith("once_")
        await asyncio.sleep(0.2)
        assert len(fired) == 1
        assert fired[0]["agent_id"] == "a"
        jobs = sched.jobs()
        assert jobs[0]["status"] in ("scheduled",)
        await sched.stop()

    @pytest.mark.asyncio
    async def test_schedule_interval_fires_repeatedly(self):
        fired = []
        async def trigger(spec):
            fired.append(spec)
        sched = Scheduler(trigger=trigger)
        sched.start()
        sched.schedule_interval(0.05, {"agent_id": "b", "input": "tick"})
        await asyncio.sleep(0.22)
        assert len(fired) >= 3
        await sched.stop()

    @pytest.mark.asyncio
    async def test_cancel_prevents_fire(self):
        fired = []
        async def trigger(spec):
            fired.append(spec)
        sched = Scheduler(trigger=trigger)
        sched.start()
        job_id = sched.schedule_once(0.05, {"agent_id": "c", "input": "x"})
        assert sched.cancel(job_id) is True
        await asyncio.sleep(0.2)
        assert fired == []
        assert sched.cancel(job_id) is False
        jobs = sched.jobs()
        assert any(j["id"] == job_id and j["status"] == "cancelled" for j in jobs)
        await sched.stop()

    @pytest.mark.asyncio
    async def test_no_trigger_is_noop(self):
        sched = Scheduler()
        sched.start()
        sched.schedule_once(0.02, {"agent_id": "d", "input": "x"})
        await asyncio.sleep(0.1)
        assert sched.jobs()[0]["triggered_at"] is None
        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_pending(self):
        fired = []
        async def trigger(spec):
            fired.append(spec)
        sched = Scheduler(trigger=trigger)
        sched.start()
        sched.schedule_once(1.0, {"agent_id": "e", "input": "x"})
        await sched.stop()
        await asyncio.sleep(0.1)
        assert fired == []

    @pytest.mark.asyncio
    async def test_runtime_scheduler_creates_run(self):
        from core.database import init_db
        from models.records import AgentRun  # noqa: F401
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.models import MockProvider
        from runtime.runtime import AgentRuntime
        from runtime.scheduler import Scheduler
        from runtime.tools import ToolExecutor, ToolRegistry
        from runtime.tools.builtin import register_builtin_tools
        from runtime.types import AgentConfig
        from services.agent_store import DBAgentStore
        init_db()
        registry = register_builtin_tools(ToolRegistry())
        sched = Scheduler()
        rt = AgentRuntime(
            run_store=SQLAlchemyRunStore(),
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(),
            tool_registry=registry,
            tool_runner=ToolExecutor(registry),
            provider_factory=lambda m: MockProvider(script=[MockProvider.final("scheduled ok")]),
            scheduler=sched,
        )
        rt.create_agent(AgentConfig(name="schedbot", model="mock"))
        rt.start()
        rt.schedule_once(0.05, {"agent_id": "schedbot", "input": "scheduled task"})
        await asyncio.sleep(0.25)
        runs = rt.list_runs(user_id=None)
        assert any(r.agent_id == "schedbot" and r.status == "COMPLETED" for r in runs)
        assert rt.list_schedules()[0]["type"] == "once"
        await rt.shutdown()

    def test_schedules_api(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            c.post("/api/v1/auth/register", json={"username": "scheduser", "password": "secret123", "email": "scheduser@x.com"})
            h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", json={"username": "scheduser", "password": "secret123"}).json()["token"]}
            c.post("/api/v1/agent/create", json={"name": "sched-api-bot", "model": "mock"}, headers=h)
            r = c.post("/api/v1/agent/schedules", json={"agent_id": "sched-api-bot", "input": "x", "delay_seconds": 60}, headers=h)
            assert r.status_code == 200, r.text
            job_id = r.json()["job_id"]
            r = c.get("/api/v1/agent/schedules", headers=h)
            assert any(s["id"] == job_id for s in r.json()["schedules"])
            r = c.delete(f"/api/v1/agent/schedules/{job_id}", headers=h)
            assert r.status_code == 200
            r = c.post("/api/v1/agent/schedules", json={"agent_id": "sched-api-bot", "input": "x"}, headers=h)
            assert r.status_code == 400