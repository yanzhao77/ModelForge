"""Stored memories must be recallable from natural sentences."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

from fastapi.testclient import TestClient

_tmp_db = tempfile.mkdtemp(prefix="mf_memrecall_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "memory-recall-test-secret-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import SessionLocal, init_db  # noqa: E402
from main import app  # noqa: E402
from models.records import User  # noqa: E402
from services.memory_store import MemoryStore  # noqa: E402
from services.runtime_registry import RuntimeRegistry  # noqa: E402

init_db()


def test_query_terms_split_chinese_runs_into_overlapping_bigrams():
    terms = MemoryStore._query_terms("我还喜欢茶吗")

    assert "喜欢" in terms
    assert "我还" in terms


def test_memory_is_recalled_from_a_sentence_and_not_from_an_unrelated_one():
    db = SessionLocal()
    try:
        user = User(username=f"memrecall-{uuid.uuid4().hex[:10]}", password_hash="hash")
        db.add(user)
        db.commit()
        db.refresh(user)
        MemoryStore.extract_memories_from_message(db, user.id, "我喜欢喝茶。")

        assert MemoryStore.get_relevant_memories_for_query(db, user.id, "我还喜欢茶吗")
        assert MemoryStore.get_relevant_memories_for_query(db, user.id, "今天天气如何") == []
    finally:
        db.close()


def test_recalled_memory_reaches_the_chat_context(monkeypatch):
    captured: dict[str, list] = {}

    async def fake_chat(self, model, messages, **kwargs):
        captured["messages"] = list(messages)
        return {"model": model, "content": "ok"}

    monkeypatch.setattr(RuntimeRegistry, "chat", fake_chat)
    username = f"memctx-{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
        )
        token = client.post(
            "/api/v1/auth/login", json={"username": username, "password": "secret123"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        session_id = client.post("/api/v1/sessions", json={"title": "memory"}, headers=headers).json()["id"]
        for message in ("我喜欢喝茶。", "我还喜欢茶吗？"):
            response = client.post(
                "/api/v1/chat",
                json={"model": "m", "messages": [{"role": "user", "content": message}], "session_id": session_id},
                headers=headers,
            )
            assert response.status_code == 200, response.text

    system_messages = [item["content"] for item in captured["messages"] if item["role"] == "system"]
    assert any("[用户记忆]" in content for content in system_messages)
