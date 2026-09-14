"""Failure text must not leak raw worker/API codes into the UI.

The worker reports stable codes (``RUNTIME_ADMIN_REQUIRED``,
``INVALID_RESPONSE_SHAPE:models`` …). Pages that interpolated them directly
showed those codes to the user instead of the localised sentence that
``format_api_error`` produces; the extensions page additionally classified
permission failures by looking for ``"403"`` in a message that never contains
an HTTP status.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time

import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from api_client.client import ApiClientError, AuthenticationError  # noqa: E402
from components.api_worker import AsyncApiMixin, api_events  # noqa: E402
from components.app_shell import TopContext  # noqa: E402
from i18n.ui_localizer import format_api_error  # noqa: E402
from pages.extensions_page import ExtensionsPage  # noqa: E402
from pages.runtime_page import RuntimePage  # noqa: E402
from pages.settings_page import SettingsPage  # noqa: E402
from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_DESKTOP_MAIN_SPEC = importlib.util.spec_from_file_location(
    "modelforge_desktop_main",
    os.path.join(ROOT, "client", "pyside6", "main.py"),
)
assert _DESKTOP_MAIN_SPEC is not None and _DESKTOP_MAIN_SPEC.loader is not None
_DESKTOP_MAIN = importlib.util.module_from_spec(_DESKTOP_MAIN_SPEC)
sys.modules[_DESKTOP_MAIN_SPEC.name] = _DESKTOP_MAIN
_DESKTOP_MAIN_SPEC.loader.exec_module(_DESKTOP_MAIN)
MainWindow = _DESKTOP_MAIN.MainWindow


class _FailingApi:
    username = "qa-user"
    base_url = "http://qa.local"

    def __getattr__(self, _name):
        return lambda *args, **kwargs: {}


class _ThemeManager:
    class _Mode:
        value = "light"

    mode = _Mode()

    def set_mode(self, _mode):  # pragma: no cover - not used by these handlers
        pass


class _Translator:
    """Minimal stand-in: the settings page only reads ``locale``."""

    locale = "zh_CN"

    def set_locale(self, _locale):  # pragma: no cover - not exercised here
        pass

    def t(self, _key, fallback=""):
        return fallback


def _app():
    return QApplication.instance() or QApplication([])


def test_format_api_error_wraps_the_code_in_a_sentence():
    text = format_api_error("RUNTIME_ADMIN_REQUIRED (request_id: abc123)")

    assert "请求未完成" in text
    assert "RUNTIME_ADMIN_REQUIRED" in text
    assert text.strip() != "RUNTIME_ADMIN_REQUIRED"


def test_format_api_error_explains_authentication_failures():
    text = format_api_error("HTTP_401 (request_id: abc123)")

    assert "会话已失效" in text
    assert "HTTP_401" in text


def test_top_context_has_distinct_session_expired_state():
    _app()
    topbar = TopContext()

    topbar.set_authentication_required(_Translator())

    assert topbar.identity.text() == "需要登录"
    assert topbar.status.label.text() == "会话已失效"


def test_main_window_authentication_failure_leaves_task_page():
    _app()

    class Shell:
        def __init__(self):
            self.topbar = TopContext()
            self.status_text = ""

        def set_status(self, text, tooltip=None, progress=None):
            self.status_text = text

    class Window:
        def __init__(self):
            self.active_destination = "tasks"
            self._service_online = True
            self._service_identity = ""
            self._service_account = "qa-user"
            self._auth_dialog_open = True
            self.translator = _Translator()
            self.shell = Shell()
            self.destinations = []

        def _navigate_to(self, destination):
            self.destinations.append(destination)
            self.active_destination = destination

    window = Window()
    MainWindow._handle_authentication_required(window, "HTTP_401")

    assert window.destinations == ["overview"]
    assert window.shell.topbar.status.label.text() == "会话已失效"
    assert window.shell.status_text == "会话已失效，请重新登录。"


def test_main_window_service_authentication_error_uses_session_state():
    _app()

    class Shell:
        def __init__(self):
            self.topbar = TopContext()
            self.status_text = ""

        def set_status(self, text, tooltip=None, progress=None):
            self.status_text = text

    class Window:
        def __init__(self):
            self.active_destination = "tasks"
            self._service_online = True
            self._service_identity = ""
            self._service_account = "qa-user"
            self._auth_dialog_open = True
            self.translator = _Translator()
            self.shell = Shell()
            self.destinations = []

        def _navigate_to(self, destination):
            self.destinations.append(destination)
            self.active_destination = destination

    window = Window()
    MainWindow._show_service_error(window, "HTTP_401 (request_id: qa)")

    assert window.destinations == ["overview"]
    assert window.shell.topbar.identity.text() == "需要登录"
    assert window.shell.topbar.status.label.text() == "会话已失效"
    assert window.shell.status_text == "会话已失效，请重新登录。"


def test_async_api_authentication_error_uses_global_handler_without_page_failure():
    app = _app()

    class Probe(QObject, AsyncApiMixin):
        def __init__(self):
            QObject.__init__(self)
            self._init_async_api()

    probe = Probe()
    routed = []
    page_failures = []

    def capture(message):
        routed.append(message)

    api_events.authentication_required.connect(capture)
    try:
        probe._run_api(
            lambda: (_ for _ in ()).throw(AuthenticationError("HTTP_401", "qa")),
            lambda _result: None,
            page_failures.append,
        )
        deadline = time.monotonic() + 2
        while not routed and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    finally:
        api_events.authentication_required.disconnect(capture)
        probe.shutdown_async_api(100)

    assert routed == ["HTTP_401 (request_id: qa)"]
    assert page_failures == []


def test_async_api_drops_stale_authentication_response_without_relogin():
    app = _app()

    class Probe(QObject, AsyncApiMixin):
        def __init__(self):
            QObject.__init__(self)
            self._init_async_api()

    probe = Probe()
    routed = []
    page_failures = []

    def capture(message):
        routed.append(message)

    api_events.authentication_required.connect(capture)
    try:
        probe._run_api(
            lambda: (_ for _ in ()).throw(ApiClientError("STALE_AUTHENTICATION_RESPONSE", "qa")),
            lambda _result: None,
            page_failures.append,
        )
        deadline = time.monotonic() + 2
        while not probe._api_workers and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        while probe._api_workers and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    finally:
        api_events.authentication_required.disconnect(capture)
        probe.shutdown_async_api(100)

    assert routed == []
    assert page_failures == []


def test_runtime_page_shows_a_sentence_not_the_code():
    _app()
    page = RuntimePage(_FailingApi())

    page._refresh_failed("RUNTIME_ADMIN_REQUIRED")

    text = page.status.text()
    assert "请求未完成" in text
    assert "RUNTIME_ADMIN_REQUIRED" in text
    assert text.strip() != "RUNTIME_ADMIN_REQUIRED"


def test_settings_page_download_source_failure_is_localized():
    _app()
    page = SettingsPage(
        _FailingApi(), "0.1.3-beta.1", lambda: None, _ThemeManager(), _Translator()
    )

    page._download_source_failed("INVALID_RESPONSE_SHAPE:settings.download_source")

    text = page.download_source_status.text()
    assert text.strip() != "INVALID_RESPONSE_SHAPE:settings.download_source"
    assert "INVALID_RESPONSE_SHAPE:settings.download_source" in text


def test_extensions_page_classifies_admin_failures_by_code():
    _app()
    page = ExtensionsPage(_FailingApi())

    page._refresh_failed("RUNTIME_ADMIN_REQUIRED")
    assert page.detail.text() == "无法加载扩展：管理员权限不足。"

    page._refresh_failed("SERVICE_UNAVAILABLE")
    assert "请求未完成" in page.detail.text()
