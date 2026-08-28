"""Phase 7: MCP tests - client, registry, adapter, runtime integration (spec 70)."""
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.mcp import MCPClient, MCPRegistry
from runtime.tools import ToolExecutor, ToolRegistry

FAKE_TOOLS = [
    {"name": "mcp.weather", "description": "Get weather", "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    {"name": "mcp.time", "description": "Get time", "inputSchema": {"type": "object", "properties": {}}},
]

CALL_RESULTS = {
    "mcp.weather": {"content": [{"type": "text", "text": "sunny in Beijing"}], "isError": False},
    "mcp.time": {"content": [{"type": "text", "text": "12:00"}], "isError": False},
}


def fake_transport():
    def handler(request):
        payload = json.loads(request.content)
        method = payload.get("method")
        rid = payload.get("id")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake-mcp", "version": "1.0"}}
        elif method == "tools/list":
            result = {"tools": FAKE_TOOLS}
        elif method == "tools/call":
            tname = payload.get("params", {}).get("name")
            result = CALL_RESULTS.get(tname, {"content": [{"type": "text", "text": "ok"}], "isError": False})
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": result})
    return httpx.MockTransport(handler)


class TestMCPClient:
    @pytest.mark.asyncio
    async def test_initialize_list_call(self):
        client = MCPClient("fake", "http://fake/mcp").with_transport(fake_transport())
        info = await client.initialize()
        assert info["serverInfo"]["name"] == "fake-mcp"
        tools = await client.list_tools()
        assert [t["name"] for t in tools] == ["mcp.weather", "mcp.time"]
        out = await client.call_tool("mcp.weather", {"city": "Beijing"})
        assert out == "sunny in Beijing"

    @pytest.mark.asyncio
    async def test_rpc_error_raises(self):
        def err_handler(request):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "method not found"}})
        client = MCPClient("bad", "http://bad/mcp").with_transport(httpx.MockTransport(err_handler))
        with pytest.raises(RuntimeError):
            await client.initialize()


class TestMCPRegistry:
    @pytest.mark.asyncio
    async def test_sync_tools_registers_adapters(self):
        client = MCPClient("fake", "http://fake/mcp").with_transport(fake_transport())
        await client.initialize()
        await client.list_tools()
        registry = MCPRegistry()
        registry.register(client)
        tools = ToolRegistry()
        count = registry.sync_tools(tools)
        assert count == 2
        assert tools.get("mcp.weather") is not None
        assert tools.get("mcp.weather").source == "mcp"
        # agent sees it like any tool
        executor = ToolExecutor(tools)
        schema = executor.schema("mcp.weather")
        assert schema["function"]["name"] == "mcp.weather"
        out = await executor.run("mcp.weather", {"city": "Beijing"}, None)
        assert out == "sunny in Beijing"

    def test_registry_crud(self):
        registry = MCPRegistry()
        client = MCPClient("s1", "http://x/mcp")
        registry.register(client)
        assert registry.names() == ["s1"]
        assert registry.unregister("s1") is True
        assert registry.unregister("s1") is False


class TestRuntimeMCP:
    @pytest.mark.asyncio
    async def test_register_server_and_run_tool(self):
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
                MockProvider.tool_call("mcp.weather", {"city": "Beijing"}),
                MockProvider.final("weather fetched"),
            ]),
        )
        info = await rt.register_mcp_server("fake", "http://fake/mcp", transport=fake_transport())
        assert info["tools"] == 2
        # MCP tools are NETWORK permission -> policy must allow network
        rt.create_agent(AgentConfig(
            name="mcpbot", model="mock", tools=["mcp.weather"],
            policy={"network_access": True},
        ))
        run = rt.create_run(agent_id="mcpbot", input_text="weather?", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        assert stored.output == "weather fetched"
        servers = rt.list_mcp_servers()
        assert any(s["name"] == "fake" for s in servers)
        # cleanup
        assert await rt.unregister_mcp_server("fake") is True
        assert rt.get_tool("mcp.weather") is None

    def test_mcp_api(self):
        from unittest.mock import patch

        from core.config import settings
        from fastapi.testclient import TestClient
        from main import app
        with patch.object(settings, "runtime_admin_usernames", "mcpapiadmin"):
            with TestClient(app) as c:
                c.post("/api/v1/auth/register", json={"username": "mcpapiadmin", "password": "secret123", "email": "mcpapiadmin@example.com"})
                login = c.post("/api/v1/auth/login", json={"username": "mcpapiadmin", "password": "secret123"})
                headers = {"Authorization": "Bearer " + login.json()["token"]}
                r = c.post("/api/v1/agent/mcp/servers", json={"name": "fake", "endpoint": "http://fake/mcp", "confirm": True}, headers=headers)
                # no live server at that endpoint -> registration fails cleanly
                assert r.status_code == 400
                r = c.get("/api/v1/agent/mcp/servers", headers=headers)
                assert r.status_code == 200
                assert "servers" in r.json()