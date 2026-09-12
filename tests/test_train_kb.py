"""Integration tests: datasets API, training task flow, knowledge base persistence + RAG."""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(prefix="mf_tk_"), "test.db"))
os.environ.setdefault("JWT_SECRET", "integration-test-secret")

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app
from services.runtime_registry import RuntimeRegistry


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register(client, username, password="secret123"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": f"{username}@example.com"},
    )


def _login(client, username, password="secret123") -> str:
    _register(client, username, password)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestDatasetsApi:
    def test_upload_list_get_delete(self, client):
        token = _login(client, "dsapi")
        headers = _auth(token)
        content = b'{"question": "q1", "answer": "a1"}\n' * 4
        r = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("samples.jsonl", content, "application/json")},
            data={"name": "接口数据集"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "parsed"
        assert data["row_count"] == 4
        ds_id = data["id"]

        r = client.get("/api/v1/datasets", headers=headers)
        assert any(d["id"] == ds_id for d in r.json())

        r = client.get(f"/api/v1/datasets/{ds_id}", headers=headers)
        assert r.json()["name"] == "接口数据集"

        r = client.post(f"/api/v1/datasets/{ds_id}/validate", headers=headers)
        assert r.json()["ok"] is True

        r = client.delete(f"/api/v1/datasets/{ds_id}", headers=headers)
        assert r.status_code == 200
        assert client.get(f"/api/v1/datasets/{ds_id}", headers=headers).status_code == 404

    def test_upload_rejects_bad_type(self, client):
        token = _login(client, "dsapi2")
        r = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_datasets_require_auth(self, client):
        assert client.get("/api/v1/datasets").status_code == 401

    def test_missing_dataset_uses_the_stable_problem_contract(self, client):
        token = _login(client, "dsmissing")
        headers = _auth(token)
        response = client.post("/api/v1/datasets/999999/validate", headers=headers)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "DATASET_NOT_FOUND"
        assert "X-Correlation-ID" in response.headers


class TestTrainingFlow:
    @pytest.fixture(autouse=True)
    def _mock_training(self, monkeypatch, tmp_path):
        import services.training as tr
        monkeypatch.setattr(tr, "_torch_available", lambda: True)
        monkeypatch.setattr(tr.TrainingService, "POLL_INTERVAL", 0.1)

        def fake_launch(self, cfg_path, state_path, log_path):
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump({"status": "done", "progress": 100, "epoch": 1, "loss": 0.5}, f)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("mock training completed\n")
            p = MagicMock()
            p.poll.return_value = 0
            p.returncode = 0
            p.terminate = MagicMock()
            return p
        monkeypatch.setattr(tr.TrainingService, "_launch", fake_launch)
        monkeypatch.setattr(settings_mod(), "train_output_dir", str(tmp_path / "outputs"))

    def test_start_status_register(self, client):
        token = _login(client, "trainapi")
        headers = _auth(token)
        content = b'{"text": "hello world"}\n' * 5
        r = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("train.jsonl", content, "application/json")},
            headers=headers,
        )
        ds_id = r.json()["id"]

        r = client.post(
            "/api/v1/train/start",
            json={"dataset_id": ds_id, "base_model": "mock-base", "method": "lora", "epochs": 1, "batch_size": 1, "confirm": True},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        task_id = r.json()["task_id"]

        # wait for the poll thread to pick up the fake "done" state
        for _ in range(50):
            status = client.get(f"/api/v1/train/status/{task_id}", headers=headers).json()
            if status["status"] == "done":
                break
            time.sleep(0.1)
        assert status["status"] == "done", status
        assert status["progress"] == 100
        assert status["loss"] == 0.5
        assert "mock training completed" in "\n".join(status["log_tail"])

        r = client.post(f"/api/v1/train/{task_id}/register-model", json={"confirm": True}, headers=headers)
        assert r.status_code == 200, r.text
        models = client.get("/api/v1/models", headers=headers).json()
        assert any(m["provider"] == "training" for m in models)

        r = client.get("/api/v1/train/tasks", headers=headers)
        assert any(t["task_id"] == task_id for t in r.json())

    def test_templates(self, client):
        token = _login(client, "trainapi2")
        r = client.get("/api/v1/train/templates", headers=_auth(token))
        assert r.status_code == 200
        assert "lora" in r.json()
        assert "full" in r.json()
        assert r.json()["lora"]["lora_r"] == 8

    def test_stop(self, client, monkeypatch):
        import services.training as tr

        def fake_launch_running(self, cfg_path, state_path, log_path):
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("started\n")
            p = MagicMock()
            p.poll.return_value = None
            p.terminate = MagicMock()
            p.returncode = None
            return p
        monkeypatch.setattr(tr.TrainingService, "_launch", fake_launch_running)

        token = _login(client, "trainapi3")
        headers = _auth(token)
        content = b'{"text": "x"}\n' * 3
        r = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("d.jsonl", content, "application/json")},
            headers=headers,
        )
        ds_id = r.json()["id"]
        r = client.post(
            "/api/v1/train/start",
            json={"dataset_id": ds_id, "base_model": "m", "method": "lora", "epochs": 3, "confirm": True},
            headers=headers,
        )
        task_id = r.json()["task_id"]
        r = client.post(f"/api/v1/train/stop/{task_id}", json={"confirm": True}, headers=headers)
        assert r.status_code == 200
        status = client.get(f"/api/v1/train/status/{task_id}", headers=headers).json()
        assert status["status"] == "stopped"

    def test_register_requires_done(self, client):
        token = _login(client, "trainapi4")
        headers = _auth(token)
        content = b'{"text": "x"}\n' * 3
        r = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("d.jsonl", content, "application/json")},
            headers=headers,
        )
        ds_id = r.json()["id"]
        r = client.post(
            "/api/v1/train/start",
            json={"dataset_id": ds_id, "base_model": "m", "method": "lora", "epochs": 3, "confirm": True},
            headers=headers,
        )
        task_id = r.json()["task_id"]
        r = client.post(f"/api/v1/train/{task_id}/register-model", json={"confirm": True}, headers=headers)
        assert r.status_code == 400

    def test_stream_reports_done_when_training_finishes(self, client, monkeypatch, tmp_path):
        """Regression: the log stream used to read a stale status snapshot."""
        import asyncio

        import services.training as tr

        state_box: dict[str, str] = {}

        def fake_launch_running(self, cfg_path, state_path, log_path):
            state_box["state"] = state_path
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("started\n")
            process = MagicMock()
            process.poll.return_value = None
            process.returncode = None
            process.terminate = MagicMock()
            return process

        monkeypatch.setattr(tr.TrainingService, "_launch", fake_launch_running)

        token = _login(client, "trainstream")
        headers = _auth(token)
        content = b'{"text": "x"}\n' * 3
        ds_id = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("s.jsonl", content, "application/json")},
            headers=headers,
        ).json()["id"]
        started = client.post(
            "/api/v1/train/start",
            json={"dataset_id": ds_id, "base_model": "m", "method": "lora", "epochs": 1, "confirm": True},
            headers=headers,
        )
        assert started.status_code == 200, started.text
        task_id = started.json()["task_id"]

        from api.train import train_stream
        from core.database import SessionLocal
        from models.records import User as UserRecord

        async def stream_reaches_terminal_status() -> bool:
            db = SessionLocal()
            try:
                owner = db.query(UserRecord).filter_by(username="trainstream").first()
                response = await train_stream(task_id, db=db, user=owner)
            finally:
                db.close()
            # The run finishes only after the stream captured its first snapshot,
            # which is exactly the case that used to hang.
            with open(state_box["state"], "w", encoding="utf-8") as f:
                json.dump({"status": "done", "progress": 100}, f)

            async def consume() -> bool:
                async for chunk in response.body_iterator:
                    if '"type": "done"' in str(chunk):
                        return True
                return False

            try:
                return await asyncio.wait_for(consume(), timeout=10)
            except asyncio.TimeoutError:
                return False

        assert asyncio.run(stream_reaches_terminal_status()) is True

    def test_restart_marks_orphaned_training_as_error(self, client, monkeypatch, tmp_path):
        """A run whose poll thread died with the process must not stay running."""
        import services.training as tr
        from core.database import SessionLocal
        from models.records import TrainTask
        from models.records import User as UserRecord

        _login(client, "trainorphan")
        db = SessionLocal()
        try:
            owner = db.query(UserRecord).filter_by(username="trainorphan").first()
            db.add(
                TrainTask(
                    task_id="orphan-training-1",
                    user_id=owner.id,
                    base_model="m",
                    method="lora",
                    status="running",
                    output_dir=str(tmp_path / "orphan"),
                    log_path=str(tmp_path / "orphan" / "train.log"),
                )
            )
            db.commit()
        finally:
            db.close()

        assert tr.get_training_service().reconcile_orphaned_tasks() >= 1

        db = SessionLocal()
        try:
            row = db.query(TrainTask).filter_by(task_id="orphan-training-1").first()
            assert row.status == "error"
            assert "重启" in row.error
        finally:
            db.close()


class TestKnowledgePersistence:
    def test_upload_documents_chunks_delete(self, client):
        token = _login(client, "kbapi")
        headers = _auth(token)
        content = ("Python 是流行的编程语言。\n" * 30).encode("utf-8")
        r = client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("guide.txt", content, "text/plain")},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ingested"

        r = client.get("/api/v1/knowledge/documents", headers=headers)
        docs = r.json()
        assert any(d["filename"] == "guide.txt" for d in docs)

        r = client.get("/api/v1/knowledge/documents/guide.txt/chunks", headers=headers)
        assert len(r.json()) >= 1

        r = client.post(
            "/api/v1/knowledge/query",
            json={"question": "python 编程", "top_k": 3},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["total_results"] > 0

        r = client.delete("/api/v1/knowledge/documents/guide.txt", headers=headers)
        assert r.status_code == 200
        docs = client.get("/api/v1/knowledge/documents", headers=headers).json()
        assert all(d["filename"] != "guide.txt" for d in docs)

    def test_answer_with_mocked_runtime(self, client, monkeypatch):
        class _FakeRuntime:
            async def chat(self, model, messages, **kwargs):
                return {"model": model, "content": "知识库回答", "raw": None}
        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: _FakeRuntime())
        monkeypatch.setattr(RuntimeRegistry, "chat", _FakeRuntime.chat)

        token = _login(client, "kbapi2")
        headers = _auth(token)
        content = ("ModelForge 是本地 AI 工作站。\n" * 30).encode("utf-8")
        client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("mf.txt", content, "text/plain")},
            headers=headers,
        )
        r = client.post(
            "/api/v1/knowledge/answer",
            json={"question": "ModelForge 是什么", "top_k": 3, "model": "mock"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["answer"] == "知识库回答"
        assert len(data["sources"]) > 0
        assert data["sources"][0]["source"] == "mf.txt"


def settings_mod():
    from core.config import settings
    return settings
