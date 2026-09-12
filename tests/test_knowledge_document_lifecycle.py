"""Re-uploading a knowledge document must replace it, not shadow it."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

from fastapi.testclient import TestClient

_tmp_db = tempfile.mkdtemp(prefix="mf_kb_life_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "knowledge-lifecycle-secret-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402


def _headers(client: TestClient) -> dict:
    username = f"kblife-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client: TestClient, headers: dict, content: str) -> None:
    response = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("guide.txt", content.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ingested"


def test_reupload_replaces_the_previous_copy():
    with TestClient(app) as client:
        headers = _headers(client)
        _upload(client, headers, "第一版内容。" * 20)
        _upload(client, headers, "第二版内容。" * 20)

        documents = client.get("/api/v1/knowledge/documents", headers=headers).json()
        matches = [doc for doc in documents if doc["filename"] == "guide.txt"]
        assert len(matches) == 1

        chunks = client.get("/api/v1/knowledge/documents/guide.txt/chunks", headers=headers).json()
        assert chunks
        assert all("第二版内容" in chunk["content"] for chunk in chunks)

        results = client.post(
            "/api/v1/knowledge/query",
            json={"question": "第二版内容", "top_k": 3},
            headers=headers,
        ).json()["results"]
        assert results
        assert all("第一版内容" not in item["text"] for item in results)


def test_delete_removes_every_copy_of_the_document():
    with TestClient(app) as client:
        headers = _headers(client)
        _upload(client, headers, "旧版本内容。" * 20)
        _upload(client, headers, "新版本内容。" * 20)

        deleted = client.delete("/api/v1/knowledge/documents/guide.txt", headers=headers)
        assert deleted.status_code == 200, deleted.text

        documents = client.get("/api/v1/knowledge/documents", headers=headers).json()
        assert all(doc["filename"] != "guide.txt" for doc in documents)
        assert client.get("/api/v1/knowledge/documents/guide.txt/chunks", headers=headers).json() == []
        missing = client.delete("/api/v1/knowledge/documents/guide.txt", headers=headers)
        assert missing.status_code == 404
