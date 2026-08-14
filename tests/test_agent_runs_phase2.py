"""Phase 2: Agent Run tests - lifecycle, persistence, cancellation, API (spec 65)."""
import asyncio
import os
import sys
import tempfile
import time

# Isolate DB for this test session (imported before core.database is used)
_tmp_db = tempfile.mkdtemp(prefix="mf_run_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.cancellation import CancellationToken
from runtime.context import RunContext
from runtime.execution import ExecutionEngine
from runtime.models import MockProvider, ModelResult
from runtime.types import AgentConfig, RunRecord, RunStatus


class FakeToolRunner:
    """Deterministic tool runner for engine tests (spec 54: FakeTool)."""

    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.calls = []

    def names(self):
        return list(self.outputs)

    def schema(self, name):
        return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}

    async def run(self, name, arguments, ctx=None):
        self.calls.append((name, arguments))
        if name in self.outputs:
            return self.outputs[name]
        from runtime.errors import ToolNotFoundError
        raise ToolNotFoundError(name)


def make_ctx(**kw):
    defaults = dict(
        run_id="run1", agent_id="agent1", input_text="hello",
        tools=["file_read"], max_iterations=20, max_tool_calls=50,
        timeout_seconds=30, tool_timeout=5.0,
        cancellation=CancellationToken(),
    )
    defaults.update(kw)
    ctx = RunContext(**defaults)
    ctx.started_at = time.monotonic()
    return ctx


class TestExecutionEngine:
    @pytest.mark.asyncio
    async def test_success_no_tools(self):
        engine = ExecutionEngine(tool_runner=FakeToolRunner())
        provider = MockProvider(script=[MockProvider.final("hi there")])
        outcome = await engine.execute(make_ctx(tools=[]), provider)
        assert outcome["status"] == "COMPLETED"
        assert outcome["output"] == "hi there"
        assert outcome["iteration"] == 1

    @pytest.mark.asyncio
    async def test_tool_call_loop(self):
        runner = FakeToolRunner(outputs={"file_read": "file contents"})
        engine = ExecutionEngine(tool_runner=runner)
        provider = MockProvider(script=[
            MockProvider.tool_call("file_read", {"filepath": "/tmp/x"}),
            MockProvider.final("done"),
        ])
        outcome = await engine.execute(make_ctx(), provider)
        assert outcome["status"] == "COMPLETED"
        assert outcome["output"] == "done"
        assert runner.calls == [("file_read", {"filepath": "/tmp/x"})]
        assert outcome["tool_call_count"] == 1
        assert outcome["iteration"] == 2
        msgs = outcome["messages"]
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "file contents"
        # full trace: user -> assistant(toolcall) -> tool -> assistant(final)
        assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]

    @pytest.mark.asyncio
    async def test_tool_failure_continues(self):
        runner = FakeToolRunner(outputs={})
        engine = ExecutionEngine(tool_runner=runner)
        provider = MockProvider(script=[
            MockProvider.tool_call("missing_tool", {}),
            MockProvider.final("recovered"),
        ])
        outcome = await engine.execute(make_ctx(tools=["missing_tool"]), provider)
        assert outcome["status"] == "COMPLETED"
        assert "not found" in outcome["messages"][-2]["content"].lower()

    @pytest.mark.asyncio
    async def test_max_iterations(self):
        engine = ExecutionEngine(tool_runner=FakeToolRunner())
        provider = MockProvider(callback=lambda m, t, i: MockProvider.tool_call("t", {}))
        outcome = await engine.execute(make_ctx(max_iterations=3, tools=["t"]), provider)
        assert outcome["status"] == "FAILED"
        assert "AGENT_LOOP_LIMIT" in outcome["error"]

    @pytest.mark.asyncio
    async def test_max_tool_calls(self):
        engine = ExecutionEngine(tool_runner=FakeToolRunner())
        provider = MockProvider(callback=lambda m, t, i: MockProvider.tool_call("t", {}))
        outcome = await engine.execute(make_ctx(max_tool_calls=2, tools=["t"]), provider)
        assert outcome["status"] == "FAILED"
        assert "AGENT_TOOL_CALL_LIMIT" in outcome["error"]

    @pytest.mark.asyncio
    async def test_timeout(self):
        engine = ExecutionEngine(tool_runner=FakeToolRunner())
        provider = MockProvider(script=[MockProvider.final("x")])
        ctx = make_ctx(tools=[])
        ctx.timeout_seconds = 1
        ctx.started_at = time.monotonic() - 5  # already over budget
        outcome = await engine.execute(ctx, provider)
        assert outcome["status"] == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_cancel(self):
        engine = ExecutionEngine(tool_runner=FakeToolRunner())
        token = CancellationToken()
        provider = MockProvider(script=[MockProvider.final("x")])
        ctx = make_ctx(tools=[], cancellation=token)
        token.cancel()
        outcome = await engine.execute(ctx, provider)
        assert outcome["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_model_error_fails_run(self):
        class BoomProvider:
            async def chat(self, messages, tools=None, timeout=None):
                raise RuntimeError("llm down")
        engine = ExecutionEngine(tool_runner=FakeToolRunner())
        outcome = await engine.execute(make_ctx(tools=[]), BoomProvider())
        assert outcome["status"] == "FAILED"
        assert "Model request failed" in outcome["error"]


class TestAgentRuntime:
    @pytest.fixture(autouse=True)
    def _runtime(self):
        # import models FIRST so init_db() creates all tables
        from models.records import AgentRun  # noqa: F401
        from repositories.run_repository import SQLAlchemyRunStore
        from core.database import init_db
        init_db()
        from runtime.events import EventBus
        from runtime.runtime import AgentRuntime
        from services.agent_store import DBAgentStore
        store = SQLAlchemyRunStore()
        agent_store = DBAgentStore(engine=None)
        rt = AgentRuntime(
            run_store=store,
            agent_store=agent_store,
            event_bus=EventBus(),
            tool_runner=FakeToolRunner(outputs={"file_read": "content!"}),
            provider_factory=lambda m: MockProvider(script=[MockProvider.final("answer")]),
        )
        rt.create_agent(AgentConfig(name="bot", model="mock", tools=["file_read"]))
        rt.start()
        yield rt

    @pytest.mark.asyncio
    async def test_create_execute_query(self, _runtime):
        rt = _runtime
        run = rt.create_run(agent_id="bot", input_text="hi", user_id=1)
        assert run.status == "PENDING"
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "answer"
        assert stored.started_at is not None
        assert stored.finished_at is not None

    @pytest.mark.asyncio
    async def test_status_persisted(self, _runtime):
        rt = _runtime
        run = rt.create_run(agent_id="bot", input_text="hi", user_id=1)
        await rt.execute_run(run.run_id)
        row = rt.run_store.get(run.run_id)
        assert row.status == "COMPLETED"
        assert row.iteration_count >= 1

    @pytest.mark.asyncio
    async def test_cancel_pending_run(self, _runtime):
        rt = _runtime
        run = rt.create_run(agent_id="bot", input_text="hi", user_id=1, execute=False)
        cancelled = await rt.cancel_run(run.run_id, user_id=1)
        assert cancelled.status == "CANCELLED"
        # executing after cancel is a no-op
        out = await rt.execute_run(run.run_id)
        assert out["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_agent_not_found(self, _runtime):
        with pytest.raises(Exception) as ei:
            _runtime.create_run(agent_id="ghost", input_text="x")
        assert getattr(ei.value, "code", "") == "AGENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_run_not_found(self, _runtime):
        with pytest.raises(Exception) as ei:
            _runtime.get_run("nope", user_id=1)
        assert getattr(ei.value, "code", "") == "RUN_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_ownership_enforced(self, _runtime):
        rt = _runtime
        run = rt.create_run(agent_id="bot", input_text="hi", user_id=1)
        with pytest.raises(Exception) as ei:
            rt.get_run(run.run_id, user_id=999)
        assert getattr(ei.value, "code", "") == "RUN_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_list_runs(self, _runtime):
        rt = _runtime
        rt.create_run(agent_id="bot", input_text="a", user_id=1)
        rt.create_run(agent_id="bot", input_text="b", user_id=2)
        runs = rt.list_runs(user_id=1)
        assert len(runs) >= 1
        assert all(r.user_id == 1 for r in runs)

    @pytest.mark.asyncio
    async def test_metrics(self, _runtime):
        rt = _runtime
        run = rt.create_run(agent_id="bot", input_text="hi", user_id=1)
        await rt.execute_run(run.run_id)
        snap = rt.metrics_snapshot()
        assert snap["agent_runs_total"] >= 1
        assert snap["agent_runs_success"] >= 1

class TestAgentRunApi:
    """End-to-end Agent Run API tests (spec 25 / 65)."""

    @pytest.fixture(scope="module")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            yield c

    @pytest.fixture(autouse=True)
    def _mock_provider(self):
        from services.agent_runtime_service import get_agent_runtime
        rt = get_agent_runtime()
        assert rt is not None
        rt.provider_factory = lambda m: MockProvider(script=[MockProvider.final("mock answer")])
        yield

    def _login(self, client, username):
        client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": username + "@x.com"})
        r = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_create_agent_via_api(self, client):
        h = self._login(client, "apibota")
        r = client.post("/api/v1/agent/create", json={"name": "api-bot-a", "model": "mock", "tools": ["file_read"]}, headers=h)
        assert r.status_code == 200
        agents = client.get("/api/v1/agent/list", headers=h).json()
        assert any(a["name"] == "api-bot-a" for a in agents)

    def test_run_success(self, client):
        h = self._login(client, "apibotb")
        client.post("/api/v1/agent/create", json={"name": "api-bot-b", "model": "mock"}, headers=h)
        r = client.post("/api/v1/agent/runs", json={"agent_id": "api-bot-b", "input": "summarize"}, headers=h)
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        assert r.json()["status"] == "PENDING"
        status = None
        for _ in range(50):
            data = client.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()
            status = data["status"]
            if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                break
            time.sleep(0.02)
        assert status == "COMPLETED", status
        data = client.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()
        assert data["output"] == "mock answer"
        assert data["started_at"] is not None
        assert data["finished_at"] is not None

    def test_run_agent_not_found(self, client):
        h = self._login(client, "apibotc")
        r = client.post("/api/v1/agent/runs", json={"agent_id": "ghost-agent", "input": "x"}, headers=h)
        assert r.status_code == 404

    def test_run_not_found(self, client):
        h = self._login(client, "apibotd")
        r = client.get("/api/v1/agent/runs/nonexistent_run", headers=h)
        assert r.status_code == 404

    def test_cancel_run(self, client):
        h = self._login(client, "apibote")
        client.post("/api/v1/agent/create", json={"name": "api-bot-e", "model": "mock"}, headers=h)
        r = client.post("/api/v1/agent/runs", json={"agent_id": "api-bot-e", "input": "x", "execute": False}, headers=h)
        run_id = r.json()["run_id"]
        r = client.post(f"/api/v1/agent/runs/{run_id}/cancel", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "CANCELLED"

    def test_list_runs_api(self, client):
        h = self._login(client, "apibotf")
        client.post("/api/v1/agent/create", json={"name": "api-bot-f", "model": "mock"}, headers=h)
        client.post("/api/v1/agent/runs", json={"agent_id": "api-bot-f", "input": "x"}, headers=h)
        runs = client.get("/api/v1/agent/runs", headers=h).json()
        assert isinstance(runs, list)
        assert len(runs) >= 1

    def test_run_ownership(self, client):
        h1 = self._login(client, "apibotg1")
        h2 = self._login(client, "apibotg2")
        client.post("/api/v1/agent/create", json={"name": "api-bot-g", "model": "mock"}, headers=h1)
        r = client.post("/api/v1/agent/runs", json={"agent_id": "api-bot-g", "input": "x"}, headers=h1)
        run_id = r.json()["run_id"]
        r = client.get(f"/api/v1/agent/runs/{run_id}", headers=h2)
        assert r.status_code == 404

    def test_metrics_api(self, client):
        h = self._login(client, "apiboth")
        r = client.get("/api/v1/agent/metrics", headers=h)
        assert r.status_code == 200
        data = r.json()
        for name in ("agent_runs_total", "llm_calls_total", "tool_calls_total"):
            assert name in data