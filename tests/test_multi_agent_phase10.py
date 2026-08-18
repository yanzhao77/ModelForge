"""Phase 10: Multi-Agent tests - agent.delegate (spec 73)."""
import asyncio
import os
import sys
import tempfile

_tmp_db = tempfile.mkdtemp(prefix="mf_ma_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.models import MockProvider
from runtime.tools import ToolExecutor, ToolRegistry
from runtime.tools.builtin import register_builtin_tools
from runtime.types import AgentConfig


def build_runtime(scripts):
    """scripts maps agent model -> [ModelResult...] provider scripts."""
    from core.database import init_db
    from models.records import AgentRun  # noqa: F401
    from repositories.event_repository import SQLAlchemyEventStore
    from repositories.run_repository import SQLAlchemyRunStore
    from runtime.events import EventBus
    from runtime.runtime import AgentRuntime
    from services.agent_store import DBAgentStore
    init_db()
    registry = register_builtin_tools(ToolRegistry())
    def factory(model):
        return MockProvider(script=scripts.get(model, [MockProvider.final("default")]))
    rt = AgentRuntime(
        run_store=SQLAlchemyRunStore(),
        agent_store=DBAgentStore(engine=None),
        event_bus=EventBus(store=SQLAlchemyEventStore()),
        tool_registry=registry,
        tool_runner=ToolExecutor(registry),
        provider_factory=factory,
    )
    return rt


class TestDelegate:
    @pytest.mark.asyncio
    async def test_delegate_to_another_agent(self):
        rt = build_runtime({
            "helper": [MockProvider.final("helper analysis done")],
            "boss": [
                MockProvider.tool_call("agent.delegate", {"agent_id": "helper", "task": "analyze this"}),
                MockProvider.final("boss summary"),
            ],
        })
        rt.create_agent(AgentConfig(name="helper", model="helper", tools=["agent.delegate"]))
        rt.create_agent(AgentConfig(name="boss", model="boss", tools=["agent.delegate"]))
        run = rt.create_run(agent_id="boss", input_text="start", user_id=1, execute=False)
        task = asyncio.create_task(rt.execute_run(run.run_id))
        await task
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "boss summary"
        runs = rt.list_runs(user_id=1)
        helper_runs = [r for r in runs if r.agent_id == "helper"]
        assert len(helper_runs) == 1
        assert helper_runs[0].status == "COMPLETED"
        assert helper_runs[0].output == "helper analysis done"
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "tool.call.completed" for e in events)

    @pytest.mark.asyncio
    async def test_self_delegation_rejected(self):
        rt = build_runtime({
            "solo": [
                MockProvider.tool_call("agent.delegate", {"agent_id": "solo", "task": "help yourself"}),
                MockProvider.final("done"),
            ],
        })
        rt.create_agent(AgentConfig(name="solo", model="solo", tools=["agent.delegate"]))
        run = rt.create_run(agent_id="solo", input_text="go", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        helper_runs = [r for r in rt.list_runs(user_id=1) if r.agent_id == "solo" and r.input == "help yourself"]
        assert helper_runs == []

    @pytest.mark.asyncio
    async def test_delegate_unknown_agent(self):
        rt = build_runtime({
            "caller": [
                MockProvider.tool_call("agent.delegate", {"agent_id": "ghost", "task": "x"}),
                MockProvider.final("recovered"),
            ],
        })
        rt.create_agent(AgentConfig(name="caller", model="caller", tools=["agent.delegate"]))
        run = rt.create_run(agent_id="caller", input_text="go", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "recovered"

    def test_delegate_tool_registered(self):
        rt = build_runtime({})
        assert rt.get_tool("agent.delegate") is not None
        assert rt.get_tool("agent.delegate").source == "builtin"

    def test_delegate_in_tool_list(self):
        rt = build_runtime({})
        names = [t["name"] for t in rt.list_tools()]
        assert "agent.delegate" in names