"""Unified chat service: session history + memory injection + runtime + persistence."""
from typing import AsyncIterator, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from models.records import User
from services.memory_store import MemoryStore
from services.session_service import SessionService
from services.runtime_registry import RuntimeRegistry


def _memory_context(db: DBSession, user_id: int, query: str) -> str:
    """Inject relevant cross-session memories into the prompt context."""
    try:
        memories = MemoryStore.get_relevant_memories_for_query(db, user_id, query, limit=3)
        return MemoryStore.format_memories_for_context(memories)
    except Exception:
        return ""


async def run_chat(
    db: DBSession,
    runtime: RuntimeRegistry,
    model: str,
    messages: List[dict],
    user: Optional[User] = None,
    session_id: Optional[int] = None,
) -> Dict:
    """Run a chat turn. Persists to the session when session_id is provided."""
    if session_id is not None:
        if user is None:
            raise PermissionError("login required for session chat")
        session = SessionService.get_session_by_id(db, session_id, user.id)
        if session is None:
            raise ValueError("session not found")
        # rebuild full context: history + memory + new user message
        history = SessionService.get_session_history(db, session_id, limit=50)
        user_message = messages[-1]["content"] if messages else ""
        mem_ctx = _memory_context(db, user.id, user_message)
        full_messages = history
        if mem_ctx:
            full_messages = [{"role": "system", "content": mem_ctx}] + full_messages
        full_messages.append({"role": "user", "content": user_message})
        # extract memories from the user message
        MemoryStore.extract_memories_from_message(db, user.id, user_message, session_id)
    else:
        full_messages = messages

    result = await runtime.chat(model, full_messages)
    response = result.get("content", "")

    if session_id is not None:
        SessionService.add_message(db, session_id, "user", messages[-1]["content"])
        SessionService.add_message(db, session_id, "assistant", response)
        count = SessionService.get_session_message_count(db, session_id)
        if count == 2:
            SessionService.auto_generate_title(db, session_id)
        db.commit()

    return {"response": response, "session_id": session_id, **result}


async def stream_chat(
    db: DBSession,
    runtime: RuntimeRegistry,
    model: str,
    messages: List[dict],
    user: Optional[User] = None,
    session_id: Optional[int] = None,
) -> AsyncIterator[Dict]:
    """Stream chat deltas. Yields {"type": "delta", "data": chunk} ...
    {"type": "done", "data": {...}}."""
    session = None
    if session_id is not None:
        if user is None:
            raise PermissionError("login required for session chat")
        session = SessionService.get_session_by_id(db, session_id, user.id)
        if session is None:
            raise ValueError("session not found")

    user_message = messages[-1]["content"] if messages else ""
    if session is not None:
        history = SessionService.get_session_history(db, session_id, limit=50)
        mem_ctx = _memory_context(db, user.id, user_message)
        full_messages = history
        if mem_ctx:
            full_messages = [{"role": "system", "content": mem_ctx}] + full_messages
        full_messages.append({"role": "user", "content": user_message})
        MemoryStore.extract_memories_from_message(db, user.id, user_message, session_id)
    else:
        full_messages = messages

    runtime_obj = runtime.get()
    stream_fn = getattr(runtime_obj, "stream_chat", None)
    parts: List[str] = []
    if stream_fn is not None:
        async for chunk in stream_fn(model, full_messages):
            parts.append(chunk)
            yield {"type": "delta", "data": chunk}
    else:
        result = await runtime.chat(model, full_messages)
        response = result.get("content", "")
        parts.append(response)
        yield {"type": "delta", "data": response}

    full_response = "".join(parts)
    if session is not None:
        SessionService.add_message(db, session.id, "user", user_message)
        SessionService.add_message(db, session.id, "assistant", full_response)
        count = SessionService.get_session_message_count(db, session.id)
        if count == 2:
            SessionService.auto_generate_title(db, session.id)
        db.commit()

    yield {
        "type": "done",
        "data": {"response": full_response, "session_id": session.id if session else None},
    }