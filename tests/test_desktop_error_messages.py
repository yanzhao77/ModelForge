"""Failure text must not leak raw worker/API codes into the UI.

The worker reports stable codes (``RUNTIME_ADMIN_REQUIRED``,
``INVALID_RESPONSE_SHAPE:models`` …). Pages that interpolated them directly
showed those codes to the user instead of the localised sentence that
``format_api_error`` produces; the extensions page additionally classified
permission failures by looking for ``"403"`` in a message that never contains
an HTTP status.
"""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client", "pyside6"))

from i18n.ui_localizer import format_api_error  # noqa: E402
from pages.extensions_page import ExtensionsPage  # noqa: E402
from pages.runtime_page import RuntimePage  # noqa: E402
from pages.settings_page import SettingsPage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


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


def _app():
    return QApplication.instance() or QApplication([])


def test_format_api_error_wraps_the_code_in_a_sentence():
    text = format_api_error("RUNTIME_ADMIN_REQUIRED (request_id: abc123)")

    assert "请求未完成" in text
    assert "RUNTIME_ADMIN_REQUIRED" in text
    assert text.strip() != "RUNTIME_ADMIN_REQUIRED"


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
    assert "请求未完成" in text
    assert "INVALID_RESPONSE_SHAPE:settings.download_source" in text


def test_extensions_page_classifies_admin_failures_by_code():
    _app()
    page = ExtensionsPage(_FailingApi())

    page._refresh_failed("RUNTIME_ADMIN_REQUIRED")
    assert page.detail.text() == "无法加载扩展：管理员权限不足。"

    page._refresh_failed("SERVICE_UNAVAILABLE")
    assert "请求未完成" in page.detail.text()
