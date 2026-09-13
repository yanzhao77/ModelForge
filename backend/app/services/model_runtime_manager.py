"""Unified local model runtime manager.

Before this module, a caller that wanted to run a local model had to know how
to build the right engine and where the weights lived. Chat, the RAG answer
route and the runtime page each created their own ``LocalRuntime`` with no
model attached, so ``model_id`` could never be resolved to a file.

``ModelRuntimeManager`` is now the only component that turns a registry
``model_id`` into a loaded engine. It owns:

* the single active :class:`RuntimeInstance` (one local model at a time),
* the load/unload state machine and its concurrency guards,
* the mapping ``model_id -> model_path -> runtime adapter``.

Chat, training, the runtime page and the OpenAI-compatible API all go through
this manager, which is what makes them share one loaded instance.
"""

from __future__ import annotations

import asyncio
import datetime
import gc
import json
import threading
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.api_contracts import problem
from core.config import settings
from models.records import ModelRecord
from services.model_capabilities import ModelCapability
from services.model_registry import ModelRegistry, ModelRegistryError
from services.runtime_resolver import RuntimeResolver

_RUNTIME_CONFIG_FILENAME = "model_runtime_config.json"
#: Defaults mirror the llama.cpp / transformers options the UI exposes.
DEFAULT_LOAD_CONFIG: dict[str, int] = {"context_length": 4096, "gpu_layers": 0, "threads": 0}

#: Load-queue priorities (V1.3). Lower rank is admitted first.
_PRIORITY_RANKS = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
_PRIORITY_LABELS = {rank: label for label, rank in _PRIORITY_RANKS.items()}


class ModelRuntimeError(RuntimeError):
    """Stable runtime failure with an API-facing problem contract."""

    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status

    def to_problem(self, correlation: str | None = None):
        return problem(self.http_status, self.code, self.message, correlation=correlation, details=self.details or None)


@dataclass
class RuntimeInstance:
    """A model that is loaded (or being loaded) into memory."""

    instance_id: str
    model_id: int
    model_name: str
    runtime_type: str
    runtime_id: str | None
    status: str
    model_path: str
    context_length: int | None = None
    gpu_layers: int | None = None
    threads: int | None = None
    memory_bytes: int | None = None
    started_at: datetime.datetime | None = None
    last_used_at: datetime.datetime | None = None
    error: str | None = None
    active_requests: int = field(default=0, repr=False)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["active"] = self.status == "loaded"
        payload["runtime"] = self.runtime_type
        for key in ("started_at", "last_used_at"):
            value = payload.get(key)
            payload[key] = value.isoformat() if value else None
        # The absolute path stays server-side: API consumers only ever need the
        # stable identifiers.
        payload.pop("model_path", None)
        return payload


def _runtime_type_for(model_format: str | None) -> str:
    return "llama.cpp" if (model_format or "").lower() in {"gguf", "ggml"} else "transformers"


def _default_runtime_factory(record: ModelRecord, model_path: str):
    """Build the engine for a local asset; heavy imports stay lazy."""
    _runtime_id, _adapter, engine = RuntimeResolver.create_engine(record, model_path)
    return engine


class ModelRuntimeManager:
    """Multi-instance manager for local model inference (V1.3).

    Several models may be loaded at once, bounded by ``max_instances`` and (when
    RAM is measurable) by a memory budget. When capacity is exhausted the
    least-recently-used **idle** instance is evicted; a busy instance is never
    evicted, so a request either waits in the priority queue or is rejected.
    """

    def __init__(
        self,
        *,
        runtime_factory: Callable[[ModelRecord, str], object] | None = None,
        max_instances: int | None = None,
        queue_timeout_seconds: float | None = None,
        resource_manager=None,
    ):
        self._factory = runtime_factory or _default_runtime_factory
        self._state_lock = threading.RLock()
        self._instances: dict[int, RuntimeInstance] = {}
        self._engines: dict[int, object] = {}
        self._transitioning = False
        self._load_config: dict[str, int] = dict(DEFAULT_LOAD_CONFIG)
        self._load_config.update(self._read_persisted_config())
        self.max_instances = max(1, int(max_instances or settings.runtime_max_loaded_models or 1))
        self.queue_timeout_seconds = float(
            queue_timeout_seconds
            if queue_timeout_seconds is not None
            else (settings.runtime_load_queue_timeout_seconds or 30)
        )
        from services.resource_manager import get_resource_manager

        self.resources = resource_manager or get_resource_manager()
        self.resources.memory_ratio = float(settings.runtime_memory_ratio or 0.85)
        #: Pending loads: (priority_rank, sequence, model_id, user_id).
        self._queue: list[tuple[int, int, int, int | None]] = []
        self._queue_seq = 0
        #: Bounded lifecycle log. Phase 9 keeps page synchronisation on polling,
        #: so clients can compare this sequence instead of diffing every field.
        self._events: deque[dict] = deque(maxlen=50)
        self._event_seq = 0

    # -- introspection ------------------------------------------------------

    def get_current(self) -> RuntimeInstance | None:
        """The most recently used loaded instance (single-instance API compat)."""
        with self._state_lock:
            loaded = [item for item in self._instances.values() if item.status == "loaded"]
        if not loaded:
            return None
        return max(loaded, key=lambda item: item.last_used_at or item.started_at or datetime.datetime.min)

    def list_loaded(self) -> list[RuntimeInstance]:
        with self._state_lock:
            return [item for item in self._instances.values() if item.status == "loaded"]

    def instances_payload(self) -> list[dict]:
        """All instances (including transitional ones) for the runtime API."""
        with self._state_lock:
            instances = list(self._instances.values())
        return [instance.to_dict() for instance in instances]

    def queue_snapshot(self) -> list[dict]:
        with self._state_lock:
            return [
                {
                    "position": index,
                    "priority": _PRIORITY_LABELS.get(rank, "NORMAL"),
                    "model_id": model_id,
                    "user_id": user_id,
                }
                for index, (rank, _seq, model_id, user_id) in enumerate(
                    sorted(self._queue, key=lambda item: (item[0], item[1]))
                )
            ]

    def get_status(self, model_id: int | None = None) -> dict:
        with self._state_lock:
            if model_id is None:
                instance = self.get_current()
            else:
                instance = self._instances.get(int(model_id))
            if instance is None:
                return {"active": False, "status": "idle", "model_id": model_id}
            return instance.to_dict()

    def load_config(self) -> dict[str, int]:
        with self._state_lock:
            return dict(self._load_config)

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._state_lock:
            events = list(self._events)
        return events[-max(1, limit):]

    def _record_event(self, name: str, **payload: object) -> None:
        with self._state_lock:
            self._event_seq += 1
            self._events.append(
                {
                    "sequence": self._event_seq,
                    "event": name,
                    "at": datetime.datetime.utcnow().isoformat() + "Z",
                    **payload,
                }
            )

    def record_load_config(self, **config: object) -> dict[str, int]:
        """Remember the last explicit runtime configuration shown in the UI."""
        with self._state_lock:
            for key in DEFAULT_LOAD_CONFIG:
                value = config.get(key)
                if value is None:
                    continue
                try:
                    self._load_config[key] = int(value)
                except (TypeError, ValueError):
                    continue
            snapshot = dict(self._load_config)
        self._persist_config(snapshot)
        return snapshot

    # -- lifecycle ----------------------------------------------------------

    async def load(
        self,
        model_id: int,
        user_id: int | None = None,
        *,
        db=None,
        runtime: str | None = None,
        priority: str = "NORMAL",
        context_length: int | None = None,
        gpu_layers: int | None = None,
        threads: int | None = None,
        **kwargs: object,
    ) -> RuntimeInstance:
        """Load a model by ``model_id``, evicting or queueing as needed."""
        record, model_path = self._resolve_target(model_id, user_id, db)
        config = self.record_load_config(
            context_length=context_length, gpu_layers=gpu_layers, threads=threads
        )
        engine_kwargs = dict(kwargs)
        if config.get("context_length"):
            engine_kwargs.setdefault("input_max_length", config["context_length"])
        if config.get("gpu_layers") is not None:
            engine_kwargs.setdefault("n_gpu_layers", config["gpu_layers"])
        if config.get("threads"):
            engine_kwargs.setdefault("n_threads", config["threads"])

        runtime_id = self._resolve_runtime(record, runtime)
        with self._state_lock:
            existing = self._instances.get(record.id)
            if existing is not None and existing.status == "loading":
                raise ModelRuntimeError(
                    "MODEL_ALREADY_LOADING",
                    "已有模型正在加载，请等待当前操作完成。",
                    {"model_id": model_id},
                )
            if (
                existing is not None
                and existing.status == "loaded"
                and (runtime_id is None or existing.runtime_id == runtime_id)
            ):
                # Idempotent re-load: hand back the already loaded instance.
                # Requesting a *different* adapter falls through and reloads.
                return existing
            if runtime_id is None:
                # No adapter can serve this asset: report it honestly instead of
                # loading it with an engine that cannot read the weights.
                raise ModelRuntimeError(
                    "MODEL_FORMAT_UNSUPPORTED",
                    "该模型格式没有可用的运行时适配器。",
                    {
                        "model_id": record.id,
                        "format": record.format,
                        "supported_runtimes": record.supported_runtime_list(),
                    },
                )

        await self._make_room(record, user_id, priority=priority)

        with self._state_lock:
            self._transitioning = True
        self._record_event("MODEL_LOADING", model_id=record.id)

        previous = self._instances.get(record.id)
        instance = RuntimeInstance(
            instance_id=uuid.uuid4().hex,
            model_id=record.id,
            model_name=record.display_name or record.name,
            runtime_type=RuntimeResolver.label(runtime_id),
            runtime_id=runtime_id,
            status="loading",
            model_path=model_path,
            context_length=config.get("context_length"),
            gpu_layers=config.get("gpu_layers"),
            threads=config.get("threads"),
        )
        claim = self.resources.claim(
            record.id,
            bytes_estimate=self.resources.estimate_instance_bytes(record, config.get("context_length")),
            context_length=config.get("context_length"),
        )
        instance.memory_bytes = claim["estimated_bytes"]
        try:
            if previous is not None:
                await self._teardown(previous)
            engine = self._factory(record, model_path)
            with self._state_lock:
                self._engines[record.id] = engine
                self._instances[record.id] = instance
            await engine.load(model_path, **engine_kwargs)
        except ModelRuntimeError:
            self._fail(instance, "模型加载失败", db)
            raise
        except Exception as exc:
            self._fail(instance, f"模型加载失败：{type(exc).__name__}", db)
            raise ModelRuntimeError(
                "RUNTIME_LOAD_FAILED",
                "模型加载失败，请确认本地运行时与模型文件可用。",
                {"model_id": record.id},
                http_status=502,
            ) from exc
        with self._state_lock:
            instance.status = "loaded"
            instance.started_at = datetime.datetime.utcnow()
            instance.last_used_at = instance.started_at
            self._transitioning = False
        self._persist_status(record.id, "loaded", db)
        self._record_event("MODEL_LOADED", model_id=record.id, instance_id=instance.instance_id)
        return instance

    async def _make_room(self, record: ModelRecord, user_id: int | None, *, priority: str) -> None:
        """Evict an idle LRU instance, or wait in the priority queue for capacity."""
        rank = _PRIORITY_RANKS.get(str(priority).upper(), _PRIORITY_RANKS["NORMAL"])
        deadline = asyncio.get_event_loop().time() + max(0.1, self.queue_timeout_seconds)
        queued = False
        entry: tuple[int, int, int, int | None] | None = None
        while True:
            with self._state_lock:
                if record.id in self._instances:
                    return
                capacity_free = len(self._instances) < self.max_instances
                needed = self.resources.estimate_instance_bytes(record)
                fits = self.resources.fits(needed)
                if fits is False:
                    capacity_free = False
                head = min(self._queue, key=lambda item: (item[0], item[1])) if self._queue else None

            if capacity_free and (not queued or head is entry):
                self._dequeue(entry)
                return
            if capacity_free and queued and head is not entry:
                # A higher-priority waiter is ahead of us; let it go first.
                pass
            elif not capacity_free:
                victim = self._lru_victim(exclude={record.id})
                if victim is not None:
                    self._record_event("MODEL_EVICTING", model_id=victim.model_id, reason="lru")
                    await self.unload(victim.model_id)
                    continue
            if not queued:
                entry = self._enqueue(rank, record.id, user_id)
                queued = True
                self._record_event("MODEL_LOAD_QUEUED", model_id=record.id, priority=str(priority).upper())
            if asyncio.get_event_loop().time() >= deadline:
                self._dequeue(entry)
                raise ModelRuntimeError(
                    "RUNTIME_BUSY",
                    "资源不足且所有已加载模型都在使用中，请稍后再试。",
                    {"model_id": record.id, "max_instances": self.max_instances},
                )
            await asyncio.sleep(0.05)

    def _enqueue(self, rank: int, model_id: int, user_id: int | None):
        with self._state_lock:
            self._queue_seq += 1
            entry = (rank, self._queue_seq, model_id, user_id)
            self._queue.append(entry)
            return entry

    def _dequeue(self, entry) -> None:
        if entry is None:
            return
        with self._state_lock:
            if entry in self._queue:
                self._queue.remove(entry)

    def _lru_victim(self, *, exclude: set[int] | None = None) -> RuntimeInstance | None:
        """Least-recently-used instance that is safe to evict (never busy)."""
        excluded = exclude or set()
        with self._state_lock:
            candidates = [
                item
                for item in self._instances.values()
                if item.model_id not in excluded
                and item.status == "loaded"
                and item.active_requests == 0
            ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item.last_used_at or item.started_at or datetime.datetime.min)

    async def evict(self, model_id: int, user_id: int | None = None) -> dict:
        """Explicitly unload one instance (used by the runtime page)."""
        return await self.unload(model_id, user_id)

    async def unload_all(self, user_id: int | None = None) -> dict:
        unloaded: list[int] = []
        for instance in list(self.list_loaded()):
            try:
                await self.unload(instance.model_id, user_id)
                unloaded.append(instance.model_id)
            except ModelRuntimeError:
                continue
        return {"unloaded": unloaded, "count": len(unloaded)}

    async def unload(self, model_id: int | None = None, user_id: int | None = None, *, db=None) -> dict:
        """Release the active runtime; refuses while requests are in flight."""
        del user_id  # resource ownership is enforced by the API layer's lease
        with self._state_lock:
            if model_id is None:
                instance = self.get_current()
            else:
                instance = self._instances.get(int(model_id))
            if instance is None:
                return {"status": "idle", "model_id": model_id, "unloaded": False}
            if instance.status in {"loading", "unloading"}:
                raise ModelRuntimeError(
                    "RUNTIME_BUSY",
                    "模型正在加载或卸载，请稍后再试。",
                    {"model_id": instance.model_id, "status": instance.status},
                )
            if instance.active_requests > 0:
                raise ModelRuntimeError(
                    "RUNTIME_BUSY",
                    "模型正在处理请求，请等待请求完成后再卸载。",
                    {"model_id": instance.model_id, "active_requests": instance.active_requests},
                )
            instance.status = "unloading"
        self._record_event("MODEL_UNLOADING", model_id=instance.model_id)
        await self._teardown(instance)
        self._persist_status(instance.model_id, "ready", db)
        self._record_event("MODEL_UNLOADED", model_id=instance.model_id)
        return {
            "status": "unloaded",
            "model_id": instance.model_id,
            "instance_id": instance.instance_id,
            "unloaded": True,
        }

    async def _teardown(self, instance: RuntimeInstance) -> None:
        """Release engine references and force the garbage collector to reclaim."""
        with self._state_lock:
            engine = self._engines.pop(instance.model_id, None)
            if self._instances.get(instance.model_id) is instance:
                self._instances.pop(instance.model_id, None)
        self.resources.release(instance.model_id)
        if engine is not None:
            try:
                await engine.stop(instance.model_path)
            except Exception:
                # A failed stop must not leak the reference; the object is still
                # dropped below so the memory can be reclaimed.
                pass
        del engine
        gc.collect()

    def _fail(self, instance: RuntimeInstance, message: str, db=None) -> None:
        with self._state_lock:
            if self._instances.get(instance.model_id) is instance:
                self._instances.pop(instance.model_id, None)
            self._engines.pop(instance.model_id, None)
            self._transitioning = False
        self.resources.release(instance.model_id)
        gc.collect()
        self._persist_status(instance.model_id, "load_failed", db)
        self._record_event("MODEL_LOAD_FAILED", model_id=instance.model_id)

    # -- inference ----------------------------------------------------------

    async def chat(
        self,
        model_id: int,
        messages: list[dict],
        *,
        user_id: int | None = None,
        db=None,
        runtime: str | None = None,
        ensure_loaded: bool = True,
        **kwargs: object,
    ) -> dict:
        instance, engine = await self._acquire(model_id, user_id, db, ensure_loaded, runtime)
        try:
            result = await engine.chat(instance.model_path, messages, **kwargs)
        finally:
            self._release_request(instance)
        payload = dict(result or {})
        payload.setdefault("model", instance.model_name)
        payload.setdefault("model_id", instance.model_id)
        return payload

    async def stream_chat(
        self,
        model_id: int,
        messages: list[dict],
        *,
        user_id: int | None = None,
        db=None,
        runtime: str | None = None,
        ensure_loaded: bool = True,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        instance, engine = await self._acquire(model_id, user_id, db, ensure_loaded, runtime)
        stream_fn = getattr(engine, "stream_chat", None)
        try:
            if stream_fn is None:
                result = await engine.chat(instance.model_path, messages, **kwargs)
                yield str((result or {}).get("content", ""))
                return
            async for chunk in stream_fn(instance.model_path, messages, **kwargs):
                yield chunk
        finally:
            self._release_request(instance)

    async def _acquire(self, model_id, user_id, db, ensure_loaded, runtime=None):
        with self._state_lock:
            instance = self._instances.get(int(model_id))
            engine = self._engines.get(int(model_id))
            ready = (
                instance is not None
                and engine is not None
                and instance.status == "loaded"
            )
            if ready:
                instance.active_requests += 1
                instance.last_used_at = datetime.datetime.utcnow()
                return instance, engine
        if not ensure_loaded:
            raise ModelRuntimeError(
                "RUNTIME_NOT_LOADED",
                "模型尚未加载，请先加载模型。",
                {"model_id": model_id},
            )
        instance = await self.load(model_id, user_id, db=db, runtime=runtime)
        with self._state_lock:
            if self._instances.get(instance.model_id) is instance:
                instance.active_requests += 1
                instance.last_used_at = datetime.datetime.utcnow()
                return instance, self._engines.get(instance.model_id)
        raise ModelRuntimeError(
            "RUNTIME_LOAD_FAILED",
            "模型加载后状态异常，请重试。",
            {"model_id": model_id},
            http_status=502,
        )

    def _release_request(self, instance: RuntimeInstance) -> None:
        with self._state_lock:
            if instance.active_requests > 0:
                instance.active_requests -= 1
            instance.last_used_at = datetime.datetime.utcnow()

    # -- helpers ------------------------------------------------------------

    def _resolve_target(self, model_id, user_id, db) -> tuple[ModelRecord, str]:
        from core.database import SessionLocal

        owns_session = db is None
        session = db or SessionLocal()
        try:
            registry = ModelRegistry(session)
            try:
                record = registry.require(model_id, user_id)
                registry.require_ready(record)
                registry.require_capability(record, ModelCapability.INFERENCE.value)
                model_path = registry.resolve_path(record)
            except ModelRegistryError as exc:
                raise ModelRuntimeError(
                    exc.code, exc.message, exc.details, http_status=exc.http_status
                ) from exc
            return record, model_path
        finally:
            if owns_session:
                session.close()

    @staticmethod
    def _resolve_runtime(record: ModelRecord, runtime: str | None) -> str | None:
        """Pick the adapter for this asset (explicit override wins)."""
        return RuntimeResolver.resolve(record, runtime)

    def _persist_status(self, model_id: int, status: str, db=None) -> None:
        """Reflect the runtime state on the registry row (best effort).

        The caller's session is reused when one is supplied so the change is
        visible to the request that triggered it; otherwise a short-lived
        session is opened and closed here.
        """
        from core.database import SessionLocal

        session = db
        owns_session = session is None
        if owns_session:
            session = SessionLocal()
        try:
            record = session.get(ModelRecord, model_id)
            if record is not None:
                record.status = status
                session.commit()
        except Exception:
            return
        finally:
            if owns_session:
                session.close()

    # -- configuration persistence -----------------------------------------

    def _config_path(self) -> Path:
        data_dir = Path(settings.data_dir)
        if not data_dir.is_absolute():
            data_dir = Path(__file__).resolve().parents[3] / data_dir
        return data_dir / _RUNTIME_CONFIG_FILENAME

    def _read_persisted_config(self) -> dict[str, int]:
        try:
            payload = json.loads(self._config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        restored: dict[str, int] = {}
        for key in DEFAULT_LOAD_CONFIG:
            value = payload.get(key)
            if isinstance(value, int):
                restored[key] = value
        return restored

    def _persist_config(self, config: dict[str, int]) -> None:
        try:
            path = self._config_path()
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return


#: Process-wide singleton: the machine runs exactly one local model at a time.
model_runtime_manager = ModelRuntimeManager()


def get_model_runtime_manager() -> ModelRuntimeManager:
    return model_runtime_manager


__all__ = [
    "DEFAULT_LOAD_CONFIG",
    "ModelRuntimeError",
    "ModelRuntimeManager",
    "RuntimeInstance",
    "get_model_runtime_manager",
    "model_runtime_manager",
]
