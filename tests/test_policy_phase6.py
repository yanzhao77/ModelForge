"""Phase 6: Policy Engine tests - permissions, denial, human gate (spec 69 / 32)."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.models import MockProvider
from runtime.policy import Policy, PolicyDecision, PolicyEngine
from runtime.tools.builtin import register_builtin_tools
from runtime.tools.registry import ToolRegistry


def reg():
    return register_builtin_tools(ToolRegistry())


class TestPolicy:
    def test_default_denies_network_and_shell(self):
        p = Policy()
        r = reg()
        assert p.check_tool(None, "web.search", r.get("web.search")).allowed is False
        assert p.check_tool(None, "shell.execute", r.get("shell.execute")).allowed is False
        assert p.check_tool(None, "filesystem.read", r.get("filesystem.read")).allowed is True

    def test_shell_access_granted(self):
        p = Policy(shell_access=True)
        r = reg()
        assert p.check_tool(None, "shell.execute", r.get("shell.execute")).allowed is True

    def test_network_access_granted(self):
        p = Policy(network_access=True)
        r = reg()
        assert p.check_tool(None, "web.search", r.get("web.search")).allowed is True

    def test_allowed_tools_restriction(self):
        p = Policy(allowed_tools=["filesystem.read", "knowledge.search"])
        r = reg()
        assert p.check_tool(None, "filesystem.read", r.get("filesystem.read")).allowed is True
        assert p.check_tool(None, "web.search", r.get("web.search")).allowed is False

    def test_denied_tools(self):
        p = Policy(denied_tools=["filesystem.read"])
        r = reg()
        assert p.check_tool(None, "filesystem.read", r.get("filesystem.read")).allowed is False

    def test_human_approval_flag(self):
        p = Policy(human_approval_required=True)
        r = reg()
        d = p.check_tool(None, "filesystem.read", r.get("filesystem.read"))
        assert d.allowed is True
        assert d.require_approval is True

    def test_require_approval_for_specific_tool(self):
        p = Policy(shell_access=True, require_approval_for=["shell.execute"])
        r = reg()
        assert p.check_tool(None, "shell.execute", r.get("shell.execute")).require_approval is True
        assert p.check_tool(None, "filesystem.read", r.get("filesystem.read")).require_approval is False

    def test_decision_helpers(self):
        assert PolicyDecision.allow().allowed is True
        assert PolicyDecision.deny("x").allowed is False
        assert PolicyDecision.approval().require_approval is True

    def test_agent_policy_merge(self):
        engine = PolicyEngine(defaults=Policy(network_access=False))
        class FakeAgent:
            policy = {"network_access": True}
        merged = engine.for_agent(FakeAgent())
        assert merged.network_access is True
        assert merged.shell_access is False
        # agent without policy -> defaults
        class NoPolicy:
            policy = None
        assert engine.for_agent(NoPolicy()).network_access is False


class TestPolicyRuntime:
    def _runtime(self, agent_policy=None, provider_script=None, agent_tools=None):
        from core.database import init_db
        from models.records import AgentRun  # noqa: F401
        from repositories.event_repository import SQLAlchemyEventStore
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.models import MockProvider
        from runtime.runtime import AgentRuntime
        from runtime.tools import ToolExecutor
        from runtime.types import AgentConfig
        from services.agent_store import DBAgentStore
        init_db()
        registry = reg()
        rt = AgentRuntime(
            run_store=SQLAlchemyRunStore(),
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(store=SQLAlchemyEventStore()),
            tool_registry=registry,
            tool_runner=ToolExecutor(registry),
            provider_factory=lambda m: MockProvider(script=provider_script or []),
        )
        rt.create_agent(AgentConfig(
            name="polbot", model="mock",
            tools=agent_tools or [],
            policy=agent_policy,
        ))
        return rt

    @pytest.mark.asyncio
    async def test_denied_tool_recorded(self):
        rt = self._runtime(
            provider_script=[
                MockProvider.tool_call("web.search", {"query": "x"}),
                MockProvider.final("done"),
            ],
            agent_tools=["web.search"],
        )
        run = rt.create_run(agent_id="polbot", input_text="search", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        events = rt.list_events(run.run_id, user_id=1)
        denied = [e for e in events if e.event_type == "tool.call.failed"]
        assert len(denied) == 1
        assert denied[0].payload.get("code") == "TOOL_DENIED"

    @pytest.mark.asyncio
    async def test_shell_allowed_with_policy(self):
        rt = self._runtime(
            agent_policy={"shell_access": True},
            provider_script=[
                MockProvider.tool_call("shell.execute", {"command": "echo hi"}),
                MockProvider.final("shell ok"),
            ],
            agent_tools=["shell.execute"],
        )
        run = rt.create_run(agent_id="polbot", input_text="run", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "shell ok"
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "tool.call.completed" for e in events)

    @pytest.mark.asyncio
    async def test_human_approval_flow(self):
        rt = self._runtime(
            agent_policy={"require_approval_for": ["filesystem.read"]},
            provider_script=[
                MockProvider.tool_call("filesystem.read", {"filepath": "/etc/hostname"}),
                MockProvider.final("approved run"),
            ],
            agent_tools=["filesystem.read"],
        )
        run = rt.create_run(agent_id="polbot", input_text="read", user_id=1, execute=False)
        task = asyncio.create_task(rt.execute_run(run.run_id))
        status = None
        for _ in range(100):
            status = rt.get_run(run.run_id).status
            if status == "WAITING_HUMAN":
                break
            await asyncio.sleep(0.01)
        assert status == "WAITING_HUMAN", status
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "human.approval.required" for e in events)
        await rt.approve_run(run.run_id, user_id=1)
        await task
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "approved run"
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "human.approval.granted" for e in events)

    @pytest.mark.asyncio
    async def test_human_reject_denies_tool(self):
        rt = self._runtime(
            agent_policy={"require_approval_for": ["filesystem.read"]},
            provider_script=[
                MockProvider.tool_call("filesystem.read", {"filepath": "/etc/hostname"}),
                MockProvider.final("final"),
            ],
            agent_tools=["filesystem.read"],
        )
        run = rt.create_run(agent_id="polbot", input_text="read", user_id=1, execute=False)
        task = asyncio.create_task(rt.execute_run(run.run_id))
        for _ in range(100):
            if rt.get_run(run.run_id).status == "WAITING_HUMAN":
                break
            await asyncio.sleep(0.01)
        await rt.reject_run(run.run_id, user_id=1)
        await task
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "human.approval.denied" for e in events)
        denied = [e for e in events if e.payload.get("code") == "TOOL_DENIED"]
        assert len(denied) == 1

    def test_approve_reject_api(self):
        from fastapi.testclient import TestClient
        from main import app
        from services.agent_runtime_service import get_agent_runtime
        with TestClient(app) as c:
            rt = get_agent_runtime()
            rt.provider_factory = lambda m: MockProvider(script=[
                MockProvider.tool_call("filesystem.read", {"filepath": "/etc/hostname"}),
                MockProvider.final("api approved"),
            ])
            c.post("/api/v1/auth/register", json={"username": "poluser", "password": "secret123", "email": "poluser@x.com"})
            h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", json={"username": "poluser", "password": "secret123"}).json()["token"]}
            c.post("/api/v1/agent/create", json={
                "name": "pol-bot", "model": "mock",
                "tools": ["filesystem.read"],
                "policy": {"require_approval_for": ["filesystem.read"]},
            }, headers=h)
            r = c.post("/api/v1/agent/runs", json={"agent_id": "pol-bot", "input": "read"}, headers=h)
            run_id = r.json()["run_id"]
            status = None
            for _ in range(100):
                status = c.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()["status"]
                if status == "WAITING_HUMAN":
                    break
                import time as _t
                _t.sleep(0.01)
            assert status == "WAITING_HUMAN"
            r = c.post(f"/api/v1/agent/runs/{run_id}/approve", headers=h)
            assert r.status_code == 200
            final = None
            for _ in range(100):
                final = c.get(f"/api/v1/agent/runs/{run_id}", headers=h).json()["status"]
                if final == "COMPLETED":
                    break
                import time as _t
                _t.sleep(0.01)
            assert final == "COMPLETED", final
            # reject on a fresh run
            r = c.post("/api/v1/agent/runs", json={"agent_id": "pol-bot", "input": "read"}, headers=h)
            run2 = r.json()["run_id"]
            for _ in range(100):
                if c.get(f"/api/v1/agent/runs/{run2}", headers=h).json()["status"] == "WAITING_HUMAN":
                    break
                import time as _t
                _t.sleep(0.01)
            r = c.post(f"/api/v1/agent/runs/{run2}/reject", headers=h)
            assert r.status_code == 200