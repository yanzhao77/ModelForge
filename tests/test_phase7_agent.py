"""Phase 7: Agent Engine tests."""
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.agent_tools import tool_file_read, tool_code_search, tool_command_execute
from services.agent_engine import AgentEngine


class TestAgentTools:
    """Tests for individual agent tools."""

    def test_file_read_existing(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write("Hello, world!")
            path = f.name
        try:
            result = tool_file_read(path)
            assert "Hello, world!" in result
        finally:
            os.unlink(path)

    def test_file_read_not_found(self):
        result = tool_file_read("/nonexistent/file_12345.txt")
        assert "Error" in result or "not found" in result.lower()

    def test_code_search_finds_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = os.path.join(tmpdir, "test.py")
            with open(py_file, "w", encoding="utf-8") as f:
                f.write("def hello_world():\n    return 'hi'\n")
            result = tool_code_search(tmpdir, "hello_world")
            assert "hello_world" in result

    def test_code_search_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool_code_search(tmpdir, "xyzzy_nonexistent_pattern")
            assert "No matches found" in result

    def test_code_search_bad_dir(self):
        result = tool_code_search("/nonexistent/dir", "pattern")
        assert "Error" in result

    def test_command_execute_echo(self):
        result = tool_command_execute("echo hello", timeout=10)
        assert "hello" in result

    @patch("services.agent_tools.subprocess.run")
    def test_command_execute_error(self, mock_run):
        mock_run.side_effect = Exception("simulated failure")
        result = tool_command_execute("some_command", timeout=5)
        assert "Error" in result


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

        agent = engine.get_agent("bot")
        messages = agent["messages"]
        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "msg1"
