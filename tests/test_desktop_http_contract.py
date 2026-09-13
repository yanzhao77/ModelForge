"""Transport-level contract for the desktop API client.

Two defects lived here: the client forced ``Content-Type: application/json`` on
every request, so multipart uploads arrived without a ``file`` part and the
service answered 422; and confirm-style DELETEs passed ``json=`` to
``httpx.Client.delete()``, which has no such parameter, so those operations
always raised ``TypeError``.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from api_client.client import ModelForgeClient  # noqa: E402


def _client() -> ModelForgeClient:
    client = ModelForgeClient("http://qa.local")
    client.set_token("qa-token")
    return client


def test_headers_do_not_force_a_json_content_type():
    headers = _client()._headers()

    # httpx derives the content type from `json=`/`files=`; pinning it here is
    # what broke every upload.
    assert "Content-Type" not in headers
    assert headers["Authorization"] == "Bearer qa-token"


@patch("api_client.client.httpx.Client.post")
def test_upload_sends_the_basename_not_the_whole_windows_path(mock_post, tmp_path):
    source = tmp_path / "probe.txt"
    source.write_text("显存不足时降低 batch size。", encoding="utf-8")
    response = mock_post.return_value
    response.json.return_value = {"status": "ingested"}
    response.raise_for_status.return_value = None

    _client().knowledge_upload(str(source))

    files = mock_post.call_args.kwargs["files"]
    assert files["file"][0] == "probe.txt"


@patch("api_client.client.httpx.Client.post")
def test_dataset_upload_sends_the_basename(mock_post, tmp_path):
    source = tmp_path / "probe.csv"
    source.write_text("instruction,input,output\n问候,你好,您好\n", encoding="utf-8")
    response = mock_post.return_value
    response.json.return_value = {"id": 1}
    response.raise_for_status.return_value = None

    _client().upload_dataset(str(source), "probe")

    files = mock_post.call_args.kwargs["files"]
    assert files["file"][0] == "probe.csv"
    assert mock_post.call_args.kwargs["data"] == {"name": "probe"}


@patch("api_client.client.httpx.Client.request")
def test_confirm_delete_sends_a_body_through_the_generic_request(mock_request):
    response = mock_request.return_value
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None

    result = _client().delete_knowledge_collection("collection-1", confirm=True)

    assert result == {"ok": True}
    method, url = mock_request.call_args.args[0], mock_request.call_args.args[1]
    assert method == "DELETE"
    assert url.endswith("/api/v1/workspaces/collections/collection-1")
    assert mock_request.call_args.kwargs["json"] == {"confirm": True, "request_id": None}


@patch("api_client.client.httpx.Client.delete", create=True)
def test_client_never_calls_the_json_less_delete_helper(mock_delete):
    """`Client.delete()` rejects `json=`; the client must not reach for it."""
    with patch("api_client.client.httpx.Client.request") as mock_request:
        response = mock_request.return_value
        response.json.return_value = {"ok": True}
        response.raise_for_status.return_value = None

        _client().delete_plugin_profile("profile-1", confirm=True)

    assert mock_delete.call_count == 0
    assert mock_request.call_args.args[0] == "DELETE"
