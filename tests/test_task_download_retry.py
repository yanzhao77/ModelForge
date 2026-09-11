"""Regression coverage for task-center metadata and model-download retry dispatch.

MF-TASK-META: the task record column is ``meta`` while the service argument is
``metadata``. Passing the argument straight into the ORM constructor silently
assigned SQLAlchemy's own ``MetaData`` attribute instead of the column, so every
task created through ``TaskService.create``/``TaskService.retry`` lost its
metadata and the download retry executor could not rebuild its request.
"""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from core.database import SessionLocal
from main import app
from models.records import DownloadTaskRecord, TaskRecord
from services.downloader import get_downloader
from services.task_execution import TaskExecutionService
from services.task_service import TaskService


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth_with_user(client, prefix):
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.com"})
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["token"]}, login.json()["user"]["id"]


def _create_download_task(client, headers, repo_id, filename="model.gguf"):
    response = client.post(
        "/api/v1/tasks",
        json={
            "task_type": "model_download",
            "source": "model_download",
            "title": f"模型下载：{repo_id}",
            "summary": "等待下载",
            "metadata": {"repo_id": repo_id, "filename": filename},
            "cancelable": True,
            "retryable": True,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_created_task_keeps_metadata(client):
    headers, _ = auth_with_user(client, "meta")
    task = _create_download_task(client, headers, "owner/demo-model")
    assert task["metadata"] == {"repo_id": "owner/demo-model", "filename": "model.gguf"}

    listed = client.get("/api/v1/tasks", headers=headers)
    assert listed.status_code == 200, listed.text
    stored = next(item for item in listed.json()["tasks"] if item["task_id"] == task["task_id"])
    assert stored["metadata"]["repo_id"] == "owner/demo-model"


def test_retry_child_inherits_metadata(client):
    headers, _ = auth_with_user(client, "retrymeta")
    task = _create_download_task(client, headers, "owner/demo-model")
    failed = client.post(
        f"/api/v1/tasks/{task['task_id']}/transition",
        json={"status": "FAILED", "summary": "下载失败"},
        headers=headers,
    )
    assert failed.status_code == 200, failed.text

    retried = client.post(f"/api/v1/tasks/{task['task_id']}/retry", json={"confirm": True}, headers=headers)
    assert retried.status_code == 200, retried.text
    child = retried.json()
    assert child["metadata"]["repo_id"] == "owner/demo-model"
    assert child["metadata"]["filename"] == "model.gguf"


def test_download_retry_dispatches_a_real_download(client):
    headers, user_id = auth_with_user(client, "retrylaunch")
    task = _create_download_task(client, headers, "owner/demo-model")
    for status in ("RUNNING", "FAILED"):
        response = client.post(
            f"/api/v1/tasks/{task['task_id']}/transition",
            json={"status": status},
            headers=headers,
        )
        assert response.status_code == 200, response.text

    with pytest.MonkeyPatch.context() as monkeypatch:
        # The dispatch contract is what matters here: no live Hugging Face call.
        monkeypatch.setattr(get_downloader(), "_schedule", lambda task_id: None)
        retried = client.post(f"/api/v1/tasks/{task['task_id']}/retry", json={"confirm": True}, headers=headers)

    assert retried.status_code == 200, retried.text
    child = retried.json()
    assert child["status"] == "RUNNING"
    assert child["error_code"] is None
    download_id = child["metadata"]["execution_task_id"]

    db = SessionLocal()
    try:
        record = db.get(DownloadTaskRecord, download_id)
        assert record is not None
        assert record.user_id == user_id
        assert record.repo_id == "owner/demo-model"
        assert record.filename == "model.gguf"
    finally:
        db.close()


def test_monitor_does_not_fail_a_queued_retry_before_dispatch(client):
    """The retry monitor must not mirror a source the dispatcher has not wired up.

    ``service.retry`` commits the child as QUEUED before ``launch_retry`` creates
    the executor entity, so a monitor tick in that window used to mark the live
    retry FAILED with "下载重试源任务不可用".
    """
    headers, _ = auth_with_user(client, "queuedretry")
    task = _create_download_task(client, headers, "owner/demo-model")
    for status in ("RUNNING", "FAILED"):
        response = client.post(
            f"/api/v1/tasks/{task['task_id']}/transition",
            json={"status": status},
            headers=headers,
        )
        assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        parent = db.query(TaskRecord).filter_by(task_id=task["task_id"]).first()
        child = TaskService().retry(db, parent)
        assert child.status == "QUEUED"

        assert TaskExecutionService().synchronize(db, child) is False
        db.refresh(child)
        assert child.status == "QUEUED"
        assert child.error_code is None
    finally:
        db.close()
