"""Startup video discovery must not invalidate a successful desktop login."""
from __future__ import annotations

import os
import sys
import time

import httpx
import pytest

pytestmark = pytest.mark.desktop

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from api_client.client import ModelForgeClient
from components.api_worker import api_events
from pages.video_page import VideoPage
from PySide6.QtWidgets import QApplication


@pytest.fixture
def desktop_api(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/auth/login":
            return httpx.Response(200, json={"token": "desktop-token", "user": {"username": "qa-user"}})
        assert request.headers["Authorization"] == "Bearer desktop-token"
        if path.startswith("/v1/"):
            return httpx.Response(401, json={"error": {"code": "API_KEY_INVALID"}})
        if path == "/api/v1/videos/models":
            return httpx.Response(200, json={"data": [{
                "id": "fake-video",
                "modelforge": {
                    "capabilities": ["video_generation"],
                    "readiness": "ready",
                    "profiles": [{"seconds": 6, "fps": 8, "size": "720x480", "frames": 49, "default_steps": 3, "min_steps": 1, "max_steps": 50}],
                },
            }]})
        if path.endswith("/content"):
            return httpx.Response(200, content=b"video-content")
        return httpx.Response(200, json={"id": "video-test", "username": "qa-user"})

    client_class = httpx.Client
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr("api_client.client.httpx.Client", lambda **kwargs: client_class(transport=transport, **kwargs))
    api = ModelForgeClient("http://qa.local")
    api.login("qa-user", "test-password")
    return api, requests


def test_startup_video_discovery_keeps_first_login(desktop_api):
    app = QApplication.instance() or QApplication([])
    api, requests = desktop_api
    auth_events = []
    capture = auth_events.append
    api_events.authentication_required.connect(capture)
    page = VideoPage(api)
    try:
        deadline = time.monotonic() + 3
        while page._api_workers and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not page._api_workers
        assert page.model_combo.currentData()["id"] == "fake-video"
        assert page.generate_btn.isEnabled()
        assert api.has_token()
        assert api.me()["username"] == "qa-user"
        assert auth_events == []
        assert [r.url.path for r in requests] == [
            "/api/v1/auth/login", "/api/v1/videos/models", "/api/v1/auth/me",
        ]
    finally:
        api_events.authentication_required.disconnect(capture)
        page.shutdown_async_api()
        page.close()
        page.deleteLater()
        app.processEvents()


def test_video_operations_use_desktop_credentials(desktop_api):
    api, requests = desktop_api
    api.create_video(model="fake-video", prompt="Test clip", idempotency_key="request-test")
    api.get_video("video-test")
    api.cancel_video("video-test")
    assert api.download_video_content("video-test") == b"video-content"
    assert [r.url.path for r in requests[1:]] == [
        "/api/v1/videos", "/api/v1/videos/video-test",
        "/api/v1/videos/video-test/cancel", "/api/v1/videos/video-test/content",
    ]
    assert requests[1].headers["Idempotency-Key"] == "request-test"
    assert api.has_token()
