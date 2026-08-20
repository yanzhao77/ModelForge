"""Unified chat service with optional user-scoped remote provider override."""
from collections.abc import AsyncIterator

from models.records import User
from services.memory_store import MemoryStore
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
    history = SessionService.get_session_history(db, session_id, limit=50)
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


async def run_chat(db: DBSession, runtime: RuntimeRegistry, model: str, messages: list[dict], user: User | None = None, session_id: int | None = None, provider: dict | None = None) -> dict:
    session, full_messages, user_message = _context(db, user, session_id, messages)
    result = await _runtime(runtime, provider).chat(model, full_messages)
    response = result.get("content", "")
    _persist(db, session, user_message, response)
    return {"response": response, "session_id": session.id if session else None, **result}


async def stream_chat(db: DBSession, runtime: RuntimeRegistry, model: str, messages: list[dict], user: User | None = None, session_id: int | None = None, provider: dict | None = None) -> AsyncIterator[dict]:
    session, full_messages, user_message = _context(db, user, session_id, messages)
    selected = _runtime(runtime, provider)
    stream_fn = getattr(selected, "stream_chat", None)
    parts: list[str] = []
    if stream_fn is not None:
        async for chunk in stream_fn(model, full_messages):
            parts.append(chunk)
            yield {"type": "delta", "data": chunk}
    else:
        result = await selected.chat(model, full_messages)
        content = result.get("content", "")
        parts.append(content)
        yield {"type": "delta", "data": content}
    full_response = "".join(parts)
    _persist(db, session, user_message, full_response)
    yield {"type": "done", "data": {"response": full_response, "session_id": session.id if session else None}}
