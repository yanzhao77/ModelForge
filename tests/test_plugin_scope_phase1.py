"""3.x-P1 tests: PluginScope + PluginContext (audit §16.4 scope mechanism)."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.tools import Tool, ToolExecutor, ToolRegistry, ToolResult
from runtime.tools.builtin import register_builtin_tools


class WeatherTool(Tool):
    name = "plugin.weather"
    description = "Weather from a plugin"

    async def execute(self, arguments, context=None):
        return ToolResult.ok("sunny")


class TestPluginScope:
    def _runtime(self):
        from models.records import AgentRun  # noqa: F401
        from core.database import init_db
        from repositories.event_repository import SQLAlchemyEventStore
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.runtime import AgentRuntime
        from services.agent_store import DBAgentStore
        init_db()
        registry = register_builtin_tools(ToolRegistry())
        return AgentRuntime(
            run_store=SQLAlchemyRunStore(),
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(store=SQLAlchemyEventStore()),
            tool_registry=registry,
            tool_runner=ToolExecutor(registry),
            provider_factory=lambda m: None,
        )

    def test_create_scope_and_mount_tool(self):
        rt = self._runtime()
        scope = rt.create_scope("skill.weather", name="Weather Skill")
        scope.mount_tool(WeatherTool())
        assert rt.get_tool("plugin.weather") is not None
        assert scope.mounted is True
        assert "plugin.weather" in scope.tools()
        scopes = rt.list_scopes()
        assert any(s["scope_id"] == "skill.weather" for s in scopes)

    def test_unmount_removes_only_owned_tools(self):
        rt = self._runtime()
        scope = rt.create_scope("s1")
        scope.mount_tool(WeatherTool())
        assert rt.get_tool("plugin.weather") is not None
        assert rt.get_tool("filesystem.read") is not None
        scope.unmount()
        assert rt.get_tool("plugin.weather") is None
        assert rt.get_tool("filesystem.read") is not None, "builtin untouched"

    def test_remove_scope(self):
        rt = self._runtime()
        rt.create_scope("s2").mount_tool(WeatherTool())
        assert rt.remove_scope("s2") is True
        assert rt.get_tool("plugin.weather") is None
        assert rt.remove_scope("s2") is False

    def test_plugin_context_registers_scoped(self):
        rt = self._runtime()
        ctx = rt.plugin_context("skill.weather", "weather-plugin", config={"units": "c"})
        ctx.register_tool(WeatherTool())
        assert rt.get_tool("plugin.weather") is not None
        assert ctx.scope_id == "skill.weather"
        assert ctx.config == {"units": "c"}
        assert ctx.to_dict()["name"] == "weather-plugin"

    def test_scope_isolation_two_plugins(self):
        rt = self._runtime()
        s1 = rt.create_scope("plugin-a")
        s2 = rt.create_scope("plugin-b")
        class ToolA(Tool):
            name = "a.tool"
            async def execute(self, arguments, context=None):
                return ToolResult.ok("A")
        class ToolB(Tool):
            name = "b.tool"
            async def execute(self, arguments, context=None):
                return ToolResult.ok("B")
        s1.mount_tool(ToolA())
        s2.mount_tool(ToolB())
        assert list(s1.tools().keys()) == ["a.tool"]
        assert list(s2.tools().keys()) == ["b.tool"]
        s1.unmount()
        assert rt.get_tool("a.tool") is None
        assert rt.get_tool("b.tool") is not None, "plugin B unaffected"

    @pytest.mark.asyncio
    async def test_plugin_context_events_on_single_bus(self):
        rt = self._runtime()
        ctx = rt.plugin_context("skill.x", "x")
        ev1 = await ctx.publish("plugin.loaded", {"name": "x"})
        ev2 = await ctx.publish("plugin.started", {"name": "x"})
        assert ev1.run_id == "plugin:skill.x"
        assert ev1.sequence == 1
        assert ev2.sequence == 2
        assert ev1.event_type == "plugin.loaded"
        assert ev2.correlation_id == "x"

    @pytest.mark.asyncio
    async def test_plugin_events_visible_to_subscriber(self):
        rt = self._runtime()
        ctx = rt.plugin_context("skill.y", "y")
        got = []
        async def sub(event):
            got.append(event.event_type)
        rt.event_bus.subscribe(sub)
        try:
            await ctx.publish("plugin.discovered")
            await ctx.publish("plugin.mounted")
        finally:
            rt.event_bus.unsubscribe(sub)
        assert got == ["plugin.discovered", "plugin.mounted"]

    def test_agent_uses_scoped_plugin_tool(self):
        from runtime.models import MockProvider
        from runtime.types import AgentConfig
        from services.agent_store import DBAgentStore
        rt = self._runtime()
        scope = rt.create_scope("skill.weather")
        scope.mount_tool(WeatherTool())
        rt.create_agent(AgentConfig(name="wbot", model="mock", tools=["plugin.weather"]))
        rt.provider_factory = lambda m: MockProvider(script=[
            MockProvider.tool_call("plugin.weather", {}),
            MockProvider.final("got weather"),
        ])
        run = rt.create_run(agent_id="wbot", input_text="weather?", user_id=1, execute=False)
    @pytest.mark.asyncio
    async def test_agent_uses_scoped_plugin_tool(self):
        from runtime.models import MockProvider
        from runtime.types import AgentConfig
        rt = self._runtime()
        scope = rt.create_scope("skill.weather")
        scope.mount_tool(WeatherTool())
        rt.create_agent(AgentConfig(name="wbot", model="mock", tools=["plugin.weather"]))
        rt.provider_factory = lambda m: MockProvider(script=[
            MockProvider.tool_call("plugin.weather", {}),
            MockProvider.final("got weather"),
        ])
        run = rt.create_run(agent_id="wbot", input_text="weather?", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "got weather"
        assert stored.tool_call_count == 1

    @pytest.mark.asyncio
    async def test_unmount_while_agent_references_tool(self):
        from runtime.models import MockProvider
        from runtime.types import AgentConfig
        rt = self._runtime()
        scope = rt.create_scope("skill.weather")
        scope.mount_tool(WeatherTool())
        rt.create_agent(AgentConfig(name="wbot2", model="mock", tools=["plugin.weather"]))
        scope.unmount()
        rt.provider_factory = lambda m: MockProvider(script=[
            MockProvider.tool_call("plugin.weather", {}),
            MockProvider.final("recovered"),
        ])
        run = rt.create_run(agent_id="wbot2", input_text="weather?", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        # tool no longer exists -> recorded as tool failure, run still completes
        assert stored.status == "COMPLETED"
        events = rt.list_events(run.run_id, user_id=1)
        assert any(e.event_type == "tool.call.failed" for e in events)
