"""Model runtime manager: load / unload / reload / switching / conflict rules."""

from __future__ import annotations

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


class FakeEngine:
    """In-memory stand-in for the llama.cpp / transformers adapter."""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.loaded = False
        self.stopped = False
        self.fail_load = False

    async def load(self, model_name: str, **kwargs):
        if self.fail_load:
            raise RuntimeError("boom")
        self.loaded = True
        self.load_options = kwargs
        return {"status": "loaded", "model": model_name}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        return {"model": model_name, "content": f"echo:{messages[-1]['content']}", "raw": None}

    async def stream_chat(self, model_name: str, messages: list, **kwargs):
        yield "part-1"
        yield "part-2"

    async def stop(self, model_name: str) -> dict:
        self.stopped = True
        return {"status": "stopped", "model": model_name}


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def harness(session, tmp_path):
    engines: list[FakeEngine] = []

    def factory(record, model_path):
        engine = FakeEngine(model_path)
        engines.append(engine)
        return engine

    manager = ModelRuntimeManager(runtime_factory=factory)
    registry = ModelRegistry(session)
    models = {}
    for name in ("alpha", "beta"):
        asset = tmp_path / "models" / f"{name}.gguf"
        asset.write_bytes(b"GGUF" + name.encode())
        models[name] = registry.register(name=name, provider="local", path=str(asset), user_id=1)
    return {"manager": manager, "registry": registry, "session": session, "models": models, "engines": engines}


@pytest.mark.asyncio
async def test_load_chat_unload_cycle(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]

    instance = await manager.load(alpha.id, 1, db=harness["session"])
    assert instance.status == "loaded"
    assert instance.model_id == alpha.id
    assert instance.runtime_type == "llama.cpp"
    assert manager.get_current() is instance

    result = await manager.chat(alpha.id, [{"role": "user", "content": "hi"}], user_id=1, db=harness["session"])
    assert result["content"] == "echo:hi"
    assert result["model_id"] == alpha.id

    outcome = await manager.unload(alpha.id, 1, db=harness["session"])
    assert outcome["unloaded"] is True
    assert manager.get_current() is None
    assert manager.list_loaded() == []
    assert harness["engines"][0].stopped is True
    # The registry reflects the released state so the UI can show "ready".
    harness["session"].expire_all()
    assert harness["session"].get(ModelRecord, alpha.id).status == "ready"


@pytest.mark.asyncio
async def test_loading_second_model_replaces_the_first(harness):
    manager = harness["manager"]
    alpha, beta = harness["models"]["alpha"], harness["models"]["beta"]

    await manager.load(alpha.id, 1, db=harness["session"])
    instance = await manager.load(beta.id, 1, db=harness["session"])

    assert instance.model_id == beta.id
    assert harness["engines"][0].stopped is True  # alpha was unloaded first
    assert manager.get_current().model_id == beta.id
    assert len(manager.list_loaded()) == 1


@pytest.mark.asyncio
async def test_reload_cycle_five_times_releases_every_engine(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]

    for _ in range(5):
        await manager.load(alpha.id, 1, db=harness["session"])
        await manager.chat(alpha.id, [{"role": "user", "content": "x"}], user_id=1, db=harness["session"])
        await manager.unload(alpha.id, 1)

    assert len(harness["engines"]) == 5
    assert all(engine.stopped for engine in harness["engines"])
    assert manager.get_current() is None


@pytest.mark.asyncio
async def test_load_is_idempotent_for_the_loaded_model(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]

    first = await manager.load(alpha.id, 1, db=harness["session"])
    second = await manager.load(alpha.id, 1, db=harness["session"])

    assert first is second
    assert len(harness["engines"]) == 1


@pytest.mark.asyncio
async def test_chat_auto_loads_an_idle_model(harness):
    manager = harness["manager"]
    beta = harness["models"]["beta"]

    result = await manager.chat(beta.id, [{"role": "user", "content": "hello"}], user_id=1, db=harness["session"])

    assert result["content"] == "echo:hello"
    assert manager.get_current().model_id == beta.id


@pytest.mark.asyncio
async def test_unknown_model_reports_a_stable_code(harness):
    with pytest.raises(ModelRuntimeError) as excinfo:
        await harness["manager"].load(999999, 1, db=harness["session"])

    assert excinfo.value.code == "MODEL_NOT_FOUND"
    assert excinfo.value.http_status == 404


@pytest.mark.asyncio
async def test_inference_incapable_model_is_rejected(harness, session, tmp_path):
    registry = harness["registry"]
    adapter = tmp_path / "models" / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_model.safetensors").write_bytes(b"w")
    record = registry.register(
        name="adapter-only",
        provider="training",
        path=str(adapter),
        user_id=1,
        model_format="peft-adapter",
        capabilities=["LORA"],
    )

    with pytest.raises(ModelRuntimeError) as excinfo:
        await harness["manager"].load(record.id, 1, db=session)

    assert excinfo.value.code == "MODEL_CAPABILITY_UNSUPPORTED"


@pytest.mark.asyncio
async def test_load_failure_clears_state_and_marks_the_record(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]

    original_factory = manager._factory

    def failing_factory(record, path):
        engine = original_factory(record, path)
        engine.fail_load = True
        return engine

    manager._factory = failing_factory
    with pytest.raises(ModelRuntimeError) as excinfo:
        await manager.load(alpha.id, 1, db=harness["session"])

    assert excinfo.value.code == "RUNTIME_LOAD_FAILED"
    assert manager.get_current() is None
    harness["session"].expire_all()
    assert harness["session"].get(ModelRecord, alpha.id).status == "load_failed"


@pytest.mark.asyncio
async def test_unload_is_refused_while_a_request_is_in_flight(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]
    instance = await manager.load(alpha.id, 1, db=harness["session"])
    instance.active_requests = 1

    with pytest.raises(ModelRuntimeError) as excinfo:
        await manager.unload(alpha.id, 1)

    assert excinfo.value.code == "RUNTIME_BUSY"
    assert manager.get_current() is instance


@pytest.mark.asyncio
async def test_stream_chat_yields_engine_deltas(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]

    chunks = [chunk async for chunk in manager.stream_chat(alpha.id, [{"role": "user", "content": "s"}], user_id=1, db=harness["session"])]

    assert chunks == ["part-1", "part-2"]


@pytest.mark.asyncio
async def test_status_reports_idle_and_loaded(harness):
    manager = harness["manager"]
    alpha = harness["models"]["alpha"]

    assert manager.get_status(alpha.id)["active"] is False
    await manager.load(alpha.id, 1, db=harness["session"])
    status = manager.get_status(alpha.id)
    assert status["active"] is True
    assert status["status"] == "loaded"
    assert "model_path" not in status  # paths stay server-side


@pytest.mark.asyncio
async def test_lifecycle_events_are_recorded_in_order(harness):
    manager = harness["manager"]
    alpha, beta = harness["models"]["alpha"], harness["models"]["beta"]

    await manager.load(alpha.id, 1, db=harness["session"])
    await manager.unload(alpha.id, 1, db=harness["session"])
    await manager.chat(beta.id, [{"role": "user", "content": "x"}], user_id=1, db=harness["session"])
    await manager.unload(beta.id, 1, db=harness["session"])

    events = [event["event"] for event in manager.recent_events()]
    assert events == [
        "MODEL_LOADING",
        "MODEL_LOADED",
        "MODEL_UNLOADING",
        "MODEL_UNLOADED",
        "MODEL_LOADING",
        "MODEL_LOADED",
        "MODEL_UNLOADING",
        "MODEL_UNLOADED",
    ]
    sequences = [event["sequence"] for event in manager.recent_events()]
    assert sequences == sorted(sequences)
