"""V1.9 Production hardening: cache invalidation, recovery, benchmark."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend", "app"))

from core.cache import TTLCache  # noqa: E402
from core.config import settings  # noqa: E402
from core.database import SessionLocal  # noqa: E402
from main import app  # noqa: E402
from models.records import ModelRecord, WorkflowRun  # noqa: E402
from services.recovery_service import RecoveryService  # noqa: E402


def _auth(client: TestClient) -> tuple[dict, str]:
    username = f"v19{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}, username


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_PATH", str(models))
    monkeypatch.setenv("MODEL_DIR", str(models))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "model_path", str(models))
    monkeypatch.setattr(settings, "model_dir", str(models))
    with TestClient(app) as client:
        headers, username = _auth(client)
        yield {"client": client, "headers": headers, "username": username, "models": models}


def test_ttl_cache_hits_misses_and_invalidation():
    cache = TTLCache(max_entries=4, default_ttl_seconds=30)
    key = cache.make_key({"a": 1})

    assert cache.get("ns", key) is None
    cache.set("ns", key, ["value"])
    assert cache.get("ns", key) == ["value"]
    cache.set("other", key, "x")

    snapshot = cache.snapshot()
    assert snapshot["entries"] == 2
    assert snapshot["hits"] == 1
    assert snapshot["misses"] == 1
    assert snapshot["hit_rate"] == 0.5

    removed = cache.invalidate("ns")
    assert removed == 1
    assert cache.get("ns", key) is None
    assert cache.get("other", key) == "x"

    cache.invalidate()
    assert cache.snapshot()["entries"] == 0
    assert cache.snapshot()["invalidations"] >= 2


def test_ttl_cache_expires_and_evicts():
    cache = TTLCache(max_entries=2, default_ttl_seconds=30)
    cache.set("ns", "short", "v", ttl_seconds=0.01)
    assert cache.get("ns", "short") == "v"
    time.sleep(0.05)
    assert cache.get("ns", "short") is None

    cache.set("ns", "a", 1)
    cache.set("ns", "b", 2)
    cache.set("ns", "c", 3)  # exceeds max_entries -> one eviction
    assert cache.snapshot()["entries"] == 2
    assert cache.snapshot()["evictions"] >= 1


def test_embedding_cache_avoids_recomputation(env):
    from core.cache import embedding_cache, invalidate_all
    from services.embedding_service import embed_texts

    invalidate_all()
    with SessionLocal() as session:
        first = embed_texts(session, 1, ["alpha beta"])
        hits_before = embedding_cache.snapshot()["hits"]
        second = embed_texts(session, 1, ["alpha beta"])

    assert first["vectors"] == second["vectors"]
    assert embedding_cache.snapshot()["hits"] > hits_before


def test_startup_recovery_settles_workflow_runs_and_models(env):
    client, headers = env["client"], env["headers"]
    asset = env["models"] / "recover.gguf"
    asset.write_bytes(b"GGUF")
    model_id = client.post(
        "/api/v1/models/install",
        json={"name": "recover", "provider": "local", "path": str(asset)},
        headers=headers,
    ).json()["id"]
    workflow = client.post(
        "/api/v1/workflows",
        json={
            "name": "Interrupted",
            "definition": {
                "entry": "start",
                "nodes": [
                    {"id": "start", "type": "input", "next": "gate"},
                    {"id": "gate", "type": "approval", "next": "done"},
                    {"id": "done", "type": "output"},
                ],
            },
        },
        headers=headers,
    ).json()
    owner_id = int(client.get("/api/v1/auth/me", headers=headers).json()["id"])
    with SessionLocal() as session:
        session.add(
            WorkflowRun(
                id=uuid.uuid4().hex[:32],
                workflow_id=workflow["workflow_id"],
                user_id=owner_id,
                status="RUNNING",
            )
        )
        session.commit()

    # Remove the model file: recovery must mark the record invalid.
    asset.unlink()
    report = RecoveryService().startup_recovery()

    assert report["ok"] is True
    assert report["steps"]["workflow_runs"]["settled"] >= 1
    assert report["steps"]["models"]["invalid_records"] >= 1
    with SessionLocal() as session:
        stale = session.query(WorkflowRun).filter(WorkflowRun.status == "RUNNING").count()
        assert stale == 0
        record = session.get(ModelRecord, model_id)
        assert record.status == "invalid"

    # Recovery is idempotent: a second pass has nothing left to settle.
    again = RecoveryService().startup_recovery()
    assert again["steps"]["workflow_runs"]["settled"] == 0


def test_hardening_and_recovery_endpoints(env):
    client, headers, username = env["client"], env["headers"], env["username"]

    assert client.get("/api/v1/system/hardening", headers=headers).status_code == 403
    from core.config import settings as live_settings

    previous = live_settings.runtime_admin_usernames
    live_settings.runtime_admin_usernames = username
    try:
        hardening = client.get("/api/v1/system/hardening", headers=headers)
        assert hardening.status_code == 200, hardening.text
        body = hardening.json()
        assert set(body) >= {"cache", "runtime", "packages", "migration_preflight", "schema_version"}
        assert "embedding" in body["cache"]

        recovery = client.post("/api/v1/system/recovery", headers=headers)
        assert recovery.status_code == 200
        assert recovery.json()["ok"] is True
    finally:
        live_settings.runtime_admin_usernames = previous


def test_benchmark_script_reports_results():
    completed = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "benchmark_platform.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=300,
    )

    assert completed.returncode == 0, completed.stderr[-500:]
    payload = json.loads(completed.stdout)
    names = {item["name"] for item in payload["results"]}
    assert {"model.register", "embedding.cold", "workflow.sequential", "recovery.pass"} <= names
    assert all(item["duration_ms"] >= 0 for item in payload["results"])
