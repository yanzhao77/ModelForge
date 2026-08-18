"""3.x-P6 tests: Capability Discovery (audit §16.9)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

_tmp_db = tempfile.mkdtemp(prefix="mf_p6_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

from runtime.plugins import PluginManager, PluginManifest
from runtime.tools import Tool, ToolResult


class CapTool(Tool):
    name = "cap.tool"
    description = "capability tool"

    async def execute(self, arguments, context=None):
        return ToolResult.ok("ok")


def make_runtime():
    from core.database import init_db
    from models.records import AgentRun  # noqa: F401
    from repositories.run_repository import SQLAlchemyRunStore
    from runtime.events import EventBus
    from runtime.runtime import AgentRuntime
    from runtime.tools import ToolExecutor, ToolRegistry
    from runtime.tools.builtin import register_builtin_tools
    from services.agent_store import DBAgentStore
    init_db()
    registry = register_builtin_tools(ToolRegistry())
    return AgentRuntime(
        run_store=SQLAlchemyRunStore(),
        agent_store=DBAgentStore(engine=None),
        event_bus=EventBus(),
        tool_registry=registry,
        tool_runner=ToolExecutor(registry),
        provider_factory=lambda m: None,
    )


SKILL_PY = """
from runtime.context.contributor import ContextSegment

def contribute(ctx):
    return [ContextSegment(content="skill x", section="skill")]
"""

AGENT_PY = """
from runtime.tools import Tool, ToolResult

class AT(Tool):
    name = "agent.cap.tool"
    async def execute(self, arguments, context=None):
        return ToolResult.ok("a")

def extend_agent(ctx):
    return {"tools": [AT()]}
"""


def make_plugin_dir():
    tmp = tempfile.mkdtemp(prefix="mf_p6p_")
    sk = os.path.join(tmp, "skill.cap")
    os.makedirs(sk)
    with open(os.path.join(sk, "plugin.yaml"), "w", encoding="utf-8") as f:
        f.write("name: skill.cap\ntype: skill\nentry: s.py\n")
    with open(os.path.join(sk, "s.py"), "w", encoding="utf-8") as f:
        f.write(SKILL_PY)
    ap = os.path.join(tmp, "agent.cap")
    os.makedirs(ap)
    with open(os.path.join(ap, "plugin.yaml"), "w", encoding="utf-8") as f:
        f.write("name: agent.cap\ntype: agent\nentry: a.py\n")
    with open(os.path.join(ap, "a.py"), "w", encoding="utf-8") as f:
        f.write(AGENT_PY)
    return tmp


class TestCapabilityDiscovery:
    def test_builtin_tools_indexed(self):
        rt = make_runtime()
        idx = rt.discover_capabilities()
        names = [t["name"] for t in idx["tools"]]
        assert "filesystem.read" in names
        assert "shell.execute" in names
        assert "agent.delegate" in names
        assert idx["skills"] == []
        assert idx["agent_extensions"] == []

    def test_plugin_tool_scoped(self):
        rt = make_runtime()
        scope = rt.create_scope("cap-scope")
        scope.mount_tool(CapTool())
        all_idx = rt.discover_capabilities()
        cap = [t for t in all_idx["tools"] if t["name"] == "cap.tool"][0]
        assert cap["scope"] == "cap-scope"
        scoped = rt.discover_capabilities(scope_id="cap-scope")
        assert [t["name"] for t in scoped["tools"]] == ["cap.tool"]
        other = rt.discover_capabilities(scope_id="other")
        assert other["tools"] == []

    def test_skill_and_agent_plugins_indexed(self):
        tmp = make_plugin_dir()
        rt = make_runtime()
        rt.plugin_manager = PluginManager(rt, plugins_dir=tmp, event_bus=rt.event_bus)
        rt.plugin_manager.load(PluginManifest.from_file(os.path.join(tmp, "skill.cap", "plugin.yaml")))
        rt.plugin_manager.load(PluginManifest.from_file(os.path.join(tmp, "agent.cap", "plugin.yaml")))
        idx = rt.discover_capabilities()
        assert any(s["name"] == "skill.cap" and s["contribution_count"] == 1 for s in idx["skills"])
        ext = [e for e in idx["agent_extensions"] if e["name"] == "agent.cap"][0]
        assert "agent.cap.tool" in ext["tools"]
        assert any(t["name"] == "agent.cap.tool" for t in idx["tools"])

    def test_api_capabilities(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            r = c.get("/api/v1/plugins/capabilities")
            assert r.status_code == 200
            data = r.json()
            assert "tools" in data and "skills" in data and "agent_extensions" in data
            names = [t["name"] for t in data["tools"]]
            assert "filesystem.read" in names