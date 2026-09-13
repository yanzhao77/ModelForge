"""Payload-shape boundaries for the desktop API client.

Pages read service payloads from Qt slots: a wrongly shaped answer used to
raise inside the slot, which PySide6 only prints, so the page kept stale state
and nothing was reported. These tests pin the two defences added for that:

* the typed client refuses a container the method's contract does not promise
  (``INVALID_RESPONSE_SHAPE``) instead of handing it to a page;
* a handler that raises anyway is turned into a visible request failure
  (``CLIENT_RENDER_FAILED``) instead of a silent one.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from api_client.client import ApiClientError, ModelForgeClient  # noqa: E402


def _json_response(payload) -> httpx.Response:
    request = httpx.Request("GET", "http://qa.local/api/v1/models")
    return httpx.Response(200, json=payload, request=request)


def _body_response(content: bytes) -> httpx.Response:
    request = httpx.Request("GET", "http://qa.local/api/v1/models")
    return httpx.Response(
        200, content=content, headers={"content-type": "application/json"}, request=request
    )


@patch("api_client.client.httpx.Client.get")
def test_array_endpoint_accepts_a_json_array(mock_get):
    mock_get.return_value = _json_response([{"id": 1, "name": "local-gguf"}])

    models = ModelForgeClient("http://qa.local").list_models()

    assert models == [{"id": 1, "name": "local-gguf"}]


@patch("api_client.client.httpx.Client.get")
def test_array_endpoint_rejects_an_object_payload(mock_get):
    mock_get.return_value = _json_response({"sessions": []})

    with pytest.raises(ApiClientError) as error:
        ModelForgeClient("http://qa.local").list_sessions()

    assert error.value.code == "INVALID_RESPONSE_SHAPE:sessions"


@patch("api_client.client.httpx.Client.get")
def test_object_field_rejects_a_wrongly_typed_field(mock_get):
    mock_get.return_value = _json_response({"tasks": "oops"})

    with pytest.raises(ApiClientError) as error:
        ModelForgeClient("http://qa.local").list_tasks()

    assert error.value.code == "INVALID_RESPONSE_SHAPE:tasks"


@patch("api_client.client.httpx.Client.get")
def test_object_endpoint_keeps_working_for_valid_payloads(mock_get):
    mock_get.return_value = _json_response(
        {"level": "READY", "recommended_action": "open_chat", "targets": []}
    )

    snapshot = ModelForgeClient("http://qa.local").model_readiness()

    assert snapshot.get("level") == "READY"
    assert snapshot.get("targets") == []
    assert snapshot.get("default_target") is None


@patch("api_client.client.httpx.Client.get")
def test_invalid_json_body_is_reported_as_a_shape_error(mock_get):
    mock_get.return_value = _body_response(b"<html>gateway</html>")

    with pytest.raises(ApiClientError) as error:
        ModelForgeClient("http://qa.local").model_readiness()

    assert error.value.code == "INVALID_RESPONSE_BODY"


@patch("api_client.client.httpx.Client.get")
def test_scalar_json_is_rejected(mock_get):
    mock_get.return_value = _json_response("ok")

    with pytest.raises(ApiClientError) as error:
        ModelForgeClient("http://qa.local").model_readiness()

    assert error.value.code.startswith("INVALID_RESPONSE_SHAPE")


pytest.importorskip("PySide6")

from components.api_worker import AsyncApiMixin, wait_for_api_workers  # noqa: E402
from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app():
    # A QCoreApplication would break later GUI modules, so use a QApplication.
    return QApplication.instance() or QApplication([])


def _drain(predicate, timeout: float = 5.0) -> bool:
    app = _app()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


class _Host(QObject, AsyncApiMixin):
    """Minimal page-like owner of background workers."""

    def __init__(self):
        super().__init__()
        self._init_async_api()


def test_handler_exception_becomes_a_visible_request_failure():
    host = _Host()
    failures: list[str] = []

    def handler(payload):
        # The shape-mismatch signature: a list where a dict was assumed.
        return payload.get("level")

    host._run_api(lambda: [{"level": "READY"}], handler, failures.append, request_key="probe")

    assert _drain(lambda: bool(failures)), "the failure never reached the page"
    assert failures[0] == "CLIENT_RENDER_FAILED:AttributeError"


def test_failure_handler_that_raises_does_not_escape():
    host = _Host()
    calls: list[str] = []

    def bad_failure(_message: str) -> None:
        calls.append("called")
        raise RuntimeError("page already gone")

    host._run_api(
        lambda: [1, 2],
        lambda payload: payload.get("level"),
        bad_failure,
        request_key="probe",
    )

    assert _drain(lambda: calls == ["called"])
    assert host._api_state["suppressed"] is False


def test_suppressed_page_never_receives_a_late_answer():
    host = _Host()
    release = threading.Event()
    seen: list[object] = []

    host._run_api(
        lambda: (release.wait(10), {"ok": True})[1],
        seen.append,
        seen.append,
        request_key="late",
    )
    host.shutdown_async_api(wait_ms=50)
    release.set()
    assert wait_for_api_workers(5000) is True

    _app().processEvents()

    assert seen == []
