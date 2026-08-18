"""Phase 4: Tool Registry tests - protocol, registry, executor, builtins (spec 67)."""
import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.errors import ToolNotFoundError, ToolTimeoutError
from runtime.run_context import ToolExecutionContext
from runtime.tools import PermissionLevel, Tool, ToolExecutor, ToolRegistry, ToolResult
from runtime.tools.builtin import register_builtin_tools


class EchoTool(Tool):
    name = "echo"
    description = "Echo input back"

    def input_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    async def execute(self, arguments, context=None):
        return ToolResult.ok("echo: " + str(arguments.get("text", "")))


class SlowTool(Tool):
    name = "slow"
    description = "Sleeps longer than its timeout"
    timeout = 0.05

    async def execute(self, arguments, context=None):
        await asyncio.sleep(1.0)
        return ToolResult.ok("done")


class FlakyTool(Tool):
    name = "flaky"
    description = "Fails twice then succeeds"
    retry_count = 2
    retry_delay = 0.0
    retryable_errors = ["*"]

    def __init__(self):
        self.calls = 0

    async def execute(self, arguments, context=None):
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("transient failure")
        return ToolResult.ok("recovered")


class BoomTool(Tool):
    name = "boom"
    description = "Always fails, not retryable"

    async def execute(self, arguments, context=None):
        raise RuntimeError("kaboom")


def make_ctx(run_id="r", agent_id="a"):
    return ToolExecutionContext(user_id=1, agent_id=agent_id, run_id=run_id, timeout=5.0)


class TestToolProtocol:
    @pytest.mark.asyncio
    async def test_tool_execute_returns_result(self):
        tool = EchoTool()
        result = await tool.execute({"text": "hi"}, make_ctx())
        assert result.success is True
        assert result.to_text() == "echo: hi"

    def test_tool_result_err(self):
        r = ToolResult.err("bad")
        assert r.success is False
        assert r.to_text().startswith("Error:")

    def test_schema_shape(self):
        tool = EchoTool()
        s = tool.schema()
        assert s["type"] == "function"
        assert s["function"]["name"] == "echo"
        assert "parameters" in s["function"]

    def test_to_dict_includes_policy_fields(self):
        tool = EchoTool()
        d = tool.to_dict()
        assert "permissions" in d
        assert "timeout" in d
        assert "retry_policy" in d
        assert d["retry_policy"]["retry_count"] == 0

    def test_permission_levels(self):
        for lvl in ("READ", "WRITE", "EXECUTE", "NETWORK", "SYSTEM", "ADMIN"):
            assert getattr(PermissionLevel, lvl) is not None


class TestToolRegistry:
    def test_register_get_list(self):
        r = ToolRegistry()
        r.register(EchoTool())
        assert r.get("echo") is not None
        assert "echo" in r
        assert r.names() == ["echo"]

    def test_aliases(self):
        r = ToolRegistry()
        tool = EchoTool()
        tool.aliases = ["echo2"]
        r.register(tool, aliases=["echo1"])
        assert r.get("echo1").name == "echo"
        assert r.get("echo2").name == "echo"
        assert r.canonical("echo1") == "echo"

    def test_unregister(self):
        r = ToolRegistry()
        r.register(EchoTool())
        assert r.unregister("echo") is True
        assert r.unregister("echo") is False

    def test_schemas_for_names(self):
        r = ToolRegistry()
        r.register(EchoTool())
        schemas = r.schemas(["echo", "missing"])
        assert len(schemas) == 1

    def test_builtins_registered_with_permissions(self):
        r = register_builtin_tools(ToolRegistry())
        assert r.get("filesystem.read") is not None
        assert r.get("shell.execute") is not None
        assert r.get("web.search") is not None
        assert PermissionLevel.READ in r.get("filesystem.read").permissions
        assert PermissionLevel.EXECUTE in r.get("shell.execute").permissions
        assert PermissionLevel.NETWORK in r.get("web.search").permissions
        assert r.canonical("file_read") == "filesystem.read"
        assert r.canonical("command_execute") == "shell.execute"

    def test_legacy_tools_keep_working(self):
        r = register_builtin_tools(ToolRegistry())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello world")
            path = f.name
        try:
            executor = ToolExecutor(r)
            loop = asyncio.new_event_loop()
            out = loop.run_until_complete(executor.run("file_read", {"filepath": path}, make_ctx()))
            loop.close()
            assert "hello world" in out
        finally:
            os.unlink(path)


class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self):
        ex = ToolExecutor(ToolRegistry())
        with pytest.raises(ToolNotFoundError):
            await ex.run("nope", {}, make_ctx())

    @pytest.mark.asyncio
    async def test_timeout(self):
        r = ToolRegistry()
        r.register(SlowTool())
        ex = ToolExecutor(r)
        with pytest.raises(ToolTimeoutError):
            await ex.run("slow", {}, make_ctx())

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        r = ToolRegistry()
        flaky = FlakyTool()
        r.register(flaky)
        ex = ToolExecutor(r)
        out = await ex.run("flaky", {}, make_ctx())
        assert out == "recovered"
        assert flaky.calls == 3

    @pytest.mark.asyncio
    async def test_non_retryable_failure_returns_error_text(self):
        r = ToolRegistry()
        r.register(BoomTool())
        ex = ToolExecutor(r)
        out = await ex.run("boom", {}, make_ctx())
        assert out == "Error: kaboom"

    @pytest.mark.asyncio
    async def test_invalid_arguments(self):
        from runtime.tools.builtin import FunctionTool
        r = ToolRegistry()
        r.register(FunctionTool(
            "strict", "strict tool",
            lambda text: "got " + text,
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ))
        ex = ToolExecutor(r)
        out = await ex.run("strict", {"unexpected": 1}, make_ctx())
        assert "Error" in out

class TestRuntimeTools:
    @pytest.mark.asyncio
    async def test_run_with_builtin_tool_via_runtime(self):
        from core.database import init_db
        from models.records import AgentRun  # noqa: F401
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.models import MockProvider
        from runtime.runtime import AgentRuntime
        from runtime.tools import ToolExecutor, ToolRegistry
        from runtime.tools.builtin import register_builtin_tools
        from runtime.types import AgentConfig
        from services.agent_store import DBAgentStore
        init_db()
        registry = register_builtin_tools(ToolRegistry())
        rt = AgentRuntime(
            run_store=SQLAlchemyRunStore(),
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(),
            tool_registry=registry,
            tool_runner=ToolExecutor(registry),
            provider_factory=lambda m: MockProvider(script=[
                MockProvider.tool_call("filesystem.read", {"filepath": "/etc/hostname"}),
                MockProvider.final("read done"),
            ]),
        )
        rt.create_agent(AgentConfig(name="toolbot4", model="mock", tools=["filesystem.read"]))
        run = rt.create_run(agent_id="toolbot4", input_text="read a file", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.tool_call_count == 1
        assert stored.output == "read done"
        names = [t["name"] for t in rt.list_tools()]
        assert "filesystem.read" in names
        assert "shell.execute" in names

    def test_tool_api(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            assert c.get("/api/v1/agent/tools").status_code == 401
            c.post("/api/v1/auth/register", json={"username": "toolapiuser", "password": "secret123", "email": "toolapiuser@example.com"})
            login = c.post("/api/v1/auth/login", json={"username": "toolapiuser", "password": "secret123"})
            headers = {"Authorization": "Bearer " + login.json()["token"]}
            r = c.get("/api/v1/agent/tools", headers=headers)
            assert r.status_code == 200
            names = [t["name"] for t in r.json()["tools"]]
            assert "filesystem.read" in names
            assert "web.search" in names
