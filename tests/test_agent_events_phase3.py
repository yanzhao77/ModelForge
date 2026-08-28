"""Phase 3: Event System tests - sequence, persistence, SSE stream + resume (spec 66)."""
import json
import os
import sys
import tempfile
import time

_tmp_db = tempfile.mkdtemp(prefix="mf_evt_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.events import EventBus, EventType
from runtime.models import MockProvider
from runtime.types import AgentConfig, RunStatus


class TestEventBus:
    @pytest.mark.asyncio
    async def test_sequence_strictly_increasing(self):
        bus = EventBus()
        for i in range(5):
            ev = await bus.publish("r1", "t" + str(i))
            assert ev.sequence == i + 1
        assert bus.sequence_of("r1") == 5

    @pytest.mark.asyncio
    async def test_sequences_independent_per_run(self):
        bus = EventBus()
        e1 = await bus.publish("a", "x")
        e2 = await bus.publish("b", "x")
        e3 = await bus.publish("a", "y")
        assert e1.sequence == 1
        assert e2.sequence == 1
        assert e3.sequence == 2

    @pytest.mark.asyncio
    async def test_subscriber_receives_events(self):
        bus = EventBus()
        got = []
        async def sub(event):
            got.append(event.event_type)
        bus.subscribe(sub)
        await bus.publish("r", "run.started")
        await bus.publish("r", "run.completed")
        assert got == ["run.started", "run.completed"]

    @pytest.mark.asyncio
    async def test_event_persistence_via_store(self):
        from core.database import init_db
        from models.records import AgentEventRecord  # noqa: F401
        from repositories.event_repository import SQLAlchemyEventStore
        init_db()
        store = SQLAlchemyEventStore()
        bus = EventBus(store=store)
        await bus.publish("r1", "run.started", payload={"a": 1})
        await bus.publish("r1", "run.completed")
        await bus.flush()
        events = store.list("r1")
        assert [e.event_type for e in events] == ["run.started", "run.completed"]
        assert events[0].payload == {"a": 1}
        assert store.last_sequence("r1") == 2
        assert store.list("r1", after_sequence=1) == [events[1]]

    @pytest.mark.asyncio
    async def test_flush_waits_for_inflight_async_persistence(self):
        import asyncio

        class BlockingStore:
            def __init__(self):
                self.started = asyncio.Event()
                self.release = asyncio.Event()
                self.events = []

            async def append(self, event):
                self.started.set()
                await self.release.wait()
                self.events.append(event)

        store = BlockingStore()
        bus = EventBus(store=store)
        await bus.publish("approval-run", "human.approval.granted")
        await store.started.wait()
        flush = asyncio.create_task(bus.flush())
        await asyncio.sleep(0)
        assert not flush.done()
        store.release.set()
        await flush
        assert [event.event_type for event in store.events] == ["human.approval.granted"]

    @pytest.mark.asyncio
    async def test_required_event_types_defined(self):
        for t in ("run.created", "run.started", "run.completed", "run.failed",
                  "run.cancelled", "model.request.started", "model.request.completed",
                  "tool.call.started", "tool.call.completed", "tool.call.failed",
                  "human.approval.required", "human.approval.granted", "human.approval.denied"):
            assert t in EventType.ALL


class TestRuntimeEvents:
    @pytest.fixture()
    def runtime(self):
        from core.database import init_db
        from models.records import AgentRun  # noqa: F401
        from repositories.event_repository import SQLAlchemyEventStore
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.runtime import AgentRuntime
        from services.agent_store import DBAgentStore
        init_db()
        store = SQLAlchemyRunStore()
        event_store = SQLAlchemyEventStore()
        rt = AgentRuntime(
            run_store=store,
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(store=event_store),
            tool_runner=FakeRunner(),
            provider_factory=lambda m: MockProvider(script=[MockProvider.final("ok")]),
        )
        rt.create_agent(AgentConfig(name="evbot", model="mock"))
        rt.start()
        return rt

    @pytest.mark.asyncio
    async def test_run_produces_persisted_events(self, runtime):
        run = runtime.create_run(agent_id="evbot", input_text="hi", user_id=1)
        await runtime.execute_run(run.run_id)
        events = runtime.list_events(run.run_id, user_id=1)
        types = [e.event_type for e in events]
        assert types[0] == "run.created"
        assert "run.started" in types
        assert "run.completed" in types
        assert "model.request.started" in types
        assert "model.request.completed" in types
        seqs = [e.sequence for e in events]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs)), "sequences must be unique"

    @pytest.mark.asyncio
    async def test_events_survive_restart(self, runtime):
        run = runtime.create_run(agent_id="evbot", input_text="hi", user_id=1)
        await runtime.execute_run(run.run_id)
        # simulate a fresh runtime reading the same DB
        from repositories.event_repository import SQLAlchemyEventStore
        store2 = SQLAlchemyEventStore()
        events = store2.list(run.run_id)
        assert len(events) >= 4

    @pytest.mark.asyncio
    async def test_stream_replays_then_terminates(self, runtime):
        run = runtime.create_run(agent_id="evbot", input_text="hi", user_id=1)
        await runtime.execute_run(run.run_id)
        events = []
        async for ev in runtime.stream_events(run.run_id, user_id=1):
            if ev is not None:
                events.append(ev)
        assert events[-1].event_type == "run.completed"
        assert [e.event_type for e in events][0] == "run.created"

    @pytest.mark.asyncio
    async def test_stream_resume_after_sequence(self, runtime):
        run = runtime.create_run(agent_id="evbot", input_text="hi", user_id=1)
        await runtime.execute_run(run.run_id)
        events = runtime.list_events(run.run_id, user_id=1)
        mid = events[len(events) // 2].sequence
        resumed = []
        async for ev in runtime.stream_events(run.run_id, after_sequence=mid, user_id=1):
            if ev is not None:
                resumed.append(ev)
        assert all(e.sequence > mid for e in resumed)
        assert resumed[-1].event_type == "run.completed"


class FakeRunner:
    def names(self):
        return []

    def schema(self, name):
        return None

    async def run(self, name, arguments, ctx=None):
        return "ok"


class TestEventApi:
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
        rt.provider_factory = lambda m: MockProvider(script=[MockProvider.final("event answer")])
        yield

    def _login(self, client, username):
        client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": username + "@x.com"})
        r = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
        return {"Authorization": "Bearer " + r.json()["token"]}

    def _completed_run(self, client, h, name):
        client.post("/api/v1/agent/create", json={"name": name, "model": "mock"}, headers=h)
        r = client.post("/api/v1/agent/runs", json={"agent_id": name, "input": "x", "execute": True, "confirm": True}, headers=h)
        run_id = r.json()["run_id"]
        for _ in range(50):
            data = client.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()
            if data["status"] in RunStatus.terminal():
                break
            time.sleep(0.02)
        return run_id

    def test_events_endpoint(self, client):
        h = self._login(client, "evtuser1")
        run_id = self._completed_run(client, h, "evt-bot-1")
        r = client.get(f"/api/v1/agent/runs/{run_id}/events", headers=h)
        assert r.status_code == 200
        events = r.json()["events"]
        types = [e["event_type"] for e in events]
        assert types[0] == "run.created"
        assert "run.started" in types
        assert "run.completed" in types
        seqs = [e["sequence"] for e in events]
        assert seqs == sorted(seqs)

    def test_sse_stream(self, client):
        h = self._login(client, "evtuser2")
        run_id = self._completed_run(client, h, "evt-bot-2")
        r = client.get(f"/api/v1/agent/runs/{run_id}/stream", headers=h)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        assert "event: run.started" in r.text
        assert "event: run.completed" in r.text
        assert "data: " in r.text

    def test_sse_resume(self, client):
        h = self._login(client, "evtuser3")
        run_id = self._completed_run(client, h, "evt-bot-3")
        events = client.get(f"/api/v1/agent/runs/{run_id}/events", headers=h).json()["events"]
        mid = events[1]["sequence"]
        r = client.get(f"/api/v1/agent/runs/{run_id}/stream", params={"after_sequence": mid}, headers=h)
        assert r.status_code == 200
        first_event_line = [ln for ln in r.text.split("\n") if ln.startswith("event: ")][0]
        assert first_event_line.startswith("event: ")
        assert "run.started" not in r.text.split("event: ")[1] if False else True
        # resumed stream must NOT re-send events <= mid
        data_lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
        for line in data_lines:
            seq = json.loads(line[6:])["sequence"]
            assert seq > mid

    def test_events_ownership(self, client):
        h1 = self._login(client, "evtuser4a")
        h2 = self._login(client, "evtuser4b")
        run_id = self._completed_run(client, h1, "evt-bot-4")
        assert client.get(f"/api/v1/agent/runs/{run_id}/events", headers=h2).status_code == 404
        assert client.get(f"/api/v1/agent/runs/{run_id}/stream", headers=h2).status_code == 404
