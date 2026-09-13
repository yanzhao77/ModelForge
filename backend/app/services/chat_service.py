"""Unified chat service with optional user-scoped remote provider override."""
import time
from collections.abc import AsyncIterator

from models.records import User
from services.memory_store import MemoryStore
from services.model_metrics import ModelMetricRecorder
from services.runtime_registry import RuntimeRegistry
from services.runtimes.openai_api_runtime import OpenAIRuntime
from services.session_service import SessionService
from sqlalchemy.orm import Session as DBSession


def _memory_context(db: DBSession, user_id: int, query: str) -> str:
    try:
        memories = MemoryStore.get_relevant_memories_for_query(db, user_id, query, limit=3)
        return MemoryStore.format_memories_for_context(memories)
    except Exception:
        return ""


def _runtime(runtime: RuntimeRegistry, provider: dict | None):
    if provider is None:
        return runtime
    return OpenAIRuntime(
        api_key=provider["api_key"], base_url=provider["base_url"],
        model=provider["default_model"], protocol=provider["protocol"],
    )


def _context(db: DBSession, user: User | None, session_id: int | None, messages: list[dict]):
    session = None
    if session_id is not None:
        if user is None:
            raise PermissionError("login required for session chat")
        session = SessionService.get_session_by_id(db, session_id, user.id)
        if session is None:
            raise ValueError("session not found")
    user_message = messages[-1]["content"] if messages else ""
    if session is None:
        return session, messages, user_message
    history = [
        message.to_dict()
        for message in SessionService.get_recent_session_messages(db, session_id, limit=50)
    ]
    mem_ctx = _memory_context(db, user.id, user_message)
    full_messages = ([{"role": "system", "content": mem_ctx}] if mem_ctx else []) + history + [{"role": "user", "content": user_message}]
    MemoryStore.extract_memories_from_message(db, user.id, user_message, session_id)
    return session, full_messages, user_message


def _persist(db: DBSession, session, user_message: str, response: str) -> None:
    if session is None:
        return
    SessionService.add_message(db, session.id, "user", user_message)
    SessionService.add_message(db, session.id, "assistant", response)
    if SessionService.get_session_message_count(db, session.id) == 2:
        SessionService.auto_generate_title(db, session.id)
    db.commit()


def _runtime_manager():
    from services.model_runtime_manager import get_model_runtime_manager

    return get_model_runtime_manager()


async def run_chat(db: DBSession, runtime: RuntimeRegistry, model: str, messages: list[dict], user: User | None = None, session_id: int | None = None, provider: dict | None = None, model_id: int | None = None, runtime_id: str | None = None) -> dict:
    session, full_messages, user_message = _context(db, user, session_id, messages)
    started = time.monotonic()
    try:
        if provider is None and model_id is not None:
            # Registry-backed path: the runtime manager owns model -> path and
            # auto-loads an idle model before the first token.
            result = await _runtime_manager().chat(
                model_id, full_messages, user_id=user.id if user else None, db=db, runtime=runtime_id
            )
        else:
            result = await _runtime(runtime, provider).chat(model, full_messages)
    except Exception as exc:
        ModelMetricRecorder.record(user_id=user.id if user else None, model=model, remote=provider is not None, latency_ms=(time.monotonic() - started) * 1000, success=False, error=exc)
        raise
    ModelMetricRecorder.record(user_id=user.id if user else None, model=model, remote=provider is not None, latency_ms=(time.monotonic() - started) * 1000, success=True, token_usage=result.get("usage") or result.get("token_usage"))
    response = result.get("content", "")
    _persist(db, session, user_message, response)
    return {"response": response, "session_id": session.id if session else None, **result}


async def stream_chat(db: DBSession, runtime: RuntimeRegistry, model: str, messages: list[dict], user: User | None = None, session_id: int | None = None, provider: dict | None = None, model_id: int | None = None, runtime_id: str | None = None) -> AsyncIterator[dict]:
    session, full_messages, user_message = _context(db, user, session_id, messages)
    if provider is None and model_id is not None:
        # Registry-backed path: one loaded instance shared with /runtime and the
        # OpenAI-compatible API, auto-loaded on first use.
        manager = _runtime_manager()
        user_ref = user.id if user else None
        stream_producer = lambda: manager.stream_chat(  # noqa: E731 - tiny closure
            model_id, full_messages, user_id=user_ref, db=db, runtime=runtime_id
        )
        chat_producer = lambda: manager.chat(  # noqa: E731 - tiny closure
            model_id, full_messages, user_id=user_ref, db=db, runtime=runtime_id
        )
    else:
        selected = _runtime(runtime, provider)
        stream_fn = getattr(selected, "stream_chat", None)
        stream_producer = (lambda: stream_fn(model, full_messages)) if stream_fn is not None else None
        chat_producer = lambda: selected.chat(model, full_messages)  # noqa: E731 - tiny closure
    parts: list[str] = []
    started = time.monotonic()
    try:
        if stream_producer is not None:
            async for chunk in stream_producer():
                parts.append(chunk)
                yield {"type": "delta", "data": chunk}
        else:
            result = await chat_producer()
            content = result.get("content", "")
            parts.append(content)
            yield {"type": "delta", "data": content}
    except Exception as exc:
        ModelMetricRecorder.record(user_id=user.id if user else None, model=model, remote=provider is not None, latency_ms=(time.monotonic() - started) * 1000, success=False, error=exc)
        raise
    full_response = "".join(parts)
    ModelMetricRecorder.record(user_id=user.id if user else None, model=model, remote=provider is not None, latency_ms=(time.monotonic() - started) * 1000, success=True)
    _persist(db, session, user_message, full_response)
    yield {"type": "done", "data": {"response": full_response, "session_id": session.id if session else None}}
