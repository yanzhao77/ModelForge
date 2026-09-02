"""MF-SEC-002 API-level: Run creation must reject a foreign Session (spec 25)."""
import os
import sys
import tempfile

# Isolate DB for this test session (imported before core.database is used)
_tmp_db = tempfile.mkdtemp(prefix="mf_sec2_api_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _login(client, username):
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@x.com"},
    )
    r = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _make_owned_session(username):
    from core.database import SessionLocal
    from models.records import User
    from services.session_service import SessionService
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == username).first()
        s = SessionService.create_session(db, user_id=u.id)
        db.commit()
        return s.id


def test_run_binds_owned_session(client):
    h = _login(client, "mfsec2api_a")
    client.post("/api/v1/agent/create", json={"name": "mfsec2api-bot-a", "model": "mock"}, headers=h)
    sid = _make_owned_session("mfsec2api_a")
    r = client.post(
        "/api/v1/agent/runs",
        json={"agent_id": "mfsec2api-bot-a", "input": "x", "confirm": True, "session_id": sid, "execute": False},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["run_id"]


def test_run_rejects_foreign_session(client):
    h1 = _login(client, "mfsec2api_b")
    h2 = _login(client, "mfsec2api_c")
    client.post("/api/v1/agent/create", json={"name": "mfsec2api-bot-b", "model": "mock"}, headers=h1)
    client.post("/api/v1/agent/create", json={"name": "mfsec2api-bot-c", "model": "mock"}, headers=h2)
    sid_b = _make_owned_session("mfsec2api_b")
    r = client.post(
        "/api/v1/agent/runs",
        json={"agent_id": "mfsec2api-bot-c", "input": "x", "confirm": True, "session_id": sid_b, "execute": False},
        headers=h2,
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"
