"""E2E acceptance (spec 86): Create Agent -> Run -> Tool -> Event -> Complete.

Also covers the remaining spec-53 runtime-level cases: run failure, run
timeout, tool timeout, max_iterations, and concurrent runs (spec 58).
"""
import asyncio
import os
import sys
import tempfile
import time

_tmp_db = tempfile.mkdtemp(prefix="mf_e2e_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.models import MockProvider
from runtime.tools import Tool, ToolExecutor, ToolRegistry, ToolResult
from runtime.tools.builtin import register_builtin_tools
from runtime.types import AgentConfig


def build_runtime(provider_script=None, provider_factory=None, agent_cfg=None):
    from core.database import init_db
    from models.records import AgentRun  # noqa: F401
    from repositories.event_repository import SQLAlchemyEventStore
    from repositories.run_repository import SQLAlchemyRunStore
    from runtime.events import EventBus
    from runtime.runtime import AgentRuntime
    from services.agent_store import DBAgentStore
    init_db()
    registry = register_builtin_tools(ToolRegistry())
    if provider_factory is None:
        def provider_factory(m):
            return MockProvider(script=provider_script or [MockProvider.final("e2e answer")])
    rt = AgentRuntime(
        run_store=SQLAlchemyRunStore(),
        agent_store=DBAgentStore(engine=None),
        event_bus=EventBus(store=SQLAlchemyEventStore()),
        tool_registry=registry,
        tool_runner=ToolExecutor(registry),
        provider_factory=provider_factory,
    )
    cfg = agent_cfg or dict(name="e2ebot", model="mock", tools=["filesystem.read"])
    rt.create_agent(AgentConfig(**cfg))
    return rt


class SlowTool(Tool):
    name = "slow.tool"
    description = "sleeps"
    timeout = 0.05

    async def execute(self, arguments, context=None):
        await asyncio.sleep(1.0)
        return ToolResult.ok("slow done")


class TestE2E:
    @pytest.mark.asyncio
    async def test_full_acceptance_flow(self):
        """spec 86: Create Agent -> Select Model/Tools -> Create Run -> LLM ->
        Tool Call -> Tool Execution -> Event -> LLM -> Final Response -> Completed."""
        rt = build_runtime(provider_script=[
            MockProvider.tool_call("filesystem.read", {"filepath": "/etc/hostname"}),
            MockProvider.final("final answer"),
        ])
        run = rt.create_run(agent_id="e2ebot", input_text="read hostname", user_id=1, execute=False)
        task = asyncio.create_task(rt.execute_run(run.run_id))
        await task
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "final answer"
        assert stored.tool_call_count == 1
        assert stored.iteration_count == 2
        # every step persisted as an event with strictly increasing sequence
        events = rt.list_events(run.run_id, user_id=1)
        seqs = [e.sequence for e in events]
        assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
        types = [e.event_type for e in events]
        for required in ("run.created", "run.started", "model.request.started",
                         "tool.call.started", "tool.call.completed",
                         "model.request.completed", "run.completed"):
            assert required in types, f"missing event {required}"
        # trace: duration/input/output present on the run
        assert stored.started_at is not None
        assert stored.finished_at is not None

    @pytest.mark.asyncio
    async def test_run_failure(self):
        class BoomProvider:
            async def chat(self, messages, tools=None, timeout=None):
                raise RuntimeError("model exploded")
        rt = build_runtime(provider_factory=lambda m: BoomProvider())
        run = rt.create_run(agent_id="e2ebot", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "FAILED"
        assert "Model request failed" in (stored.error or "")
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "run.failed" for e in events)

    @pytest.mark.asyncio
    async def test_run_timeout(self):
        async def slow_provider(messages, tools=None, timeout=None):
            await asyncio.sleep(2.0)
            return MockProvider.final("late")
        rt = build_runtime(
            agent_cfg=dict(name="slowbot", model="mock", tools=[], runtime_config={"timeout_seconds": 1}),
            provider_factory=lambda m: MockProvider(callback=slow_provider),
        )
        run = rt.create_run(agent_id="slowbot", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_tool_timeout_in_run(self):
        rt = build_runtime(
            provider_script=[
                MockProvider.tool_call("slow.tool", {}),
                MockProvider.final("after timeout"),
            ],
            agent_cfg=dict(name="toolbot", model="mock", tools=["slow.tool"]),
        )
        rt.register_tool(SlowTool())
        run = rt.create_run(agent_id="toolbot", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        events = rt.list_events(run.run_id, user_id=1)
        failed = [e for e in events if e.event_type == "tool.call.failed"]
        assert len(failed) == 1
        assert (failed[0].payload.get("output") or "").startswith("Error:")

    @pytest.mark.asyncio
    async def test_max_iterations_in_run(self):
        rt = build_runtime(
            provider_factory=lambda m: MockProvider(
                callback=lambda msgs, tools, i: MockProvider.tool_call("t", {}),
            ),
            agent_cfg=dict(name="loopbot", model="mock", tools=["t"], runtime_config={"max_iterations": 3}),
        )
        run = rt.create_run(agent_id="loopbot", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "FAILED"
        assert "AGENT_LOOP_LIMIT" in (stored.error or "")

    @pytest.mark.asyncio
    async def test_concurrent_runs(self):
        """spec 58: multiple concurrent runs, no global current_run."""
        rt = build_runtime(provider_factory=lambda m: MockProvider(script=[MockProvider.final("c")]))
        r1 = rt.create_run(agent_id="e2ebot", input_text="a", user_id=1, execute=False)
        r2 = rt.create_run(agent_id="e2ebot", input_text="b", user_id=1, execute=False)
        r3 = rt.create_run(agent_id="e2ebot", input_text="c", user_id=1, execute=False)
        results = await asyncio.gather(
            rt.execute_run(r1.run_id), rt.execute_run(r2.run_id), rt.execute_run(r3.run_id),
        )
        assert all(r["status"] == "COMPLETED" for r in results)
        for rid in (r1.run_id, r2.run_id, r3.run_id):
            assert rt.get_run(rid).status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_live_event_stream(self):
        """Events are delivered live to subscribers while the run executes."""
        rt = build_runtime(provider_script=[MockProvider.final("live")])
        run = rt.create_run(agent_id="e2ebot", input_text="x", user_id=1, execute=False)
        live = []
        async def sub(event):
            live.append(event.event_type)
        rt.event_bus.subscribe(sub)
        try:
            await rt.execute_run(run.run_id)
        finally:
            rt.event_bus.unsubscribe(sub)
        assert "run.started" in live
        assert "run.completed" in live
        assert len(live) == len(set(live)), "no duplicates in live stream"

    def test_api_e2e(self):
        """Full API flow: agent -> run -> events (spec 86)."""
        from fastapi.testclient import TestClient
        from main import app
        from services.agent_runtime_service import get_agent_runtime
        with TestClient(app) as c:
            rt = get_agent_runtime()
            rt.provider_factory = lambda m: MockProvider(script=[
                MockProvider.tool_call("filesystem.read", {"filepath": "/etc/hostname"}),
                MockProvider.final("api e2e done"),
            ])
            c.post("/api/v1/auth/register", json={"username": "e2euser", "password": "secret123", "email": "e2euser@x.com"})
            h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", json={"username": "e2euser", "password": "secret123"}).json()["token"]}
            r = c.post("/api/v1/agent/create", json={"name": "e2e-api-bot", "model": "mock", "tools": ["filesystem.read"]}, headers=h)
            assert r.status_code == 200
            r = c.post("/api/v1/agent/runs", json={"agent_id": "e2e-api-bot", "input": "read"}, headers=h)
            run_id = r.json()["run_id"]
            status = None
            for _ in range(100):
                status = c.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()["status"]
                if status == "COMPLETED":
                    break
                time.sleep(0.02)
            assert status == "COMPLETED", status
            data = c.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()
            assert data["output"] == "api e2e done"
            assert data["tool_call_count"] == 1
            events = c.get(f"/api/v1/agent/runs/{run_id}/events", headers=h).json()["events"]
            types = [e["event_type"] for e in events]
            assert "tool.call.started" in types and "tool.call.completed" in types