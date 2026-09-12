"""Regression coverage for legacy train/agent task projections."""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from core.database import SessionLocal
from main import app
from models.records import AgentRun, TaskEvent, TaskOutbox, TaskRecord, TrainTask


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


def test_task_list_projects_training_and_agent_runs(client):
    headers, user_id = auth_with_user(client, "projection")
    train_id = uuid.uuid4().hex[:12]
    run_id = uuid.uuid4().hex
    db = SessionLocal()
    try:
        db.add(TrainTask(
            task_id=train_id, user_id=user_id, base_model="qwen-test", method="lora",
            config="{}", status="running", progress=48, total_epochs=3, current_epoch=2,
            output_dir="/tmp/out", log_path="/tmp/log",
        ))
        db.add(AgentRun(
            run_id=run_id, agent_id="researcher", user_id=user_id, status="COMPLETED",
            input="summarize market", output="done", model="mock",
        ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/tasks", headers=headers)
    assert response.status_code == 200, response.text
    tasks = response.json()["tasks"]
    training = next(task for task in tasks if task["source"] == "training" and task["source_task_id"] == train_id)
    agent = next(task for task in tasks if task["source"] == "agent_runtime" and task["source_task_id"] == run_id)
    assert training["status"] == "RUNNING"
    assert training["progress_percent"] == 48
    assert training["cancelable"] is True
    assert agent["status"] == "SUCCEEDED"
    assert agent["retryable"] is False


def test_task_center_cancel_stops_the_owning_training_and_settles_the_row(client):
    """Cancelling now reaches the training subprocess instead of only asking."""
    headers, user_id = auth_with_user(client, "cancelprojection")
    train_id = uuid.uuid4().hex[:12]
    db = SessionLocal()
    try:
        db.add(TrainTask(
            task_id=train_id, user_id=user_id, base_model="qwen-test", method="lora",
            config="{}", status="running", progress=10, total_epochs=3, current_epoch=1,
            output_dir="/tmp/out", log_path="/tmp/log",
        ))
        db.commit()
    finally:
        db.close()

    first = client.get("/api/v1/tasks", headers=headers).json()["tasks"]
    task = next(item for item in first if item["source_task_id"] == train_id)
    cancelled = client.post(f"/api/v1/tasks/{task['task_id']}/cancel", json={"confirm": True}, headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    refreshed = client.get("/api/v1/tasks", headers=headers).json()["tasks"]
    task = next(item for item in refreshed if item["source_task_id"] == train_id)
    assert task["status"] == "CANCELLED"

    db = SessionLocal()
    try:
        source = db.query(TrainTask).filter_by(task_id=train_id, user_id=user_id).one()
        assert source.status == "stopped"
    finally:
        db.close()


def test_projection_does_not_revive_a_cancellation_request(client):
    """A stale RUNNING source must not resurrect a row that is awaiting cancel."""
    from services.task_service import TaskService

    _headers, user_id = auth_with_user(client, "cancelguard")
    source_task_id = f"cancelled-download-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        service = TaskService()
        task = service.create(
            db,
            user_id=user_id,
            task_type="model_download",
            source="model_download",
            source_task_id=source_task_id,
            title="guard",
            cancelable=True,
            retryable=True,
        )
        # The row has to be live before a cancel can be requested for it.
        service.project(
            db,
            user_id=user_id,
            task_type="model_download",
            source="model_download",
            source_task_id=source_task_id,
            title="guard",
            status="RUNNING",
            cancelable=True,
            retryable=True,
        )
        task = service.request_cancel(db, db.query(TaskRecord).filter_by(task_id=task.task_id).one())

        # A worker that has not observed the request yet keeps reporting RUNNING.
        service.project(
            db,
            user_id=user_id,
            task_type="model_download",
            source="model_download",
            source_task_id=source_task_id,
            title="guard",
            status="RUNNING",
            cancelable=True,
            retryable=True,
        )

        assert db.query(TaskRecord).filter_by(task_id=task.task_id).one().status == "CANCEL_REQUESTED"
    finally:
        db.close()


def test_unchanged_legacy_projection_does_not_amplify_events_or_outbox(client):
    headers, user_id = auth_with_user(client, "projectiondiff")
    train_id = uuid.uuid4().hex[:12]
    db = SessionLocal()
    try:
        db.add(TrainTask(
            task_id=train_id, user_id=user_id, base_model="qwen-test", method="lora",
            config="{}", status="running", progress=25, total_epochs=4, current_epoch=1,
            output_dir="/tmp/out", log_path="/tmp/log",
        ))
        db.commit()
    finally:
        db.close()

    assert client.get("/api/v1/tasks", headers=headers).status_code == 200
    db = SessionLocal()
    try:
        task = db.query(TaskRecord).filter_by(user_id=user_id, source_task_id=train_id).one()
        baseline_version = task.version
        baseline_events = db.query(TaskEvent).filter_by(user_id=user_id).count()
        baseline_outbox = db.query(TaskOutbox).filter_by(user_id=user_id).count()
    finally:
        db.close()

    for _ in range(4):
        assert client.get("/api/v1/tasks", headers=headers).status_code == 200

    db = SessionLocal()
    try:
        task = db.query(TaskRecord).filter_by(user_id=user_id, source_task_id=train_id).one()
        assert task.version == baseline_version
        assert db.query(TaskEvent).filter_by(user_id=user_id).count() == baseline_events
        assert db.query(TaskOutbox).filter_by(user_id=user_id).count() == baseline_outbox

        source = db.query(TrainTask).filter_by(task_id=train_id, user_id=user_id).one()
        source.progress = 50
        source.current_epoch = 2
        db.commit()
    finally:
        db.close()

    assert client.get("/api/v1/tasks", headers=headers).status_code == 200
    db = SessionLocal()
    try:
        task = db.query(TaskRecord).filter_by(user_id=user_id, source_task_id=train_id).one()
        assert task.progress_percent == 50
        assert task.version == baseline_version
        assert db.query(TaskEvent).filter_by(user_id=user_id).count() == baseline_events + 1
        assert db.query(TaskOutbox).filter_by(user_id=user_id).count() == baseline_outbox + 1
    finally:
        db.close()
