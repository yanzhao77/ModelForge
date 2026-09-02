"""MF-SEC-002: Agent Run session isolation regression tests.

A Run may only bind to a Session owned by the calling user, and the
HistoryProvider must never surface another tenant's session messages.
"""
import os
import sys
import tempfile

# Isolate DB for this test module (imported before core.database is used).
_tmp_db = tempfile.mkdtemp(prefix="mf_sec2_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.errors import SessionNotFoundError  # noqa: E402
from runtime.types import AgentConfig  # noqa: E402


@pytest.fixture
def _db():
    import models.records  # noqa: F401  (registers all tables on Base)
    from core.database import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    db = SessionLocal()
    yield db
    db.close()
    # Reset schema so the module-level temp DB stays clean for later tests.
    Base.metadata.drop_all(engine)


def _make_user(db, username):
    from models.records import User

    u = User(username=username, password_hash="hash")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_session(db, user_id, title="t"):
    from services.session_service import SessionService

    session = SessionService.create_session(db, user_id=user_id, title=title)
    db.commit()
    db.refresh(session)
    return session


def _add_message(db, session_id, role, content):
    from models.records import Message

    m = Message(session_id=session_id, role=role, content=content)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _runtime():
    from repositories.run_repository import SQLAlchemyRunStore
    from runtime.events import EventBus
    from runtime.runtime import AgentRuntime
    from runtime.tools import ToolExecutor, ToolRegistry
    from services.agent_store import DBAgentStore

    rt = AgentRuntime(
        run_store=SQLAlchemyRunStore(),
        agent_store=DBAgentStore(engine=None),
        event_bus=EventBus(),
        tool_runner=ToolExecutor(ToolRegistry()),
    )
    rt.start()
    return rt


class TestSessionHistoryProviderIsolation:
    @pytest.mark.asyncio
    async def test_owner_reads_own_session(self, _db):
        alice = _make_user(_db, "alice")
        session = _make_session(_db, alice.id)
        _add_message(_db, session.id, "user", "private msg")
        from runtime.kb_provider import SessionHistoryProvider

        history = await SessionHistoryProvider().load(session.id, user_id=alice.id)
        assert any(m["content"] == "private msg" for m in history)

    @pytest.mark.asyncio
    async def test_other_user_sees_no_history(self, _db):
        alice = _make_user(_db, "alice")
        bob = _make_user(_db, "bob")
        session = _make_session(_db, alice.id)
        _add_message(_db, session.id, "user", "secret")
        from runtime.kb_provider import SessionHistoryProvider

        history = await SessionHistoryProvider().load(session.id, user_id=bob.id)
        assert history == []

    @pytest.mark.asyncio
    async def test_no_user_id_returns_empty(self, _db):
        alice = _make_user(_db, "alice")
        session = _make_session(_db, alice.id)
        from runtime.kb_provider import SessionHistoryProvider

        history = await SessionHistoryProvider().load(session.id, user_id=None)
        assert history == []


class TestRunSessionBindingIsolation:
    @pytest.mark.asyncio
    async def test_run_binds_own_session(self, _db):
        alice = _make_user(_db, "alice")
        session = _make_session(_db, alice.id)
        rt = _runtime()
        rt.create_agent(AgentConfig(name="bot", model="mock"))
        run = rt.create_run(agent_id="bot", input_text="hi", user_id=alice.id, session_id=session.id, execute=False)
        assert run.session_id == session.id

    @pytest.mark.asyncio
    async def test_run_rejects_other_users_session(self, _db):
        alice = _make_user(_db, "alice")
        bob = _make_user(_db, "bob")
        session = _make_session(_db, alice.id)
        rt = _runtime()
        rt.create_agent(AgentConfig(name="bot", model="mock"))
        with pytest.raises(SessionNotFoundError):
            rt.create_run(agent_id="bot", input_text="hi", user_id=bob.id, session_id=session.id, execute=False)

    @pytest.mark.asyncio
    async def test_run_rejects_inactive_session(self, _db):
        alice = _make_user(_db, "alice")
        session = _make_session(_db, alice.id)
        from services.session_service import SessionService

        SessionService.delete_session(_db, session.id, user_id=alice.id)
        _db.commit()
        rt = _runtime()
        rt.create_agent(AgentConfig(name="bot", model="mock"))
        with pytest.raises(SessionNotFoundError):
            rt.create_run(agent_id="bot", input_text="hi", user_id=alice.id, session_id=session.id, execute=False)