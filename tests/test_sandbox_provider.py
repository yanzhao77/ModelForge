from __future__ import annotations

import os
import sys
import uuid

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402
from runtime.policy import Policy  # noqa: E402
from runtime.tools.base import PermissionLevel  # noqa: E402
from runtime.tools.builtin import register_builtin_tools  # noqa: E402
from runtime.tools.registry import ToolRegistry  # noqa: E402
from services import sandbox_provider  # noqa: E402
from services.sandbox_provider import SandboxProviderService  # noqa: E402


def _auth(client: TestClient) -> dict[str, str]:
    username = f"sandbox-{uuid.uuid4().hex[:10]}"
    created = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    assert created.status_code == 200, created.text
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_sandbox_status_disables_execution_without_docker(monkeypatch):
    monkeypatch.setattr(sandbox_provider.shutil, "which", lambda _name: None)

    status = SandboxProviderService().status()

    assert status["provider"] == "docker"
    assert status["available"] is False
    assert status["execution_enabled"] is False
    assert status["host_fallback"] is False
    assert status["disabled_reason"] == "DOCKER_CLI_UNAVAILABLE"


def test_sandbox_status_api_reports_diagnostics_without_enabling_execution(monkeypatch):
    monkeypatch.setattr(sandbox_provider.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.delenv("MODELFORGE_SANDBOX_EXECUTION", raising=False)

    class Completed:
        returncode = 0
        stdout = '{"ServerVersion":"25.0.0","SecurityOptions":["name=rootless"]}'
        stderr = ""

    monkeypatch.setattr(sandbox_provider.subprocess, "run", lambda *args, **kwargs: Completed())

    with TestClient(app) as client:
        headers = _auth(client)
        response = client.get("/api/v1/sandbox/status", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert payload["execution_enabled"] is False
    assert payload["disabled_reason"] == "SANDBOX_EXECUTION_DISABLED"
    assert payload["host_fallback"] is False
    assert payload["rootless"] is True


def test_sandbox_execute_api_refuses_when_disabled(monkeypatch):
    monkeypatch.setattr(sandbox_provider.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.delenv("MODELFORGE_SANDBOX_EXECUTION", raising=False)

    class Completed:
        returncode = 0
        stdout = '{"ServerVersion":"25.0.0","SecurityOptions":[]}'
        stderr = ""

    monkeypatch.setattr(sandbox_provider.subprocess, "run", lambda *args, **kwargs: Completed())

    with TestClient(app) as client:
        headers = _auth(client)
        response = client.post("/api/v1/sandbox/execute-python", headers=headers, json={"code": "print('hi')"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SANDBOX_EXECUTION_DISABLED"


def test_sandbox_execute_uses_docker_isolation_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox_provider.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("MODELFORGE_SANDBOX_EXECUTION", "1")
    commands = []

    class Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["/usr/bin/docker", "info"]:
            return Completed(stdout='{"ServerVersion":"25.0.0","SecurityOptions":["name=rootless"]}')
        if command[:3] == ["/usr/bin/docker", "image", "inspect"]:
            return Completed(stdout="[]")
        if command[:2] == ["/usr/bin/docker", "run"]:
            volume = command[command.index("-v") + 1]
            workspace = volume.split(":", 1)[0]
            output = os.path.join(workspace, "output", "result.txt")
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("done")
            return Completed(stdout="ok\n")
        raise AssertionError(command)

    monkeypatch.setattr(sandbox_provider.subprocess, "run", fake_run)
    result = SandboxProviderService(root=tmp_path).execute_python("print('ok')")

    docker_run = commands[-1]
    assert docker_run[:2] == ["/usr/bin/docker", "run"]
    assert "--network" in docker_run and "none" in docker_run
    assert "--memory" in docker_run and "512m" in docker_run
    assert "--pids-limit" in docker_run and "128" in docker_run
    assert "--read-only" in docker_run
    assert result["host_fallback"] is False
    assert result["output_files"] == [{"path": "result.txt", "size_bytes": 4, "text_preview": "done"}]


def test_sandbox_execute_tool_is_policy_gated():
    registry = register_builtin_tools(ToolRegistry())
    tool = registry.get("sandbox.execute")

    assert tool is not None
    assert tool.permissions == [PermissionLevel.EXECUTE]
    denied = Policy().check_tool(None, "sandbox.execute", tool)
    assert denied.allowed is False
    approved = Policy(shell_access=True, require_approval_for=["sandbox.execute"]).check_tool(None, "sandbox.execute", tool)
    assert approved.allowed is True
    assert approved.require_approval is True
