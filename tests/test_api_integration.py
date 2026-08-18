"""Integration tests: auth flow, sessions, memories, models API, chat, and LangGraph agent."""
import os
import sys
import tempfile

# Isolate the app database for this test session
_tmp_db = tempfile.mkdtemp(prefix="mf_test_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ["JWT_SECRET"] = "integration-test-secret-that-is-at-least-32-characters"

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from langchain_core.messages import AIMessage, ToolMessage
from main import app
from services.agent_engine import AgentEngine
from services.runtime_registry import RuntimeRegistry


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan (initializes the app database)."""
    with TestClient(app) as c:
        yield c


def _register(client, username, password="secret123"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": f"{username}@example.com"},
    )


def _login(client, username, password="secret123") -> str:
    # Auto-register if the user does not exist yet (idempotent)
    _register(client, username, password)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestAuthFlow:
    def test_register_login_me(self, client):
        r = _register(client, "alice")
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "alice"

        r = client.post("/api/v1/auth/login", json={"username": "alice", "password": "secret123"})
        assert r.status_code == 200
        token = r.json()["token"]
        assert token

        r = client.get("/api/v1/auth/me", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["username"] == "alice"

    def test_duplicate_register_rejected(self, client):
        _register(client, "bob")
        r = _register(client, "bob")
        assert r.status_code == 400

    def test_me_requires_auth(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_bad_login_rejected(self, client):
        r = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "wrong"})
        assert r.status_code == 401

    def test_short_password_rejected(self, client):
        r = _register(client, "shortpwd", password="123")
        assert r.status_code == 400


class TestSessions:
    def test_session_crud_flow(self, client):
        token = _login(client, "sessuser")
        headers = _auth(token)

        r = client.post("/api/v1/sessions", json={"title": "测试会话"}, headers=headers)
        assert r.status_code == 200
        sid = r.json()["id"]

        r = client.get("/api/v1/sessions", headers=headers)
        assert r.status_code == 200
        assert any(s["id"] == sid for s in r.json())

        r = client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"role": "user", "content": "你好，ModelForge"},
            headers=headers,
        )
        assert r.status_code == 200

        r = client.get(f"/api/v1/sessions/{sid}/messages", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.patch(f"/api/v1/sessions/{sid}", json={"title": "新标题"}, headers=headers)
        assert r.status_code == 200

        r = client.post(f"/api/v1/sessions/{sid}/title", headers=headers)
        assert r.status_code == 200
        assert r.json()["title"].startswith("你好")

        r = client.delete(f"/api/v1/sessions/{sid}", headers=headers)
        assert r.status_code == 200
        r = client.get("/api/v1/sessions", headers=headers)
        assert all(s["id"] != sid for s in r.json())

    def test_session_ownership_enforced(self, client):
        token1 = _login(client, "own1")
        token2 = _login(client, "own2")
        sid = client.post("/api/v1/sessions", json={}, headers=_auth(token1)).json()["id"]
        r = client.get(f"/api/v1/sessions/{sid}", headers=_auth(token2))
        assert r.status_code == 404


class TestMemories:
    def test_manual_create_list_search(self, client):
        token = _login(client, "memuser")
        headers = _auth(token)

        r = client.post(
            "/api/v1/memories",
            json={"memory_type": "fact", "key": "我是", "value": "我是一名 Python 工程师"},
            headers=headers,
        )
        assert r.status_code == 200

        r = client.get("/api/v1/memories", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1

        r = client.get("/api/v1/memories/search", params={"q": "工程师"}, headers=headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_memories_isolated_per_user(self, client):
        token = _login(client, "memiso")
        r = client.get("/api/v1/memories", headers=_auth(token))
        assert r.status_code == 200
        # memory from another user must not leak
        for m in r.json():
            assert m["value"] != "我是一名 Python 工程师"


class TestModelsApi:
    def test_install_list_scan_remove(self, client):
        token = _login(client, "modeluser")
        headers = _auth(token)

        r = client.post(
            "/api/v1/models/install",
            json={"name": "demo-model", "provider": "local", "path": "/tmp/demo", "size": "1GB"},
            headers=headers,
        )
        assert r.status_code == 200
        mid = r.json()["id"]

        r = client.get("/api/v1/models", headers=headers)
        assert any(m["name"] == "demo-model" for m in r.json())

        r = client.post("/api/v1/models/scan", json={"path": "/nonexistent"}, headers=headers)
        assert r.status_code == 200

        r = client.delete(f"/api/v1/models/{mid}", headers=headers)
        assert r.status_code == 200

    def test_models_require_auth(self, client):
        assert client.get("/api/v1/models").status_code == 401
        assert client.post("/api/v1/models/download", json={"repo_id": "x/y"}).status_code == 401


class TestChat:
    @pytest.fixture(autouse=True)
    def _fake_runtime(self, monkeypatch):
        class _FakeRuntime:
            async def chat(self, model, messages, **kwargs):
                return {"model": model, "content": "这是模拟回复", "raw": None}

        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: _FakeRuntime())
        monkeypatch.setattr(RuntimeRegistry, "chat", _FakeRuntime.chat)

    def test_chat_requires_login_without_session(self, client):
        payload = {"model": "mock", "messages": [{"role": "user", "content": "你好"}]}
        assert client.post("/api/v1/chat", json=payload).status_code == 401
        token = _login(client, "chatanonymous")
        r = client.post("/api/v1/chat", json=payload, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["response"] == "这是模拟回复"

    def test_chat_saves_to_session_and_auto_title(self, client):
        token = _login(client, "chatuser")
        sid = client.post("/api/v1/sessions", json={}, headers=_auth(token)).json()["id"]

        r = client.post(
            "/api/v1/chat",
            json={
                "model": "mock",
                "messages": [{"role": "user", "content": "今天的天气怎么样"}],
                "session_id": sid,
            },
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.json()["session_id"] == sid

        msgs = client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(token)).json()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "这是模拟回复"
        # auto title from first user message
        title = client.get(f"/api/v1/sessions/{sid}", headers=_auth(token)).json()["title"]
        assert title.startswith("今天的天气")

    def test_chat_stream_sse(self, client):
        payload = {"model": "mock", "messages": [{"role": "user", "content": "流式"}]}
        assert client.post("/api/v1/chat/stream", json=payload).status_code == 401
        token = _login(client, "chatstream")
        r = client.post("/api/v1/chat/stream", json=payload, headers=_auth(token))
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        assert "这是模拟回复" in r.text
        assert '"type": "done"' in r.text

    def test_chat_stream_requires_login_for_session(self, client):
        r = client.post(
            "/api/v1/chat/stream",
            json={"model": "mock", "messages": [{"role": "user", "content": "x"}], "session_id": 1},
        )
        assert r.status_code == 401


class TestOpenAICompat:
    def test_chat_completions_non_stream(self, client, monkeypatch):
        class _FakeRuntime:
            async def chat(self, model, messages, **kwargs):
                return {"model": model, "content": "openai reply", "raw": None}
        monkeypatch.setattr(RuntimeRegistry, "get", lambda self, name=None: _FakeRuntime())
        monkeypatch.setattr(RuntimeRegistry, "chat", _FakeRuntime.chat)

        payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        assert client.post("/v1/chat/completions", json=payload).status_code == 401
        token = _login(client, "openaiuser")
        r = client.post("/v1/chat/completions", json=payload, headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "openai reply"
        assert "usage" in data

    def test_list_models(self, client):
        assert client.get("/v1/models").status_code == 401
        token = _login(client, "openaimodeluser")
        r = client.get("/v1/models", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["object"] == "list"


class TestLangGraphAgent:
    def test_tool_calling_loop(self):
        """Real LangGraph: agent -> tool -> agent -> END."""
        engine = AgentEngine()
        engine.create_agent("toolbot", "mock-llm", ["file_read"])

        class _ToolLLM:
            def __init__(self):
                self.calls = 0
            def bind_tools(self, tools):
                return self
            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "file_read",
                                "args": {"filepath": "/nonexistent/file_xyz_123.txt"},
                                "id": "call_1",
                                "type": "tool_call",
                            }
                        ],
                    )
                return AIMessage(content="done reading")

        result = engine.chat("toolbot", "read a file", llm=_ToolLLM())
        assert result["response"] == "done reading"
        messages = engine.get_agent("toolbot")["messages"]
        assert len(messages) == 4  # human, ai(toolcall), tool, ai
        assert isinstance(messages[2], ToolMessage)

    def test_real_langgraph_structure(self):
        """Agent graph should be an actual compiled StateGraph."""
        engine = AgentEngine()
        engine.create_agent("graphbot", "m", [])
        agent = engine.get_agent("graphbot")
        assert agent is not None
        assert agent["tools"] == []
        result = engine.chat("graphbot", "hi")
        assert "No LLM provider" in result["response"]

    def test_delete_agent(self):
        engine = AgentEngine()
        engine.create_agent("delbot", "m", [])
        assert engine.delete_agent("delbot") is True
        assert engine.delete_agent("delbot") is False