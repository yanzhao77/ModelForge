"""Regression tests for the project-scoped Agent API control plane."""
from __future__ import annotations

import os
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app
from runtime.models import MockProvider
from runtime.types import AgentConfig
from services.agent_runtime_service import get_agent_runtime


def _user_headers(client: TestClient, label: str) -> tuple[dict, int]:
    username = f"platform-{label}-{uuid4().hex[:8]}"
    registered = client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.test"})
    assert registered.status_code == 200, registered.text
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _project_and_key(client: TestClient, headers: dict) -> tuple[str, str]:
    org = client.post("/api/v2/organizations", headers=headers, json={"name": "API Platform Org"})
    assert org.status_code == 200, org.text
    organization_id = org.json()["organization"]["id"]
    project = client.post(
        f"/api/v2/organizations/{organization_id}/projects",
        headers=headers,
        json={"name": "Service", "environment": "test"},
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["project"]["id"]
    key = client.post(f"/api/v2/projects/{project_id}/keys", headers=headers, json={"name": "automation"})
    assert key.status_code == 200, key.text
    return project_id, key.json()["secret"]


def test_project_key_lifecycle_does_not_expose_secret_and_is_revocable():
    with TestClient(app) as client:
        headers, _user_id = _user_headers(client, "keys")
        project_id, secret = _project_and_key(client, headers)
        listed = client.get(f"/api/v2/projects/{project_id}/keys", headers=headers)
        assert listed.status_code == 200, listed.text
        rendered = str(listed.json())
        assert secret not in rendered
        key_id = listed.json()["keys"][0]["id"]
        revoked = client.post(f"/api/v2/projects/{project_id}/keys/{key_id}/revoke", headers=headers, json={"confirm": True})
        assert revoked.status_code == 200, revoked.text
        denied = client.get("/api/v2/runs/not-real", headers={"X-API-Key": secret})
        assert denied.status_code == 401
        assert denied.json()["detail"]["code"] == "API_KEY_INVALID"


def test_agent_invocation_is_project_scoped_idempotent_and_metered():
    with TestClient(app) as client:
        headers, user_id = _user_headers(client, "runs")
        project_id, secret = _project_and_key(client, headers)
        runtime = get_agent_runtime()
        agent_name = "platform-agent-" + uuid4().hex[:8]
        runtime.create_agent(AgentConfig(name=agent_name, model="mock", user_id=user_id, tools=[]))
        unbound = client.post("/api/v2/runs", headers={"X-API-Key": secret, "Idempotency-Key": "unbound"}, json={"agent_id": agent_name, "input": "hello", "max_tokens": 32})
        assert unbound.status_code == 403
        assert unbound.json()["detail"]["code"] == "AGENT_PROJECT_SCOPE_DENIED"
        binding = client.post(f"/api/v2/projects/{project_id}/agents", headers=headers, json={"agent_id": agent_name})
        assert binding.status_code == 200, binding.text
        runtime.provider_factory = lambda _model: MockProvider(script=[MockProvider.final("platform response")])

        invocation_headers = {"X-API-Key": secret, "Idempotency-Key": "invoke-once"}
        first = client.post("/api/v2/runs", headers=invocation_headers, json={"agent_id": agent_name, "input": "hello", "max_tokens": 32})
        assert first.status_code == 200, first.text
        assert first.json()["replayed"] is False
        assert first.json()["invocation"]["status"] == "COMPLETED"
        second = client.post("/api/v2/runs", headers=invocation_headers, json={"agent_id": agent_name, "input": "hello", "max_tokens": 32})
        assert second.status_code == 200, second.text
        assert second.json()["replayed"] is True
        assert second.json()["invocation"]["id"] == first.json()["invocation"]["id"]
        conflict = client.post("/api/v2/runs", headers=invocation_headers, json={"agent_id": agent_name, "input": "changed", "max_tokens": 32})
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

        usage = client.get(f"/api/v2/projects/{project_id}/usage", headers=headers)
        assert usage.status_code == 200, usage.text
        assert usage.json()["project_id"] == project_id
        assert len(usage.json()["records"]) == 1
        assert usage.json()["records"][0]["idempotency_key"] == "invoke-once"


def test_per_run_quota_is_enforced_before_agent_execution():
    with TestClient(app) as client:
        headers, user_id = _user_headers(client, "quota")
        project_id, secret = _project_and_key(client, headers)
        runtime = get_agent_runtime()
        agent_name = "quota-agent-" + uuid4().hex[:8]
        runtime.create_agent(AgentConfig(name=agent_name, model="mock", user_id=user_id, tools=[]))
        binding = client.post(f"/api/v2/projects/{project_id}/agents", headers=headers, json={"agent_id": agent_name})
        assert binding.status_code == 200, binding.text
        quota = client.put(
            f"/api/v2/projects/{project_id}/quota",
            headers=headers,
            json={"max_concurrent_runs": 1, "daily_token_limit": 100, "monthly_token_limit": 200, "per_run_token_limit": 10},
        )
        assert quota.status_code == 200, quota.text
        rejected = client.post(
            "/api/v2/runs",
            headers={"X-API-Key": secret, "Idempotency-Key": "over-quota"},
            json={"agent_id": agent_name, "input": "hello", "max_tokens": 11},
        )
        assert rejected.status_code == 429
        assert rejected.json()["detail"]["code"] == "PER_RUN_QUOTA_EXCEEDED"
