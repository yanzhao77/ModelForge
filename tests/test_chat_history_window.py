"""The chat context window must carry the newest turns of a conversation."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

from fastapi.testclient import TestClient

_tmp_db = tempfile.mkdtemp(prefix="mf_chatwin_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "chat-window-test-secret-value-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402
from services.runtime_registry import RuntimeRegistry  # noqa: E402


def test_session_chat_sends_the_newest_history_window(monkeypatch):
    captured: dict[str, list] = {}

    async def fake_chat(self, model, messages, **kwargs):
        captured["messages"] = list(messages)
        return {"model": model, "content": "ok"}

    monkeypatch.setattr(RuntimeRegistry, "chat", fake_chat)
    username = f"chatwindow-{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
        )
        token = client.post(
            "/api/v1/auth/login", json={"username": username, "password": "secret123"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        session_id = client.post("/api/v1/sessions", json={"title": "long"}, headers=headers).json()["id"]
        for index in range(1, 61):
            client.post(
                f"/api/v1/sessions/{session_id}/messages",
                json={"role": "user" if index % 2 else "assistant", "content": f"m{index}"},
                headers=headers,
            )

        response = client.post(
            "/api/v1/chat",
            json={"model": "m", "messages": [{"role": "user", "content": "NEW"}], "session_id": session_id},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    seen = [message["content"] for message in captured["messages"]]
    assert "NEW" in seen
    # The newest turns are inside the window and the oldest ones fall out of it.
    assert "m60" in seen
    assert "m1" not in seen
