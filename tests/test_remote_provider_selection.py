"""Regression coverage for remote-service presets and chat model selection.

Two defects are pinned here: the remote-service dialog only offered 智谱 /
OpenAI / 自定义, so a DeepSeek or CC Switch endpoint had to be typed by hand;
and the chat page listed only verified providers and read that list once, so an
already configured service could not be selected.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time

import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(__file__))
CLIENT_ROOT = os.path.join(ROOT, "client", "pyside6")
sys.path.insert(0, CLIENT_ROOT)

from components.api_worker import wait_for_api_workers  # noqa: E402
from components.provider_dialog import RemoteProviderDialog  # noqa: E402
from i18n import I18n  # noqa: E402
from pages.chat_page import ChatPage  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "mf_provider_selection_main", os.path.join(CLIENT_ROOT, "main.py")
)
_desktop_main = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_desktop_main)

_APP = None

# A saved DeepSeek service that has not been verified yet: exactly the state a
# user is in right after saving a service in 模型管理.
DEEPSEEK_PROVIDER = {
    "id": 7,
    "name": "DeepSeek",
    "base_url": "https://api.deepseek.com",
    "protocol": "chat_completions",
    "default_model": "deepseek-flash",
    "enabled": True,
    "key_configured": True,
    "credential_state": "configured",
    "endpoint": "https://api.deepseek.com/chat/completions",
    "verification_status": "unknown",
}


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class FakeApi:
    base_url = "http://127.0.0.1:8000"
    username = "qa-user"

    def __init__(self, providers=None):
        self.providers = [dict(item) for item in (providers or [])]

    def list_remote_providers(self):
        return [dict(item) for item in self.providers]

    def list_models(self):
        return []

    def __getattr__(self, _name):
        return lambda *args, **kwargs: []


class FakeThemeManager:
    class Mode:
        value = "light"

    mode = Mode()

    def set_mode(self, _mode):
        pass


def test_presets_offer_deepseek_and_cc_switch_local_route():
    _app()
    dialog = RemoteProviderDialog(FakeApi())
    try:
        keys = [dialog.preset.itemData(index) for index in range(dialog.preset.count())]
        assert {"deepseek", "ccswitch"} <= set(keys)

        dialog.preset.setCurrentIndex(dialog.preset.findData("zhipu"))
        # 智谱's model ids are lower case; the preset used to prefill the
        # documentation display name, which no account can call.
        assert dialog.model.text() == "glm-4.7"

        dialog.preset.setCurrentIndex(dialog.preset.findData("deepseek"))
        assert dialog.name.text() == "DeepSeek"
        assert dialog.base_url.text() == "https://api.deepseek.com"
        assert dialog.protocol.currentData() == "chat_completions"
        assert dialog.model.text() == "deepseek-flash"

        dialog.preset.setCurrentIndex(dialog.preset.findData("ccswitch"))
        assert dialog.name.text() == "CC Switch"
        assert dialog.base_url.text() == "http://127.0.0.1:15721/v1"
        assert dialog.protocol.currentData() == "responses"
        # The local route injects the real credential, so the client only needs
        # the placeholder key that route expects.
        assert dialog.api_key.text() == "cc-switch"
        assert "路由" in dialog.state.text()
    finally:
        dialog.close()
        dialog.shutdown_async_api()


def test_verification_names_a_default_model_that_the_service_does_not_offer():
    """A verified service whose default model is a display name is still unusable."""
    _app()
    api = FakeApi([DEEPSEEK_PROVIDER])
    dialog = RemoteProviderDialog(api)
    try:
        dialog._render([dict(DEEPSEEK_PROVIDER)])
        assert dialog.current()["id"] == 7

        dialog._verified({"ok": True, "models": ["deepseek-v4-pro", "deepseek-chat"]})

        assert "不在服务返回的模型列表中" in dialog.state.text()
        assert "deepseek-v4-pro" in dialog.state.text()

        # The message must survive the list reload that follows a verification.
        dialog._render(api.list_remote_providers())
        assert "不在服务返回的模型列表中" in dialog.state.text()
    finally:
        dialog.close()
        dialog.shutdown_async_api()


def test_verification_reports_success_for_a_matching_default_model():
    _app()
    api = FakeApi([DEEPSEEK_PROVIDER])
    dialog = RemoteProviderDialog(api)
    try:
        dialog._render([dict(DEEPSEEK_PROVIDER)])

        dialog._verified({"ok": True, "models": ["deepseek-flash", "deepseek-v4-pro"]})

        assert dialog.state.text() == "连接验证成功，发现 2 个模型。"
    finally:
        dialog.close()
        dialog.shutdown_async_api()


def test_chat_lists_configured_service_before_verification():
    _app()
    api = FakeApi([DEEPSEEK_PROVIDER])
    page = ChatPage(api)
    try:
        page._render_remote_providers(api.list_remote_providers())
        labels = [
            page.provider_select.itemText(index)
            for index in range(page.provider_select.count())
        ]
        assert labels[0] == "本地运行时"
        assert any("DeepSeek" in label and "deepseek-flash" in label for label in labels)

        page.provider_select.setCurrentIndex(1)
        assert page._provider_id() == 7
        assert page._chat_ready() is True
        assert page.send_btn.isEnabled() is True
        assert page.model_input.text() == "deepseek-flash"
        assert "DeepSeek" in page.chat_status.label.text()
    finally:
        page.close()
        page.shutdown_async_api()


def test_chat_status_points_at_configured_services_instead_of_missing_model():
    _app()
    page = ChatPage(FakeApi([DEEPSEEK_PROVIDER]))
    try:
        page._render_readiness({"level": "SETUP_REQUIRED", "targets": []})
        page._render_remote_providers([DEEPSEEK_PROVIDER])
        assert page.chat_status.label.text() == "已配置 1 个远程模型，请在上方选择"
    finally:
        page.close()
        page.shutdown_async_api()


def test_select_provider_applies_after_the_service_list_arrives():
    _app()
    page = ChatPage(FakeApi([]))
    try:
        page._render_remote_providers([])
        assert page.provider_select.count() == 1

        page.select_provider(7)  # the service is not loaded yet
        page._render_remote_providers([DEEPSEEK_PROVIDER])

        assert page._provider_id() == 7
        assert page.model_input.text() == "deepseek-flash"
    finally:
        page.close()
        page.shutdown_async_api()


def test_chat_reloads_services_when_the_page_is_shown():
    app = _app()
    page = ChatPage(FakeApi([]))
    calls: list[bool] = []
    try:
        page.refresh_providers = lambda: calls.append(True)
        page.show()
        app.processEvents()
        assert calls, "showing the chat page must re-read the configured services"
    finally:
        page.close()
        page.shutdown_async_api()
        app.processEvents()


def test_model_page_chat_button_selects_that_service(tmp_path):
    app = _app()
    window = _desktop_main.MainWindow(
        FakeApi([DEEPSEEK_PROVIDER]),
        _desktop_main.RecoveryManager(data_dir=os.path.join(str(tmp_path), "state")),
        I18n(),
        FakeThemeManager(),
    )
    try:
        window._navigate_to("models")
        window.models_page._render_models(([], [dict(DEEPSEEK_PROVIDER)]))
        card = window.models_page.cards_layout.itemAt(0).widget()
        chat_button = next(
            button
            for button in card.findChildren(QPushButton)
            if button.text() == "开始对话"
        )
        chat_button.click()

        deadline = time.monotonic() + 5.0
        while window.chat_page._provider_id() != 7 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert window.active_destination == "chat"
        assert window.chat_page._provider_id() == 7
        assert window.chat_page.model_input.text() == "deepseek-flash"
    finally:
        window.close()
        assert wait_for_api_workers(5000) is True
        app.processEvents()
        window.deleteLater()
        app.processEvents()
