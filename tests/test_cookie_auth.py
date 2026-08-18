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
