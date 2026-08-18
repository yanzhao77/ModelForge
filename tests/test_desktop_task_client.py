"""Desktop task-center client contract checks for retry and audit data."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from api_client.client import ModelForgeClient


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


@patch("api_client.client.httpx.Client.post")
def test_retry_task_posts_to_task_retry_endpoint(mock_post):
    mock_post.return_value = _response({"task_id": "task-1", "status": "QUEUED"})
    client = ModelForgeClient("http://qa.local")

    result = client.retry_task("task-1")

    assert result["status"] == "QUEUED"
    url = mock_post.call_args.args[0]
    assert url.endswith("/api/v1/tasks/task-1/retry")


@patch("api_client.client.httpx.Client.get")
def test_task_events_and_logs_use_bounded_query_params(mock_get):
    mock_get.side_effect = [_response({"events": [{"event_id": 2}]}), _response({"source": "training", "lines": ["epoch=1"]})]
    client = ModelForgeClient("http://qa.local")

    events = client.task_events("task-2", limit=120)
    logs = client.task_logs("task-2", limit=120)

    assert events == [{"event_id": 2}]
    assert logs["lines"] == ["epoch=1"]
    assert mock_get.call_args_list[0].kwargs["params"] == {"limit": 120}
    assert mock_get.call_args_list[1].kwargs["params"] == {"limit": 120}


def test_task_center_contains_retry_log_and_export_controls():
    source = open(os.path.join(ROOT, "client", "pyside6", "components", "task_center.py"), encoding="utf-8").read()
    assert "task_events" in source
    assert "task_logs" in source
    assert "导出 JSON" in source
    assert "导出文本" in source
    assert "实时任务流已连接" in source
