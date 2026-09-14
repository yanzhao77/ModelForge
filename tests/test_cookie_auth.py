import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_http_only_cookie_session_and_csrf(client):
    username = f"cookieuser-{uuid.uuid4().hex[:10]}"
    registration = client.post("/api/v1/auth/register", json={"username": username, "password": "safe-pass-123", "email": f"{username}@example.com"})
    assert registration.status_code == 200, registration.text
    assert "modelforge_session" not in client.cookies
    login = client.post(
        "/api/v1/auth/login",
        headers={"X-Auth-Transport": "cookie"},
        json={"username": username, "password": "safe-pass-123"},
    )
    assert login.status_code == 200, login.text
    assert "token" not in login.json()
    assert "modelforge_session" in client.cookies
    assert "modelforge_csrf" in client.cookies
    assert "HttpOnly" in login.headers.get("set-cookie", "")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == username

    blocked = client.post("/api/v1/tasks", json={"task_type": "cookie", "title": "csrf check"})
    assert blocked.status_code == 403
    accepted = client.post("/api/v1/tasks", headers={"X-CSRF-Token": client.cookies.get("modelforge_csrf")}, json={"task_type": "cookie", "title": "csrf check"})
    assert accepted.status_code == 200

    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies.get("modelforge_csrf")})
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401



def test_cookie_transport_does_not_return_jwt_to_browser(client):
    username = f"browser-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "safe-pass-123", "email": f"{username}@example.com"})
    response = client.post("/api/v1/auth/login", headers={"X-Auth-Transport": "cookie"}, json={"username": username, "password": "safe-pass-123"})
    assert response.status_code == 200
    assert "token" not in response.json()
    assert response.json()["csrf_token"]


def test_openai_compatible_router_ignores_cookie_sessions(client, monkeypatch):
    """The external /v1 API requires a local API key, not browser cookie auth."""
    from api import openai_api

    class _FakeRuntime:
        async def chat(self, model, messages, **kwargs):
            return {"model": model, "content": "ok"}

    monkeypatch.setattr(openai_api, "get_runtime", lambda: _FakeRuntime())
    username = f"openaicsrf-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "safe-pass-123", "email": f"{username}@example.com"})
    login = client.post(
        "/api/v1/auth/login",
        headers={"X-Auth-Transport": "cookie"},
        json={"username": username, "password": "safe-pass-123"},
    )
    assert login.status_code == 200, login.text
    payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    blocked = client.post("/v1/chat/completions", json=payload)
    assert blocked.status_code == 401
    assert blocked.json()["error"]["code"] == "API_KEY_REQUIRED"

    accepted = client.post(
        "/v1/chat/completions",
        headers={"X-CSRF-Token": client.cookies.get("modelforge_csrf")},
        json=payload,
    )
    assert accepted.status_code == 401


def test_password_change_retires_tokens_issued_before_it(client):
    """A leaked token must not survive the password reset that responds to it."""
    username = f"pwdtoken-{uuid.uuid4().hex[:10]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "safe-pass-123", "email": f"{username}@example.com"})
    token = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "safe-pass-123"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": "safe-pass-123", "new_password": "safe-pass-456"},
    )
    assert changed.status_code == 200, changed.text

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    # The replacement credential still works.
    fresh = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "safe-pass-456"}
    ).json()["token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fresh}"}).status_code == 200
