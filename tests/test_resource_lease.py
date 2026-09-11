"""Exclusive inference/training ownership across accounts.

Model files are shared on disk, but only one account may hold the inference
runtime and only one account may run training at a time.
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from api import chat as chat_api
from api import runtime as runtime_api
from main import app
from services.resource_lease import (
    ResourceBusy,
    ResourceLease,
    inference_lease,
    training_lease,
    transient_hold,
)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    _reset_shared_state()


def _reset_shared_state() -> None:
    """Leave no lease or running-process entry behind for the next test."""
    from services.training import get_training_service

    get_training_service()._procs.clear()
    for lease in (inference_lease, training_lease):
        holder = lease.holder()
        if holder is not None:
            lease.release(user_id=holder.user_id)


def _account(client, prefix: str) -> tuple[dict, int, str]:
    username = f"{prefix}-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.com"},
    )
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["token"]}, login.json()["user"]["id"], username


# ---------------------------------------------------------------------------
# Lease semantics
# ---------------------------------------------------------------------------

def test_lease_is_reentrant_for_the_owner_only():
    lease = ResourceLease("inference", "RUNTIME_BUSY", "推理服务")
    first = lease.acquire(user_id=1, username="alpha")
    assert first.created is True

    again = lease.acquire(user_id=1, username="alpha")
    assert again.created is False

    with pytest.raises(ResourceBusy) as busy:
        lease.acquire(user_id=2, username="beta")
    assert busy.value.holder.username == "alpha"
    assert busy.value.to_problem().status_code == 409
    assert busy.value.to_problem().detail["code"] == "RUNTIME_BUSY"


def test_release_by_another_account_is_rejected():
    lease = ResourceLease("inference", "RUNTIME_BUSY", "推理服务")
    lease.acquire(user_id=1, username="alpha")

    with pytest.raises(ResourceBusy):
        lease.release(user_id=2)

    assert lease.release(user_id=1) is True
    assert lease.release(user_id=1) is False


def test_transient_hold_keeps_a_lease_the_owner_already_holds():
    lease = ResourceLease("inference", "RUNTIME_BUSY", "推理服务")
    lease.acquire(user_id=1, username="alpha")

    with transient_hold(lease, user_id=1, username="alpha"):
        assert lease.holder().user_id == 1

    # An explicitly loaded model must survive the chat request that used it.
    assert lease.holder() is not None


def test_transient_hold_releases_a_lease_it_claimed():
    lease = ResourceLease("inference", "RUNTIME_BUSY", "推理服务")

    with transient_hold(lease, user_id=1, username="alpha"):
        assert lease.holder().user_id == 1

    assert lease.holder() is None


# ---------------------------------------------------------------------------
# HTTP integration
# ---------------------------------------------------------------------------

class _FakeRuntime:
    def __init__(self):
        self.loaded: list[str] = []

    async def load(self, model: str) -> dict:
        self.loaded.append(model)
        return {"status": "loaded", "model": model, "content": ""}

    async def stop(self, model: str) -> dict:
        return {"status": "stopped", "model": model, "content": ""}

    def status(self) -> dict:
        return {"default": "fake", "runtimes": {}}


def test_runtime_start_is_exclusive_between_accounts(client, monkeypatch):
    from core.config import settings

    headers_a, _id_a, name_a = _account(client, "leasea")
    headers_b, _id_b, name_b = _account(client, "leaseb")
    monkeypatch.setattr(settings, "runtime_admin_usernames", f"{name_a},{name_b}")
    monkeypatch.setattr(runtime_api, "_runtime", _FakeRuntime())

    assert client.post("/api/v1/runtime/start", json={"model": "m"}, headers=headers_a).status_code == 200

    blocked = client.post("/api/v1/runtime/start", json={"model": "m"}, headers=headers_b)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "RUNTIME_BUSY"
    assert name_a in blocked.json()["detail"]["message"]

    # The owner keeps working; stopping frees the resource for the other account.
    assert client.post("/api/v1/runtime/start", json={"model": "m"}, headers=headers_a).status_code == 200
    assert client.post("/api/v1/runtime/stop", json={"model": "m"}, headers=headers_a).status_code == 200
    assert client.post("/api/v1/runtime/start", json={"model": "m"}, headers=headers_b).status_code == 200


async def _fake_run_chat(*args, **kwargs) -> dict:
    return {"model": "m", "content": "ok"}


def test_chat_is_blocked_while_another_account_owns_inference(client, monkeypatch):
    monkeypatch.setattr(chat_api, "run_chat", _fake_run_chat)
    headers_a, id_a, _name_a = _account(client, "chata")
    headers_b, _id_b, _name_b = _account(client, "chatb")
    inference_lease.acquire(user_id=id_a, username="owner")

    blocked = client.post(
        "/api/v1/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers_b,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "RUNTIME_BUSY"

    # The owning account itself is never blocked by its own lease.
    allowed = client.post(
        "/api/v1/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers_a,
    )
    assert allowed.status_code == 200


def test_chat_releases_inference_when_it_claimed_it(client, monkeypatch):
    monkeypatch.setattr(chat_api, "run_chat", _fake_run_chat)
    headers_a, _id_a, _name_a = _account(client, "freeda")
    headers_b, _id_b, _name_b = _account(client, "freedb")
    payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    assert client.post("/api/v1/chat", json=payload, headers=headers_a).status_code == 200
    assert inference_lease.holder() is None
    # A stateless chat must not lock the machine for the next account.
    assert client.post("/api/v1/chat", json=payload, headers=headers_b).status_code == 200


def test_openai_completions_reports_busy_instead_of_running_inference(client):
    headers_a, id_a, _name_a = _account(client, "oaia")
    headers_b, _id_b, _name_b = _account(client, "oaib")
    inference_lease.acquire(user_id=id_a, username="owner")

    blocked = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers_b,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "RUNTIME_BUSY"


def test_training_start_is_exclusive_between_accounts(client, monkeypatch, tmp_path):
    import services.training as training_module

    monkeypatch.setattr(training_module, "_torch_available", lambda: True)
    monkeypatch.setattr(training_module.TrainingService, "POLL_INTERVAL", 0.1)
    monkeypatch.setattr(training_module.settings, "train_output_dir", str(tmp_path / "outputs"))

    def fake_launch(self, cfg_path, state_path, log_path):
        process = MagicMock()
        process.poll.return_value = None
        process.returncode = None
        process.terminate = MagicMock()
        return process

    monkeypatch.setattr(training_module.TrainingService, "_launch", fake_launch)

    headers_a, _id_a, _name_a = _account(client, "traina")
    headers_b, _id_b, _name_b = _account(client, "trainb")
    dataset = tmp_path / "train.jsonl"
    dataset.write_text('{"text": "hello"}\n', encoding="utf-8")
    payload = {"dataset_path": str(dataset), "base_model": "mock-base", "method": "lora", "confirm": True}

    started = client.post("/api/v1/train/start", json=payload, headers=headers_a)
    assert started.status_code == 200, started.text
    task_id = started.json()["task_id"]

    blocked = client.post("/api/v1/train/start", json=payload, headers=headers_b)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "TRAINING_BUSY"

    assert client.post(f"/api/v1/train/stop/{task_id}", json={"confirm": True}, headers=headers_a).status_code == 200
    assert training_lease.holder() is None
    restarted = client.post("/api/v1/train/start", json=payload, headers=headers_b)
    assert restarted.status_code == 200
    assert (
        client.post(
            f"/api/v1/train/stop/{restarted.json()['task_id']}",
            json={"confirm": True},
            headers=headers_b,
        ).status_code
        == 200
    )
