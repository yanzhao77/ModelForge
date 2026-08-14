"""3.x-P5 tests: Multi-Agent guards (audit §12) - parent_run_id / depth / cycle / children / cancel / budget."""
import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

_tmp_db = tempfile.mkdtemp(prefix="mf_p5_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

from runtime.models import MockProvider
from runtime.tools import ToolExecutor, ToolRegistry
from runtime.tools.builtin import register_builtin_tools


def build_runtime(scripts, agent_cfgs):
    from models.records import AgentRun  # noqa: F401
    from core.database import init_db
    from repositories.event_repository import SQLAlchemyEventStore
    from repositories.run_repository import SQLAlchemyRunStore
    from runtime.events import EventBus
    from runtime.runtime import AgentRuntime
    from runtime.types import AgentConfig
    from services.agent_store import DBAgentStore
    init_db()
    registry = register_builtin_tools(ToolRegistry())
    def factory(model):
        return MockProvider(script=scripts.get(model, [MockProvider.final("default")]))
    rt = AgentRuntime(
        run_store=SQLAlchemyRunStore(),
        agent_store=DBAgentStore(engine=None),
        event_bus=EventBus(store=SQLAlchemyEventStore()),
        tool_registry=registry,
        tool_runner=ToolExecutor(registry),
        provider_factory=factory,
    )
    for cfg in agent_cfgs:
        rt.create_agent(AgentConfig(**cfg))
    return rt


def delegate(name, task):
    return MockProvider.tool_call("agent.delegate", {"agent_id": name, "task": task})


class TestMultiAgentGuards:
    @pytest.mark.asyncio
    async def test_child_run_records_parent(self):
        rt = build_runtime(
            {"p5helper": [MockProvider.final("h")], "p5boss": [delegate("p5helper", "t"), MockProvider.final("p5b")]},
            [dict(name="p5helper", model="p5helper", tools=["agent.delegate"]),
             dict(name="p5boss", model="p5boss", tools=["agent.delegate"])],
        )
        run = rt.create_run(agent_id="p5boss", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        children = rt.list_runs(user_id=1, agent_id="p5helper")
        assert len(children) == 1
        assert children[0].parent_run_id == run.run_id
        assert children[0].status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_indirect_cycle_detected(self):
        rt = build_runtime(
            {"p5a": [delegate("p5b", "t"), MockProvider.final("A done")],
             "p5b": [delegate("p5a", "t"), MockProvider.final("B done")]},
            [dict(name="p5a", model="p5a", tools=["agent.delegate"]),
             dict(name="p5b", model="p5b", tools=["agent.delegate"])],
        )
        run = rt.create_run(agent_id="p5a", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        runs = rt.list_runs(user_id=1)
        a_runs = [r for r in runs if r.agent_id == "p5a"]
        b_runs = [r for r in runs if r.agent_id == "p5b"]
        assert len(a_runs) == 1, "cycle must prevent a second A run"
        assert len(b_runs) == 1
        assert rt.get_run(run.run_id).status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_depth_limit(self):
        rt = build_runtime(
            {"d1": [delegate("d2", "t"), MockProvider.final("D1")],
             "d2": [delegate("d3", "t"), MockProvider.final("D2")],
             "d3": [MockProvider.final("D3")]},
            [dict(name="d1", model="d1", tools=["agent.delegate"], runtime_config={"delegation_max_depth": 1}),
             dict(name="d2", model="d2", tools=["agent.delegate"], runtime_config={"delegation_max_depth": 1}),
             dict(name="d3", model="d3", tools=[])],
        )
        run = rt.create_run(agent_id="d1", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        d3_runs = [r for r in rt.list_runs(user_id=1) if r.agent_id == "d3"]
        assert d3_runs == [], "depth limit must block the third level"

    @pytest.mark.asyncio
    async def test_child_count_limit(self):
        rt = build_runtime(
            {"p": [delegate("p5c1", "t"), delegate("p5c2", "t"), delegate("p5c3", "t"), MockProvider.final("P")],
             "p5c1": [MockProvider.final("1")], "p5c2": [MockProvider.final("2")], "p5c3": [MockProvider.final("3")]},
            [dict(name="p", model="p", tools=["agent.delegate"], runtime_config={"delegation_max_children": 2}),
             dict(name="p5c1", model="p5c1", tools=[]),
             dict(name="p5c2", model="p5c2", tools=[]),
             dict(name="p5c3", model="p5c3", tools=[])],
        )
        run = rt.create_run(agent_id="p", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        c_runs = [r for r in rt.list_runs(user_id=1) if r.agent_id in ("p5c1", "p5c2", "p5c3")]
        assert len(c_runs) == 2, "child count limit must block the third child"
    @pytest.mark.asyncio
    async def test_cancel_propagates_to_children(self):
        async def slow_provider(messages, tools=None, timeout=None):
            await asyncio.sleep(2.0)
            return MockProvider.final("slow")
        rt = build_runtime(
            {"p5boss2": [delegate("p5worker", "t"), MockProvider.final("B")]},
            [dict(name="p5boss2", model="p5boss2", tools=["agent.delegate"]),
             dict(name="p5worker", model="p5worker", tools=[])],
        )
        rt.provider_factory = lambda m: MockProvider(callback=slow_provider) if m == "p5worker" else MockProvider(script=[delegate("p5worker", "t"), MockProvider.final("B")])
        run = rt.create_run(agent_id="p5boss2", input_text="x", user_id=1, execute=False)
        task = asyncio.create_task(rt.execute_run(run.run_id))
        child = None
        for _ in range(100):
            children = rt.list_runs(user_id=1, agent_id="p5worker")
            if children:
                child = children[0]
                break
            await asyncio.sleep(0.02)
        assert child is not None, "child run should start"
        await rt.cancel_run(run.run_id, user_id=1)
        await task
        assert rt.get_run(run.run_id).status == "CANCELLED"
        assert rt.get_run(child.run_id).status == "CANCELLED", "cancellation must cascade"

    @pytest.mark.asyncio
    async def test_budget_timeout_propagates(self):
        async def slow_provider2(messages, tools=None, timeout=None):
            await asyncio.sleep(5.0)
            return MockProvider.final("late")
        rt = build_runtime(
            {"p5boss3": [delegate("p5slowchild", "t"), MockProvider.final("B3")]},
            [dict(name="p5boss3", model="p5boss3", tools=["agent.delegate"], runtime_config={"timeout_seconds": 2}),
             dict(name="p5slowchild", model="p5slowchild", tools=[], runtime_config={"timeout_seconds": 600})],
        )
        rt.provider_factory = lambda m: MockProvider(callback=slow_provider2) if m == "p5slowchild" else MockProvider(script=[delegate("p5slowchild", "t"), MockProvider.final("B3")])
        run = rt.create_run(agent_id="p5boss3", input_text="x", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        children = rt.list_runs(user_id=1, agent_id="p5slowchild")
        assert len(children) == 1
        assert children[0].status == "TIMEOUT", f"child status: {children[0].status}"

    def test_run_api_exposes_parent_run_id(self):
        from fastapi.testclient import TestClient
        from main import app
        from services.agent_runtime_service import get_agent_runtime
        with TestClient(app) as c:
            rt = get_agent_runtime()
            rt.provider_factory = lambda m: MockProvider(script=[MockProvider.final("x")])
            c.post("/api/v1/auth/register", json={"username": "p5user", "password": "secret123", "email": "p5user@x.com"})
            h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", json={"username": "p5user", "password": "secret123"}).json()["token"]}
            c.post("/api/v1/agent/create", json={"name": "p5bot", "model": "mock"}, headers=h)
            r = c.post("/api/v1/agent/runs", json={"agent_id": "p5bot", "input": "x"}, headers=h)
            run_id = r.json()["run_id"]
            data = c.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()
            assert "parent_run_id" in data
            assert data["parent_run_id"] is None