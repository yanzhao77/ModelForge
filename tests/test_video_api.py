"""OpenAI-style video API tests with the deterministic fake runtime."""
from __future__ import annotations

import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth(client: TestClient, prefix: str) -> dict[str, str]:
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.com"},
    )
    assert response.status_code in {200, 201}, response.text
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["token"]}


def wait_for_status(client: TestClient, headers: dict[str, str], video_id: str, status: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/v1/videos/{video_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {status}; last={last}")


def video_payload(**overrides):
    payload = {
        "model": "fake-video",
        "prompt": "A small test clip for ModelForge",
        "seconds": 6,
        "fps": 8,
        "size": "720x480",
        "num_inference_steps": 3,
        "seed": 42,
    }
    payload.update(overrides)
    return payload


def test_video_routes_require_authentication(client):
    assert client.post("/v1/videos", json=video_payload()).status_code == 401
    assert client.get("/v1/videos/video_missing").status_code == 401
    assert client.get("/v1/videos/video_missing/content").status_code == 401
    assert client.post("/v1/videos/video_missing/cancel").status_code == 401


def test_models_lists_video_capabilities(client):
    headers = auth(client, "videomodels")
    response = client.get("/v1/models", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    fake = next(item for item in data if item["id"] == "fake-video")
    assert fake["modelforge"]["capabilities"] == ["video_generation"]
    assert fake["modelforge"]["readiness"] == "ready"
    cog = next(item for item in data if item["id"] == "cogvideox-2b")
    assert cog["modelforge"]["capabilities"] == ["video_generation"]
    assert cog["modelforge"]["readiness"] in {"ready", "unavailable"}


def test_fake_video_submit_status_content_and_task_projection(client):
    headers = auth(client, "videoflow")
    response = client.post("/v1/videos", json=video_payload(), headers={**headers, "Idempotency-Key": uuid.uuid4().hex})
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["object"] == "video"
    assert created["status"] in {"queued", "processing"}
    assert created["resolved"] == {"frames": 49, "fps": 8, "size": "720x480", "num_inference_steps": 3, "seed": 42}
    assert "prompt" not in created

    complete = wait_for_status(client, headers, created["id"], "completed")
    assert complete["progress"] == 100

    task = client.get(f"/api/v1/tasks/{complete['task_id']}", headers=headers)
    assert task.status_code == 200, task.text
    assert task.json()["task_type"] == "video_generation"
    assert task.json()["status"] == "SUCCEEDED"
    assert task.json()["metadata"]["video_id"] == created["id"]

    content = client.get(f"/v1/videos/{created['id']}/content", headers=headers)
    assert content.status_code == 200, content.text
    assert content.headers["content-type"].startswith("video/mp4")
    assert b"ModelForge fake video" in content.content


def test_video_idempotency_replay_and_conflict(client):
    headers = auth(client, "videoidem")
    key = uuid.uuid4().hex
    first = client.post("/v1/videos", json=video_payload(seed=1), headers={**headers, "Idempotency-Key": key})
    assert first.status_code == 202, first.text
    replay = client.post("/v1/videos", json=video_payload(seed=1), headers={**headers, "Idempotency-Key": key})
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == first.json()["id"]

    conflict = client.post("/v1/videos", json=video_payload(seed=2), headers={**headers, "Idempotency-Key": key})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_unsupported_cogvideox_model_is_not_queued_without_readiness(client):
    headers = auth(client, "videocog")
    response = client.post("/v1/videos", json=video_payload(model="cogvideox-2b"), headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VIDEO_MODEL_NOT_READY"


def test_video_jobs_are_user_isolated(client):
    alice = auth(client, "videoalice")
    bob = auth(client, "videobob")
    created = client.post("/v1/videos", json=video_payload(), headers=alice).json()
    assert client.get(f"/v1/videos/{created['id']}", headers=bob).status_code == 404
    assert client.get(f"/v1/videos/{created['id']}/content", headers=bob).status_code == 404
