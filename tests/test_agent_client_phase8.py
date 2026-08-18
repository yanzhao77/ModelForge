"""Phase 8: Client tests - api_client agent methods + structural page checks (spec 71)."""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from api_client.client import ModelForgeClient


class TestAgentRunApiClient:
    @patch("api_client.client.httpx.Client.post")
    def test_create_agent_run(self, mock_post):
        resp = MagicMock()
        resp.json.return_value = {"run_id": "r123", "status": "PENDING", "agent_id": "bot"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        c = ModelForgeClient("http://x")
        out = c.create_agent_run("bot", "do it", execute=False)
        assert out["run_id"] == "r123"
        kwargs = mock_post.call_args[1]
        assert kwargs["json"]["execute"] is False
        assert kwargs["json"]["agent_id"] == "bot"

    @patch("api_client.client.httpx.Client.get")
    def test_get_agent_run_and_events(self, mock_get):
        def side_effect(url, **kw):
            r = MagicMock()
            payload = {"run_id": "r", "status": "COMPLETED", "events": [{"sequence": 1}]} if "events" in url else {"run_id": "r", "status": "COMPLETED"}
            r.json.return_value = payload
            r.raise_for_status = MagicMock()
            return r
        mock_get.side_effect = side_effect
        c = ModelForgeClient("http://x")
        assert c.get_agent_run("r")["status"] == "COMPLETED"
        assert c.get_agent_run_events("r", after_sequence=2) == [{"sequence": 1}]

    @patch("api_client.client.httpx.Client.post")
    def test_cancel_approve_reject(self, mock_post):
        resp = MagicMock()
        resp.json.return_value = {"status": "CANCELLED"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        c = ModelForgeClient("http://x")
        assert c.cancel_agent_run("r")["status"] == "CANCELLED"
        assert c.approve_agent_run("r")["status"] == "CANCELLED"
        assert c.reject_agent_run("r")["status"] == "CANCELLED"

    @patch("api_client.client.httpx.Client.get")
    def test_list_tools_and_metrics(self, mock_get):
        def side_effect(url, **kw):
            r = MagicMock()
            payload = {"tools": [{"name": "filesystem.read"}]} if "tools" in url else {"agent_runs_total": 1, "llm_calls_total": 2}
            r.json.return_value = payload
            r.raise_for_status = MagicMock()
            return r
        mock_get.side_effect = side_effect
        c = ModelForgeClient("http://x")
        assert c.list_agent_tools()[0]["name"] == "filesystem.read"
        assert c.agent_metrics()["agent_runs_total"] == 1

    def test_stream_agent_run_parses_sse(self):
        events = [
            {"event_type": "run.started", "sequence": 1, "payload": {}},
            {"event_type": "run.completed", "sequence": 2, "payload": {}},
        ]

        class FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def raise_for_status(self):
                pass
            def iter_lines(self):
                return iter(["data: " + json.dumps(e) for e in events])

        with patch("api_client.client.httpx.Client.stream") as mock_stream:
            ctx = MagicMock()
            ctx.__enter__.return_value = FakeResp()
            mock_stream.return_value = ctx
            c = ModelForgeClient("http://x")
            out = list(c.stream_agent_run("r"))
            assert [e["event_type"] for e in out] == ["run.started", "run.completed"]


class TestClientStructure:
    BASE = os.path.join(os.path.dirname(__file__), "..", "client", "pyside6")

    def test_agent_page_file_exists(self):
        path = os.path.join(self.BASE, "pages", "agent_page.py")
        assert os.path.exists(path)
        src = open(path, encoding="utf-8").read()
        assert "class AgentPage" in src
        assert "RunTimeline" in src

    def test_run_timeline_file_exists(self):
        path = os.path.join(self.BASE, "pages", "run_timeline.py")
        assert os.path.exists(path)
        src = open(path, encoding="utf-8").read()
        assert "class RunTimeline" in src
        assert "class ToolCallCard" in src
        assert "class EventStreamWorker" in src

    def test_no_fake_thinking(self):
        path = os.path.join(self.BASE, "pages", "run_timeline.py")
        src = open(path, encoding="utf-8").read()
        assert "Thinking..." not in src
        assert "Generating..." in src

    def test_main_has_agent_tab(self):
        path = os.path.join(self.BASE, "main.py")
        src = open(path, encoding="utf-8").read()
        assert "AgentPage" in src
        assert "addTab(self.agent_page" in src