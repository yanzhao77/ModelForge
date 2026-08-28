"""Phase 7: Agent Engine tests."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from core.agent_file_access import AgentFileAccessError, workspace_root_for_user
from core.config import settings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.agent_engine import AgentEngine
from services.agent_tools import tool_code_search, tool_command_execute, tool_file_read


class TestAgentTools:
    """Tests for individual agent tools."""

    @staticmethod
    def _workspace(tmp_path, monkeypatch, user_id=1):
        monkeypatch.setattr(settings, "agent_workspace_root", str(tmp_path / "agent-workspaces"))
        return workspace_root_for_user(user_id), SimpleNamespace(user_id=user_id)

    def test_file_read_existing(self, tmp_path, monkeypatch):
        workspace, context = self._workspace(tmp_path, monkeypatch)
        (workspace / "hello.txt").write_text("Hello, world!", encoding="utf-8")
        assert "Hello, world!" in tool_file_read("hello.txt", context)

    def test_file_read_rejects_missing_user_context(self, tmp_path, monkeypatch):
        self._workspace(tmp_path, monkeypatch)
        with pytest.raises(AgentFileAccessError, match="FILESYSTEM_USER_CONTEXT_REQUIRED"):
            tool_file_read("missing.txt")

    def test_code_search_finds_match(self, tmp_path, monkeypatch):
        workspace, context = self._workspace(tmp_path, monkeypatch)
        (workspace / "test.py").write_text("def hello_world():\n    return 'hi'\n", encoding="utf-8")
        result = tool_code_search(".", "hello_world", context)
        assert "hello_world" in result

    def test_code_search_no_match(self, tmp_path, monkeypatch):
        workspace, context = self._workspace(tmp_path, monkeypatch)
        (workspace / "test.py").write_text("def hello_world():\n    return 'hi'\n", encoding="utf-8")
        result = tool_code_search(".", "xyzzy_nonexistent_pattern", context)
        assert "No matches found" in result

    def test_code_search_rejects_external_directory(self, tmp_path, monkeypatch):
        _workspace, context = self._workspace(tmp_path, monkeypatch)
        with pytest.raises(AgentFileAccessError, match="RESOURCE_OUTSIDE_ALLOWED_ROOT"):
            tool_code_search("/nonexistent/dir", "pattern", context)

    def test_command_execute_disabled_by_default(self):
        result = tool_command_execute("echo hello", timeout=10)
        assert "disabled" in result.lower()

    @patch("services.agent_tools.subprocess.run")
    def test_command_execute_error(self, mock_run):
        mock_run.side_effect = Exception("simulated failure")
        with patch.object(settings.tools, "command_execution_enabled", True):
            result = tool_command_execute("pwd", timeout=5)
        assert "Error" in result
        assert mock_run.call_args.args[0] == ["pwd"]
        assert mock_run.call_args.kwargs["shell"] is False


class TestAgentEngine:
    """Tests for the agent engine."""

    def test_create_agent(self):
        engine = AgentEngine()
        info = engine.create_agent("test-bot", "llama2", ["file_read", "code_search"])
        assert info["name"] == "test-bot"
        assert info["model"] == "llama2"
        assert "file_read" in info["tools"]

    def test_chat_no_llm(self):
        engine = AgentEngine()
        engine.create_agent("bot", "llama2", ["file_read"])
        result = engine.chat("bot", "Hello!")
        assert "response" in result
        assert "file_read" in result["response"]

    def test_chat_with_llm_callback(self):
        engine = AgentEngine()
        engine.create_agent("bot", "gpt-4", ["code_search"])

        def fake_llm(messages):
            return "I found the code you need."

        result = engine.chat("bot", "Find my code", llm_callback=fake_llm)
        assert result["response"] == "I found the code you need."
        assert result["model"] == "gpt-4"

    def test_chat_unknown_agent(self):
        engine = AgentEngine()
        result = engine.chat("nonexistent", "Hi")
        assert "error" in result

    def test_list_agents(self):
        engine = AgentEngine()
        engine.create_agent("a1", "m1", [])
        engine.create_agent("a2", "m2", ["file_read"])
        agents = engine.list_agents()
        assert len(agents) == 2
        names = [a["name"] for a in agents]
        assert "a1" in names
        assert "a2" in names

    def test_get_agent(self):
        engine = AgentEngine()
        engine.create_agent("test", "llama2", ["file_read"])
        agent = engine.get_agent("test")
        assert agent is not None
        assert agent["name"] == "test"

    def test_get_agent_missing(self):
        engine = AgentEngine()
        assert engine.get_agent("nope") is None

    def test_chat_preserves_history(self):
        engine = AgentEngine()
        engine.create_agent("bot", "gpt-4", [])

        def fake_llm(messages):
            return "response"

        engine.chat("bot", "msg1", llm_callback=fake_llm)
        engine.chat("bot", "msg2", llm_callback=fake_llm)

        from langchain_core.messages import AIMessage, HumanMessage

        agent = engine.get_agent("bot")
        messages = agent["messages"]
        assert len(messages) == 4
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "msg1"
        assert isinstance(messages[1], AIMessage)
        assert messages[1].content == "response"
        assert messages[2].content == "msg2"
        assert messages[3].content == "response"
