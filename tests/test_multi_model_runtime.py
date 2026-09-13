"""V1.3 Multi-Model runtime: capacity, LRU eviction, queue, priorities, resources."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import Base  # noqa: E402
from models.records import ModelRecord  # noqa: E402
from services.model_registry import ModelRegistry  # noqa: E402
from services.model_runtime_manager import (  # noqa: E402
    ModelRuntimeError,
    ModelRuntimeManager,
)
from services.resource_manager import ResourceManager  # noqa: E402


class FakeEngine:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.stopped = False
        self.loaded = False

    async def load(self, model_name: str, **kwargs):
        self.loaded = True
        return {"status": "loaded"}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"content": "ok"}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "ok"

    async def stop(self, model_name: str) -> dict:
        self.stopped = True
        return {"status": "stopped"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    engines: list[FakeEngine] = []

    def factory(record, model_path):
        item = FakeEngine(model_path)
        engines.append(item)
        return item

    registry = ModelRegistry(session)
    records = {}
    for name in ("a", "b", "c"):
        asset = tmp_path / "models" / f"{name}.gguf"
        asset.write_bytes(b"G" * 1024)
        records[name] = registry.register(name=name, provider="local", path=str(asset), user_id=1)
    yield {"session": session, "registry": registry, "records": records, "engines": engines, "factory": factory}
    session.close()
    Base.metadata.drop_all(bind=engine)


def _manager(env, **kwargs) -> ModelRuntimeManager:
    # A dedicated ResourceManager keeps this test's accounting isolated from the
    # process-wide singleton (which other test modules also load models into).
    return ModelRuntimeManager(
        runtime_factory=env["factory"], resource_manager=ResourceManager(), **kwargs
    )


@pytest.mark.asyncio
async def test_multiple_instances_coexist(env):
    manager = _manager(env, max_instances=3)
    records = env["records"]

    await manager.load(records["a"].id, 1, db=env["session"])
    await manager.load(records["b"].id, 1, db=env["session"])
    await manager.load(records["c"].id, 1, db=env["session"])

    assert len(manager.list_loaded()) == 3
    payload = manager.instances_payload()
    assert {item["model_id"] for item in payload} == {record.id for record in records.values()}
    assert manager.get_status(records["b"].id)["active"] is True


@pytest.mark.asyncio
async def test_lru_evicts_the_idle_oldest_instance(env):
    manager = _manager(env, max_instances=2)
    records, engines = env["records"], env["engines"]

    await manager.load(records["a"].id, 1, db=env["session"])
    await manager.load(records["b"].id, 1, db=env["session"])
    await manager.load(records["c"].id, 1, db=env["session"])

    loaded_ids = {instance.model_id for instance in manager.list_loaded()}
    assert loaded_ids == {records["b"].id, records["c"].id}
    assert engines[0].stopped is True  # "a" was the LRU victim
    events = [event["event"] for event in manager.recent_events()]
    assert "MODEL_EVICTING" in events


@pytest.mark.asyncio
async def test_busy_instance_is_never_evicted(env):
    manager = _manager(env, max_instances=1, queue_timeout_seconds=0.3)
    records = env["records"]
    instance = await manager.load(records["a"].id, 1, db=env["session"])
    instance.active_requests = 1  # pretend a chat is in flight

    with pytest.raises(ModelRuntimeError) as excinfo:
        await manager.load(records["b"].id, 1, db=env["session"])

    assert excinfo.value.code == "RUNTIME_BUSY"
    assert manager.get_status(records["a"].id)["active"] is True
    assert manager.queue_snapshot() == []


@pytest.mark.asyncio
async def test_queued_load_proceeds_when_capacity_frees_up(env):
    manager = _manager(env, max_instances=1, queue_timeout_seconds=5)
    records = env["records"]
    instance = await manager.load(records["a"].id, 1, db=env["session"])
    instance.active_requests = 1

    async def release_soon():
        await asyncio.sleep(0.2)
        instance.active_requests = 0
        await manager.unload(records["a"].id, 1, db=env["session"])

    releaser = asyncio.create_task(release_soon())
    loaded = await manager.load(records["b"].id, 1, db=env["session"], priority="HIGH")
    await releaser

    assert loaded.model_id == records["b"].id
    assert manager.queue_snapshot() == []


@pytest.mark.asyncio
async def test_queue_reports_priority_order(env):
    manager = _manager(env, max_instances=1, queue_timeout_seconds=0.2)
    records = env["records"]
    instance = await manager.load(records["a"].id, 1, db=env["session"])
    instance.active_requests = 1

    low = asyncio.create_task(manager.load(records["b"].id, 1, db=env["session"], priority="LOW"))
    await asyncio.sleep(0.05)
    high = asyncio.create_task(manager.load(records["c"].id, 1, db=env["session"], priority="HIGH"))
    await asyncio.sleep(0.05)

    queue = manager.queue_snapshot()
    assert [item["priority"] for item in queue] == ["HIGH", "LOW"]
    with pytest.raises(ModelRuntimeError):
        await low
    with pytest.raises(ModelRuntimeError):
        await high
    instance.active_requests = 0


@pytest.mark.asyncio
async def test_load_unload_cycles_release_every_instance_and_claim(env):
    manager = _manager(env, max_instances=2)
    records = env["records"]

    for index in range(6):
        record = records["abc"[index % 3]]
        await manager.load(record.id, 1, db=env["session"])
        await manager.chat(record.id, [{"role": "user", "content": "x"}], user_id=1, db=env["session"])
        await manager.unload(record.id, 1, db=env["session"])

    assert manager.list_loaded() == []
    assert manager.instances_payload() == []
    assert manager.resources.claims() == []
    assert manager.resources.claimed_bytes() == 0
    assert all(engine.stopped for engine in env["engines"])


@pytest.mark.asyncio
async def test_unload_all_releases_every_idle_instance(env):
    manager = _manager(env, max_instances=3)
    records = env["records"]
    await manager.load(records["a"].id, 1, db=env["session"])
    await manager.load(records["b"].id, 1, db=env["session"])

    result = await manager.unload_all(1)

    assert sorted(result["unloaded"]) == sorted([records["a"].id, records["b"].id])
    assert manager.list_loaded() == []


def test_resource_manager_estimates_and_snapshot(tmp_path):
    from services.model_registry import ModelRegistry

    manager = ResourceManager(data_dir=str(tmp_path))
    record = ModelRecord(id=1, name="m", provider="local", size_bytes=1_000_000, format="gguf")

    small = ResourceManager.estimate_instance_bytes(record, 1024)
    large = ResourceManager.estimate_instance_bytes(record, 8192)
    assert large > small
    assert small >= 1_000_000

    snapshot = manager.snapshot()
    payload = snapshot.to_dict()
    assert set(payload) >= {
        "measured",
        "cpu_count",
        "memory_total_bytes",
        "gpu_available",
        "vram_total_bytes",
        "disk_free_bytes",
        "notes",
    }
    assert payload["disk_total_bytes"] and payload["disk_free_bytes"]
    assert isinstance(payload["notes"], list)

    manager.claim(1, bytes_estimate=small, context_length=1024)
    assert manager.claimed_bytes() == small
    assert manager.claims()[0]["model_id"] == 1
    manager.release(1)
    assert manager.claimed_bytes() == 0

    fits = manager.fits(1)
    assert fits in (True, False, None)
