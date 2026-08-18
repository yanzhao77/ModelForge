"""3.x-P2 tests: PluginManager - manifest/load/lifecycle/dependency/mount-unmount (audit §16)."""
import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.plugins import PluginManager, PluginManifest
from runtime.plugins.manager import PLUGIN_LIFECYCLE_EVENTS

PLUGIN_ENTRY = """
from runtime.tools import Tool, ToolResult


class WeatherTool(Tool):
    name = "plugin.weather"
    description = "Weather from a plugin"

    async def execute(self, arguments, context=None):
        return ToolResult.ok("sunny 25C")


def get_tools(ctx):
    return [WeatherTool()]
"""


def make_plugin_dir():
    tmp = tempfile.mkdtemp(prefix="mf_plugin_")
    pdir = os.path.join(tmp, "weather")
    os.makedirs(pdir)
    with open(os.path.join(pdir, "plugin.yaml"), "w", encoding="utf-8") as f:
        f.write("name: weather\nversion: 1.0.0\ntype: tool\nentry: weather_plugin.py\ndependencies: []\n")
    with open(os.path.join(pdir, "weather_plugin.py"), "w", encoding="utf-8") as f:
        f.write(PLUGIN_ENTRY)
    return tmp


def make_runtime(plugins_dir=None):
    from core.database import init_db
    from models.records import AgentRun  # noqa: F401
    from repositories.event_repository import SQLAlchemyEventStore
    from repositories.run_repository import SQLAlchemyRunStore
    from runtime.events import EventBus
    from runtime.runtime import AgentRuntime
    from runtime.tools import ToolExecutor, ToolRegistry
    from runtime.tools.builtin import register_builtin_tools
    from services.agent_store import DBAgentStore
    init_db()
    registry = register_builtin_tools(ToolRegistry())
    rt = AgentRuntime(
        run_store=SQLAlchemyRunStore(),
        agent_store=DBAgentStore(engine=None),
        event_bus=EventBus(store=SQLAlchemyEventStore()),
        tool_registry=registry,
        tool_runner=ToolExecutor(registry),
        provider_factory=lambda m: None,
    )
    if plugins_dir:
        rt.plugin_manager = PluginManager(rt, plugins_dir=plugins_dir, event_bus=rt.event_bus)
    return rt


class TestPluginManager:
    def test_discover_finds_manifest(self):
        tmp = make_plugin_dir()
        rt = make_runtime(plugins_dir=tmp)
        found = rt.get_plugin_manager().discover()
        assert any(p["name"] == "weather" for p in found)
        weather = [p for p in found if p["name"] == "weather"][0]
        assert weather["problems"] == []

    def test_load_registers_tool(self):
        tmp = make_plugin_dir()
        rt = make_runtime(plugins_dir=tmp)
        pm = rt.get_plugin_manager()
        manifest = PluginManifest.from_file(os.path.join(tmp, "weather", "plugin.yaml"))
        state = pm.load(manifest)
        assert state["status"] == "loaded"
        assert rt.get_tool("plugin.weather") is not None
        assert "plugin.weather" in state["scope"].tools()

    def test_lifecycle_events_and_states(self):
        tmp = make_plugin_dir()
        rt = make_runtime(plugins_dir=tmp)
        pm = rt.get_plugin_manager()
        manifest = PluginManifest.from_file(os.path.join(tmp, "weather", "plugin.yaml"))
        pm.load(manifest)
        assert pm.start("weather") is True
        assert pm.get("weather")["status"] == "started"
        assert pm.stop("weather") is True
        assert pm.mount("weather") is True
        assert pm.unmount("weather") is True
        assert rt.get_tool("plugin.weather") is None, "unmount removes plugin tools"
        assert pm.list()[0]["name"] == "weather"

    def test_manifest_validation(self):
        rt = make_runtime()
        pm = rt.get_plugin_manager()
        with pytest.raises(ValueError):
            pm.load(PluginManifest(name="", type="tool"))
        with pytest.raises(ValueError):
            pm.load(PluginManifest(name="bad", type="bogus"))

    def test_dependency_resolution(self):
        rt = make_runtime()
        pm = rt.get_plugin_manager()
        pm.load(PluginManifest(name="base", type="skill"))
        with pytest.raises(ValueError):
            pm.load(PluginManifest(name="child", type="tool", dependencies=["missing"]))
        pm.load(PluginManifest(name="child", type="skill", dependencies=["base"]))
        assert pm.dependencies_of("child") == ["base"]

    @pytest.mark.asyncio
    async def test_plugin_events_on_bus(self):
        tmp = make_plugin_dir()
        rt = make_runtime(plugins_dir=tmp)
        pm = rt.get_plugin_manager()
        manifest = PluginManifest.from_file(os.path.join(tmp, "weather", "plugin.yaml"))
        pm.load(manifest)
        got = []
        async def sub(event):
            if event.run_id == "plugin:manager":
                got.append(event.event_type)
        rt.event_bus.subscribe(sub)
        try:
            pm.start("weather")
            pm.stop("weather")
            pm.mount("weather")
            await asyncio.sleep(0.05)
        finally:
            rt.event_bus.unsubscribe(sub)
        assert "plugin.loaded" in got
        assert "plugin.started" in got
        assert "plugin.stopped" in got
        assert "plugin.mounted" in got
        for e in PLUGIN_LIFECYCLE_EVENTS:
            assert e.startswith("plugin.")

    @pytest.mark.asyncio
    async def test_agent_runs_plugin_tool(self):
        tmp = make_plugin_dir()
        rt = make_runtime(plugins_dir=tmp)
        pm = rt.get_plugin_manager()
        manifest = PluginManifest.from_file(os.path.join(tmp, "weather", "plugin.yaml"))
        pm.load(manifest)
        from runtime.models import MockProvider
        from runtime.types import AgentConfig
        rt.create_agent(AgentConfig(name="p2bot", model="mock", tools=["plugin.weather"]))
        rt.provider_factory = lambda m: MockProvider(script=[
            MockProvider.tool_call("plugin.weather", {}),
            MockProvider.final("weather ok"),
        ])
        run = rt.create_run(agent_id="p2bot", input_text="weather?", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "weather ok"
        assert stored.tool_call_count == 1

    def test_unload_removes_plugin(self):
        tmp = make_plugin_dir()
        rt = make_runtime(plugins_dir=tmp)
        pm = rt.get_plugin_manager()
        manifest = PluginManifest.from_file(os.path.join(tmp, "weather", "plugin.yaml"))
        pm.load(manifest)
        assert pm.unload("weather") is True
        assert rt.get_tool("plugin.weather") is None
        assert pm.get("weather") is None

    def test_api_load_list_unmount(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            r = c.get("/api/v1/plugins/discover")
            assert r.status_code == 200
            assert "plugins" in r.json()
            r = c.post("/api/v1/plugins/load", json={"manifest": {
                "name": "apiplugin", "version": "1.0.0", "type": "skill", "entry": None,
            }})
            assert r.status_code == 200, r.text
            assert r.json()["name"] == "apiplugin"
            r = c.post("/api/v1/plugins/apiplugin/start")
            assert r.status_code == 200
            r = c.post("/api/v1/plugins/apiplugin/unmount")
            assert r.status_code == 200
            r = c.delete("/api/v1/plugins/apiplugin")
            assert r.status_code == 200
            r = c.post("/api/v1/plugins/ghost/start")
            assert r.status_code == 404