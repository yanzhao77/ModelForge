"""OpenAI-style video API tests with the deterministic fake runtime."""
from __future__ import annotations

import os
import sys
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from main import app
from services.model_capability_registry import (
    get_capability_registry,
    set_capability_registry,
)
from services.video_runtime import (
    RuntimeLoadResult,
    RuntimeStopResult,
    VideoGenerationResult,
    VideoRuntimeError,
    VideoRuntimeProbe,
    file_sha256,
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MODELFORGE_ENABLE_FAKE_VIDEO_RUNTIME", "1")
    set_capability_registry(None)
    with TestClient(app) as test_client:
        yield test_client
    set_capability_registry(None)


def write_wan_snapshot(root):
    root.mkdir(parents=True)
    (root / "model_index.json").write_text(
        '{"_class_name":"WanPipeline","scheduler":["diffusers","UniPCMultistepScheduler"],"text_encoder":["transformers","UMT5EncoderModel"],"tokenizer":["transformers","T5TokenizerFast"],"transformer":["diffusers","WanTransformer3DModel"],"vae":["diffusers","AutoencoderKLWan"]}',
        encoding="utf-8",
    )
    for child in ("scheduler", "text_encoder", "tokenizer", "transformer", "vae"):
        (root / child).mkdir()
    (root / "scheduler" / "scheduler_config.json").write_text("{}", encoding="utf-8")
    (root / "text_encoder" / "config.json").write_text('{"architectures":["UMT5EncoderModel"]}', encoding="utf-8")
    (root / "tokenizer" / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (root / "tokenizer" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "transformer" / "config.json").write_text('{"_class_name":"WanTransformer3DModel"}', encoding="utf-8")
    (root / "transformer" / "diffusion_pytorch_model.safetensors.index.json").write_text('{"weight_map":{"x":"diffusion_pytorch_model-00001-of-00001.safetensors"}}', encoding="utf-8")
    (root / "transformer" / "diffusion_pytorch_model-00001-of-00001.safetensors").write_bytes(b"x")
    (root / "text_encoder" / "model.safetensors.index.json").write_text('{"weight_map":{"x":"model-00001-of-00001.safetensors"}}', encoding="utf-8")
    (root / "text_encoder" / "model-00001-of-00001.safetensors").write_bytes(b"x")
    (root / "vae" / "config.json").write_text('{"_class_name":"AutoencoderKLWan"}', encoding="utf-8")
    (root / "vae" / "diffusion_pytorch_model.safetensors").write_bytes(b"x")


class CapturingWanRuntime:
    runtime_name = "wan-diffusers"

    def __init__(self):
        self.prompts = []

    async def probe(self, model):
        return VideoRuntimeProbe(True, "READY", "mock wan ready", {"path": model.local_path})

    async def load(self, model):
        return RuntimeLoadResult("loadable", model.model_id, self.runtime_name)

    async def generate(self, request, *, progress, cancellation, output_path):
        assert cancellation() is False
        self.prompts.append(request.prompt)
        await progress("inference", 50, request.num_inference_steps)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mock-mp4:" + request.prompt.encode("utf-8"))
        await progress("complete", 100, request.num_inference_steps)
        return VideoGenerationResult(output_path, file_sha256(output_path), output_path.stat().st_size, 1000)

    async def unload(self, model_id):
        return RuntimeStopResult("stopped", model_id, self.runtime_name)

    async def shutdown(self):
        return None


class CancelableWanRuntime(CapturingWanRuntime):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.cancel_seen = threading.Event()

    async def generate(self, request, *, progress, cancellation, output_path):
        self.prompts.append(request.prompt)
        self.started.set()
        await progress("inference", 10, request.num_inference_steps)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if cancellation():
                self.cancel_seen.set()
                raise VideoRuntimeError("VIDEO_CANCELLED", "Video generation was cancelled.")
            time.sleep(0.02)
        raise VideoRuntimeError("VIDEO_TEST_TIMEOUT", "Cancellation did not arrive in time.")


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


def api_auth(client: TestClient, jwt_headers: dict[str, str]) -> dict[str, str]:
    issued = client.post("/api/v1/local-api/keys", json={"name": "video"}, headers=jwt_headers)
    assert issued.status_code == 200, issued.text
    return {"Authorization": "Bearer " + issued.json()["secret"]}


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


def test_fake_video_is_not_registered_without_explicit_enable(monkeypatch):
    monkeypatch.delenv("MODELFORGE_ENABLE_FAKE_VIDEO_RUNTIME", raising=False)
    set_capability_registry(None)
    try:
        model_ids = {model.model_id for model in get_capability_registry().video_models()}
        assert "fake-video" not in model_ids
    finally:
        set_capability_registry(None)


def test_desktop_video_models_accept_login_without_an_api_key(client):
    headers = auth(client, "desktopmodels")
    response = client.get("/api/v1/videos/models", headers=headers)
    assert response.status_code == 200, response.text
    fake = next(item for item in response.json()["data"] if item["id"] == "fake-video")
    assert fake["modelforge"]["capabilities"] == ["video_generation"]
    assert fake["modelforge"]["readiness"] == "ready"
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.get("/v1/models", headers=headers).status_code == 401
    assert client.post("/v1/videos", json=video_payload(), headers=headers).status_code == 401


def test_desktop_video_routes_require_login(client):
    assert client.get("/api/v1/videos/models").status_code == 401
    assert client.post("/api/v1/videos", json=video_payload()).status_code == 401
    assert client.get("/api/v1/videos/video_missing").status_code == 401
    assert client.get("/api/v1/videos/video_missing/content").status_code == 401
    assert client.post("/api/v1/videos/video_missing/cancel").status_code == 401


def test_desktop_video_lifecycle_and_user_isolation(client):
    headers = auth(client, "desktopvideo")
    other = auth(client, "desktopother")
    response = client.post("/api/v1/videos", json=video_payload(), headers=headers)
    assert response.status_code == 202, response.text
    path = f"/api/v1/videos/{response.json()['id']}"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = client.get(path, headers=headers)
        assert status.status_code == 200, status.text
        if status.json()["status"] == "completed":
            break
        time.sleep(0.05)
    assert status.json()["status"] == "completed"
    content = client.get(f"{path}/content", headers=headers)
    assert content.status_code == 200, content.text
    assert b"ModelForge fake video" in content.content
    assert client.get(path, headers=other).status_code == 404
    assert client.get(f"{path}/content", headers=other).status_code == 404
    assert client.post(f"{path}/cancel", headers=other).status_code == 404
    assert client.post(f"{path}/cancel", headers=headers).status_code == 200


def test_models_lists_video_capabilities(client):
    headers = api_auth(client, auth(client, "videomodels"))
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
    jwt_headers = auth(client, "videoflow")
    headers = api_auth(client, jwt_headers)
    response = client.post("/v1/videos", json=video_payload(), headers={**headers, "Idempotency-Key": uuid.uuid4().hex})
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["object"] == "video"
    assert created["status"] in {"queued", "processing"}
    assert created["resolved"] == {"frames": 49, "fps": 8, "size": "720x480", "num_inference_steps": 3, "seed": 42}
    assert "prompt" not in created

    complete = wait_for_status(client, headers, created["id"], "completed")
    assert complete["progress"] == 100

    task = client.get(f"/api/v1/tasks/{complete['task_id']}", headers=jwt_headers)
    assert task.status_code == 200, task.text
    assert task.json()["task_type"] == "video_generation"
    assert task.json()["status"] == "SUCCEEDED"
    assert task.json()["metadata"]["video_id"] == created["id"]

    content = client.get(f"/v1/videos/{created['id']}/content", headers=headers)
    assert content.status_code == 200, content.text
    assert content.headers["content-type"].startswith("video/mp4")
    assert b"ModelForge fake video" in content.content


def test_video_idempotency_replay_and_conflict(client):
    headers = api_auth(client, auth(client, "videoidem"))
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
    headers = api_auth(client, auth(client, "videocog"))
    response = client.post("/v1/videos", json=video_payload(model="cogvideox-2b"), headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VIDEO_MODEL_NOT_READY"


def test_video_jobs_are_user_isolated(client):
    alice = api_auth(client, auth(client, "videoalice"))
    bob = api_auth(client, auth(client, "videobob"))
    created = client.post("/v1/videos", json=video_payload(), headers=alice).json()
    assert client.get(f"/v1/videos/{created['id']}", headers=bob).status_code == 404
    assert client.get(f"/v1/videos/{created['id']}/content", headers=bob).status_code == 404


def test_local_wan_video_model_uses_full_prompt_in_runtime(client, tmp_path):
    jwt_headers = auth(client, "localwan")
    headers = api_auth(client, jwt_headers)
    snapshot = tmp_path / "neutral-name"
    write_wan_snapshot(snapshot)
    registered = client.post("/api/v1/models/local/register", json={"path": str(snapshot)}, headers=jwt_headers)
    assert registered.status_code == 200, registered.text
    model_id = registered.json()["model"]["id"]
    runtime = CapturingWanRuntime()
    registry = get_capability_registry()
    registry.register_video_runtime(runtime)
    try:
        payload = video_payload(model=f"local:{model_id}", prompt="complete prompt reaches runtime", seconds=1, fps=4, size="256x256", num_inference_steps=1)
        created = client.post("/v1/videos", json=payload, headers=headers)
        assert created.status_code == 202, created.text
        complete = wait_for_status(client, headers, created.json()["id"], "completed")
        assert complete["resolved"]["frames"] == 5
        assert runtime.prompts == ["complete prompt reaches runtime"]
    finally:
        set_capability_registry(None)


def test_local_wan_video_job_can_be_cancelled_while_running(client, tmp_path):
    jwt_headers = auth(client, "localwancancel")
    headers = api_auth(client, jwt_headers)
    snapshot = tmp_path / "neutral-cancel-name"
    write_wan_snapshot(snapshot)
    registered = client.post("/api/v1/models/local/register", json={"path": str(snapshot)}, headers=jwt_headers)
    assert registered.status_code == 200, registered.text
    model_id = registered.json()["model"]["id"]
    runtime = CancelableWanRuntime()
    registry = get_capability_registry()
    registry.register_video_runtime(runtime)
    try:
        payload = video_payload(model=f"local:{model_id}", prompt="cancel this complete prompt", seconds=1, fps=4, size="256x256", num_inference_steps=1)
        created = client.post("/v1/videos", json=payload, headers=headers)
        assert created.status_code == 202, created.text
        assert runtime.started.wait(timeout=2)
        cancelled = client.post(f"/v1/videos/{created.json()['id']}/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        final = wait_for_status(client, headers, created.json()["id"], "cancelled", timeout=6)
        assert final["status"] == "cancelled"
        assert runtime.cancel_seen.is_set()
    finally:
        set_capability_registry(None)
