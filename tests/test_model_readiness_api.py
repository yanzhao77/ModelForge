"""API contract tests for user-scoped, credential-safe model readiness."""

from __future__ import annotations

import os
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from main import app


def _headers(client: TestClient) -> dict:
    suffix = uuid4().hex[:10]
    username = f"ready{suffix}"
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    assert registered.status_code == 200, registered.text
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['token']}"}


def test_readiness_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/api/v1/models/readiness").status_code == 401


def test_readiness_and_default_are_scoped_and_never_expose_secret_data():
    with TestClient(app) as client:
        first = _headers(client)
        initial = client.get("/api/v1/models/readiness", headers=first)
        assert initial.status_code == 200, initial.text
        assert initial.json()["level"] == "SETUP_REQUIRED"

        created = client.post(
            "/api/v1/models/install",
            headers=first,
            json={"name": "readiness-local", "provider": "local", "path": "/safe/test/model.gguf"},
        )
        assert created.status_code == 200, created.text
        model_id = created.json()["id"]

        set_default = client.put(
            "/api/v1/models/default",
            headers=first,
            json={"kind": "local", "model_ref": str(model_id)},
        )
        assert set_default.status_code == 200, set_default.text
        snapshot = set_default.json()
        assert snapshot["level"] == "READY"
        assert snapshot["default_target"]["model_ref"] == str(model_id)
        rendered = str(snapshot).lower()
        assert "ciphertext" not in rendered
        assert "api_key" not in rendered

        second = _headers(client)
        cross_user = client.put(
            "/api/v1/models/default",
            headers=second,
            json={"kind": "local", "model_ref": str(model_id)},
        )
        assert cross_user.status_code == 400

        cleared = client.delete("/api/v1/models/default", headers=first)
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["default_target"] is None
