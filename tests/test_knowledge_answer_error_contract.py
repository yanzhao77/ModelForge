"""The RAG answer route must report upstream inference failures stably.

``/chat`` already answered ``PROVIDER_UNAVAILABLE`` when the inference backend
was unreachable, but ``/knowledge/answer`` let the same failure escape as a bare
HTTP 500, so the desktop could only show ``HTTP_500`` and the cause was lost.
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import api.knowledge as knowledge_api  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from services.inference_errors import classify_inference_exception  # noqa: E402


class _FailingKB:
    def __init__(self, error: Exception):
        self._error = error

    async def answer(self, *_args, **_kwargs):
        raise self._error


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://provider.local/api/chat")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status} from provider", request=request, response=response)


def _answer(error: Exception) -> HTTPException:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(knowledge_api, "_get_kb", lambda: _FailingKB(error))
    try:
        request = knowledge_api.AnswerRequest(question="显存不足怎么办", model="local-gguf")
        user = SimpleNamespace(id=1, username="qa-user")
        with pytest.raises(HTTPException) as raised:
            asyncio.run(knowledge_api.knowledge_answer(request, db=None, user=user))
        return raised.value
    finally:
        monkeypatch.undo()


@pytest.mark.parametrize(
    "error,expected_status,expected_code",
    [
        (_http_status_error(502), 502, "PROVIDER_UNAVAILABLE"),
        (_http_status_error(429), 429, "RATE_LIMITED"),
        (httpx.ConnectError("no route"), 502, "ENDPOINT_UNREACHABLE"),
        (RuntimeError("boom"), 502, "INFERENCE_FAILED"),
    ],
)
def test_answer_maps_provider_failures_to_stable_codes(error, expected_status, expected_code):
    raised = _answer(error)

    assert raised.status_code == expected_status
    assert raised.detail["code"] == expected_code
    assert raised.detail["correlation_id"]


def test_chat_and_answer_share_one_classifier():
    from api.chat import _classify_chat_exception

    error = _http_status_error(503)

    assert _classify_chat_exception(error).code == classify_inference_exception(error).code
