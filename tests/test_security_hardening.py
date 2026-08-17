import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.config import load_config, settings
from fastapi.testclient import TestClient
from main import app
from services.agent_tools import tool_command_execute


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _auth(client, username):
    client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": username + "@example.com"})
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_production_rejects_missing_or_default_jwt_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELFORGE_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("jwt_secret: ''\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        load_config(str(config_path))


def test_command_tool_is_disabled_by_default():
    assert "disabled" in tool_command_execute("pwd").lower()


def test_command_tool_uses_argv_allowlist_without_shell():
    with patch.object(settings.tools, "command_execution_enabled", True), patch("services.agent_tools.subprocess.run") as run:
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        assert tool_command_execute("pwd") == "ok"
        assert run.call_args.args[0] == ["pwd"]
        assert run.call_args.kwargs["shell"] is False
        assert "allowlist" in tool_command_execute("echo forbidden").lower()


def test_agent_runtime_routes_require_authentication(client):
    assert client.get("/api/v1/agent/runs").status_code == 401
    assert client.get("/api/v1/agent/tools").status_code == 401
    assert client.get("/api/v1/agent/mcp/servers").status_code == 401


def test_agent_definitions_are_isolated_per_user(client):
    alice = _auth(client, "securityalice")
    bob = _auth(client, "securitybob")
    created = client.post("/api/v1/agent/create", json={"name": "alice-private-agent", "model": "mock", "tools": ["file_read"]}, headers=alice)
    assert created.status_code == 200, created.text
    assert any(item["name"] == "alice-private-agent" for item in client.get("/api/v1/agent/list", headers=alice).json())
    assert all(item["name"] != "alice-private-agent" for item in client.get("/api/v1/agent/list", headers=bob).json())
    assert client.delete("/api/v1/agent/alice-private-agent", headers=bob).status_code == 404


def test_shared_runtime_management_requires_administrator(client):
    user = _auth(client, "securityoperator")
    assert client.get("/api/v1/agent/mcp/servers", headers=user).status_code == 403
    assert client.get("/api/v1/agent/metrics", headers=user).status_code == 403
