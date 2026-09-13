"""A slow knowledge upload must not stop the rest of the API from answering.

Parsing, chunking, embedding and the DB write used to run on the event loop
thread, so one large upload froze health checks, task streams and cancellation
for every account in the process.

The requests go through ``httpx.ASGITransport`` instead of ``TestClient``: the
test client serialises concurrent requests, which hides whether the *app* is
blocking. The lifespan is replaced by the two calls the knowledge routes need.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import uuid

import pytest

_tmp_db = tempfile.mkdtemp(prefix="mf_kb_live_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "knowledge-liveness-secret-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import api.knowledge as knowledge_api  # noqa: E402
import httpx  # noqa: E402
from core.database import init_db  # noqa: E402
from main import app  # noqa: E402
from services.knowledge_base import get_global_kb  # noqa: E402

SLOW_UPLOAD_SECONDS = 1.5
# Generous compared with the ~30ms warmed-up health check, tight enough that a
# blocked event loop (which waits for the whole upload) fails the test.
LIVENESS_DEADLINE_SECONDS = 0.8
CJK_PARAGRAPH = "摘要: " + "这是一段很长的中文说明文字，用来验证上传路径不会卡住服务。" * 30


def _bootstrap() -> None:
    """``httpx.ASGITransport`` does not run the app lifespan; do the parts we need."""
    init_db()
    knowledge_api.set_knowledge_base(get_global_kb())


async def _client() -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    username = f"kblive-{uuid.uuid4().hex[:8]}"
    await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = (
        await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "secret123"}
        )
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.mark.asyncio
async def test_health_check_answers_while_an_upload_is_running(monkeypatch):
    _bootstrap()
    request_seen: list[str] = []

    def slow_upload(path, **kwargs):
        request_seen.append(str(kwargs.get("filename")))
        time.sleep(SLOW_UPLOAD_SECONDS)
        return {"status": "ingested", "file": str(path), "chunks": 1, "type": "text"}

    client = await _client()
    try:
        # Absorb one-off warm-up (lazy imports, connection setup) before timing.
        assert (await client.get("/healthz")).status_code == 200
        monkeypatch.setattr(knowledge_api._get_kb(), "upload", slow_upload)

        upload = asyncio.create_task(
            client.post(
                "/api/v1/knowledge/upload",
                files={"file": ("slow.txt", b"hello world", "text/plain")},
            )
        )
        await asyncio.sleep(0.2)
        assert not upload.done(), "the upload finished before liveness was probed"

        started = time.monotonic()
        health = await asyncio.wait_for(
            client.get("/healthz"), timeout=LIVENESS_DEADLINE_SECONDS
        )
        elapsed = time.monotonic() - started

        assert health.status_code == 200
        assert elapsed < LIVENESS_DEADLINE_SECONDS, (
            f"health check waited {elapsed:.2f}s for a running upload"
        )
        assert (await upload).status_code == 200
        assert request_seen == ["slow.txt"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_long_cjk_upload_returns_through_the_api():
    """End-to-end guard: the triggering document must be ingested, not hang."""
    _bootstrap()
    client = await _client()
    try:
        response = await asyncio.wait_for(
            client.post(
                "/api/v1/knowledge/upload",
                files={"file": ("zh.md", CJK_PARAGRAPH.encode("utf-8"), "text/markdown")},
            ),
            timeout=15,
        )
    finally:
        await client.aclose()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ingested"
