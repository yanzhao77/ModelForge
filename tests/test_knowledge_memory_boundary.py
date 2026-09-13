"""Persisted knowledge must not be copied into the process-wide in-memory index.

The singleton used to append every owner's chunks to one shared vector store and
never release them, so a long-running server kept every account's document text
in memory and re-embedded all of it whenever another account started using the
knowledge base.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from core.database import Base  # noqa: E402
from models.records import KnowledgeChunk, KnowledgeDocument, User  # noqa: E402
from services.knowledge_base import KnowledgeBase  # noqa: E402


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _user(db, username: str) -> User:
    user = User(username=username, password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _document(db, user_id: int, filename: str, text: str) -> None:
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
            content=text,
            meta='{"filename": "%s", "chunk_index": 0}' % filename,
        )
    )
    db.commit()


def test_db_query_answers_without_retaining_the_corpus():
    db = _session()
    alice = _user(db, "alice-mem")
    bob = _user(db, "bob-mem")
    _document(db, alice.id, "alice.txt", "alice_marker deployment runbook " * 5)
    _document(db, bob.id, "bob.txt", "bob_marker deployment runbook " * 5)

    kb = KnowledgeBase()
    alice_hits = kb.query("alice_marker", top_k=3, db=db, user_id=alice.id)

    assert alice_hits["total_results"] == 1
    # The rows live in the database only; the singleton must stay empty.
    assert kb.vector_store.documents == []
    assert kb.vector_store.vectors == []

    bob_hits = kb.query("bob_marker", top_k=3, db=db, user_id=bob.id)

    assert bob_hits["total_results"] == 1
    assert "alice_marker" not in bob_hits["results"][0]["text"]
    assert kb.vector_store.documents == []


def test_retrieval_keeps_working_for_a_second_owner():
    db = _session()
    alice = _user(db, "alice-second")
    bob = _user(db, "bob-second")
    _document(db, alice.id, "alice.txt", "alice_marker deployment runbook " * 5)
    _document(db, bob.id, "bob.txt", "bob_marker deployment runbook " * 5)

    kb = KnowledgeBase()
    assert kb.query("alice_marker", top_k=3, db=db, user_id=alice.id)["total_results"] == 1
    assert kb.query("bob_marker", top_k=3, db=db, user_id=bob.id)["total_results"] == 1
    assert kb.query("alice_marker", top_k=3, db=db, user_id=alice.id)["total_results"] == 1
    # One warm-up per owner, regardless of how many queries follow.
    assert kb._loaded_scopes == {alice.id, bob.id}
    assert kb.vector_store.documents == []


def test_local_upload_still_uses_the_in_memory_index(tmp_path):
    path = tmp_path / "local.txt"
    path.write_text("python programming guide. " * 40, encoding="utf-8")

    kb = KnowledgeBase()
    assert kb.upload(str(path), filename="local.txt")["status"] == "ingested"

    assert kb.vector_store.documents
    assert kb.query("python programming", top_k=3)["total_results"] >= 1
    assert kb.stats()["documents"] == 1
    assert kb.chunks("local.txt")

    assert kb.delete_document("local.txt") is True
    assert kb.vector_store.documents == []
    assert kb.stats()["documents"] == 0
