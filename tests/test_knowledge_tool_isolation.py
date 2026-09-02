"""MF-SEC-001: Agent knowledge_search tool must never cross tenant boundaries.

A knowledge tool call lacking an authenticated user context is rejected, and a
user can only retrieve documents owned by that same user (or a collection they
own and bound). This prevents the process-wide in-memory index from becoming a
tenant-isolation bypass.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from core.database import Base
from models.records import (
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeCollectionDocument,
    KnowledgeDocument,
    User,
)
from services.agent_tools import tool_knowledge_search


def _engine_and_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    return engine, db


def _make_user(db, username):
    user = User(username=username, password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _upload_doc(db, user_id, filename, token):
    doc = KnowledgeDocument(
        user_id=user_id,
        filename=filename,
        filetype="text",
        chunk_count=1,
        doc_meta="{}",
    )
    db.add(doc)
    db.flush()
    db.add(
        KnowledgeChunk(
            doc_id=doc.id,
            chunk_index=0,
            content=f"This document belongs to {token} and contains unique marker {token}.",
            meta='{"filename": "%s"}' % filename,
        )
    )
    db.commit()
    return doc


def _context(user_id, knowledge_binding=None):
    return SimpleNamespace(
        user_id=user_id,
        knowledge_binding=knowledge_binding or {"mode": "all"},
    )


@pytest.fixture()
def isolated_kb(monkeypatch):
    """Two users each upload a doc carrying a private marker; counts all chunks."""
    import core.database as cd

    engine, db = _engine_and_db()

    # Point SessionLocal used by the tool at this in-memory engine. monkeypatch
    # guarantees restoration even when an assertion fails.
    monkeypatch.setattr(cd, "engine", engine)
    monkeypatch.setattr(cd, "SessionLocal", sessionmaker(bind=engine))

    # Use a fresh KnowledgeBase instead of the process-wide singleton: other
    # test modules may already have fitted the singleton embedder on unrelated
    # content, which would zero out dot products for these in-memory rows.
    from services.knowledge_base import KnowledgeBase

    monkeypatch.setattr(
        "services.knowledge_base.get_global_kb", lambda: KnowledgeBase()
    )

    alice = _make_user(db, "alice-kb")
    bob = _make_user(db, "bob-kb")
    _upload_doc(db, alice.id, "alice.txt", "ALICE_ONLY_TOKEN")
    _upload_doc(db, bob.id, "bob.txt", "BOB_ONLY_TOKEN")

    yield SimpleNamespace(engine=engine, db=db, alice=alice, bob=bob)
    db.close()


def test_alice_only_sees_her_own_documents(isolated_kb):
    out = tool_knowledge_search("ALICE_ONLY_TOKEN", top_k=5, context=_context(isolated_kb.alice.id))
    assert "ALICE_ONLY_TOKEN" in out
    assert "BOB_ONLY_TOKEN" not in out
    assert "bob.txt" not in out


def test_bob_only_sees_his_own_documents(isolated_kb):
    out = tool_knowledge_search("BOB_ONLY_TOKEN", top_k=5, context=_context(isolated_kb.bob.id))
    assert "BOB_ONLY_TOKEN" in out
    assert "ALICE_ONLY_TOKEN" not in out
    assert "alice.txt" not in out


def test_no_context_is_rejected(isolated_kb):
    out = tool_knowledge_search("ALICE_ONLY_TOKEN", top_k=5, context=None)
    assert "KNOWLEDGE_USER_CONTEXT_REQUIRED" in out
    assert "ALICE_ONLY_TOKEN" not in out


def test_none_user_id_is_rejected(isolated_kb):
    out = tool_knowledge_search("ALICE_ONLY_TOKEN", top_k=5, context=_context(None))
    assert "KNOWLEDGE_USER_CONTEXT_REQUIRED" in out
    assert "ALICE_ONLY_TOKEN" not in out


def test_binding_to_another_users_collection_yields_nothing(isolated_kb):
    # Alice cannot bind Bob's collection and read his docs through the tool.
    bob_collection = KnowledgeCollection(
        id="bob-collection",
        user_id=isolated_kb.bob.id,
        name="bob-col",
    )
    isolated_kb.db.add(bob_collection)
    isolated_kb.db.commit()
    binding = {"mode": "collections", "collection_ids": ["bob-collection"]}
    out = tool_knowledge_search("BOB_ONLY_TOKEN", top_k=5, context=_context(isolated_kb.alice.id, binding))
    assert "BOB_ONLY_TOKEN" not in out


def test_no_other_users_filename_or_id_leaks(isolated_kb):
    out = tool_knowledge_search("BOB_ONLY_TOKEN", top_k=5, context=_context(isolated_kb.alice.id))
    assert "bob.txt" not in out
