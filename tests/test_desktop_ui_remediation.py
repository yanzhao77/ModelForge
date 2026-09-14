from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.desktop

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from components.app_shell import NavigationRail
from i18n.manager import I18n
from pages.chat_page import ChatPage
from pages.developer_api_page import DeveloperApiPage
from pages.login_dialog import LoginDialog
from pages.models_page import ModelsPage
from pages.run_timeline import RunTimeline
from pages.settings_page import SettingsPage
from PySide6.QtWidgets import QApplication
from theme.metrics import SIDEBAR_COLLAPSED_WIDTH
from theme.theme import apply_theme


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeApi:
    base_url = "http://127.0.0.1:8000"
    username = "qa-user"

    def get_info(self):
        return {"name": "ModelForge", "version": "test"}

    def list_remote_providers(self):
        return []

    def list_organizations(self):
        return [{"id": "org-1", "name": "示例组织"}]

    def list_api_projects(self):
        return [{"id": "project-1", "name": "示例项目", "environment": "test"}]

    def list_agents(self):
        return [{"name": "support-agent"}]

    def list_project_agents(self, _project_id):
        return [{"agent_id": "support-agent"}]

    def list_project_keys(self, _project_id):
        return [{"id": "key-1", "name": "desktop", "prefix": "mf_test", "revoked_at": None}]

    def project_usage(self, _project_id):
        return {
            "ledger_version": "trial-v1",
            "daily_tokens": 12,
            "monthly_tokens": 12,
            "active_invocations": 0,
            "quota": {
                "max_concurrent_runs": 3,
                "daily_token_limit": 100000,
                "monthly_token_limit": 1000000,
                "per_run_token_limit": 8192,
            },
        }

    def local_api_status(self):
        return {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8000,
            "base_url": "http://127.0.0.1:8000/v1",
            "max_concurrent_requests": 4,
            "request_timeout_seconds": 120,
            "auto_load_models": True,
            "loaded_models": 1,
        }

    def list_local_api_keys(self):
        return {
            "keys": [
                {
                    "id": "local-key-1",
                    "name": "desktop",
                    "prefix": "mf-local123",
                    "scopes": ["models:read", "chat:write"],
                    "enabled": True,
                    "revoked_at": None,
                    "last_used_at": "2026-09-14T08:00:00",
                }
            ],
            "available_scopes": ["models:read", "chat:write"],
        }

    def list_local_api_models(self):
        return [
            {
                "id": "local-chat",
                "model_id": 1,
                "name": "local-chat",
                "display_name": "Local Chat",
                "format": "gguf",
                "api_capabilities": ["chat-completions", "responses"],
                "endpoints": ["/v1/chat/completions", "/v1/responses"],
                "loaded": True,
                "runtime_status": "loaded",
                "compatibility": {"state": "loaded", "reasons": []},
                "size_bytes": 1024,
            }
        ]

    def list_local_api_logs(self, _limit=100):
        return [
            {
                "request_id": "req-1",
                "endpoint": "/v1/chat/completions",
                "model": "local-chat",
                "status_code": 200,
                "duration_ms": 15,
                "error_code": None,
                "created_at": "2026-09-14T08:01:00",
            }
        ]


class FakeThemeManager:
    class Mode:
        value = "light"

    mode = Mode()

    def set_mode(self, _mode):
        pass


class TestUiSecurityAndAccessibility:
    def test_chat_renders_untrusted_content_as_plain_text(self, qt_app):
        page = ChatPage(FakeApi())
        page._append_msg("user", '<a href="file:///tmp/probe">probe</a>')
        assert '<a href="file:///tmp/probe">probe</a>' in page.display.toPlainText()
        rendered_html = page.display.document().toHtml()
        assert "&lt;a href=" in rendered_html
        assert '<a href=' not in rendered_html
        assert page.msg_input.accessibleName() == "消息内容"
        page.shutdown_stream()

    def test_chat_keeps_remote_provider_id_from_readiness_default(self, qt_app):
        page = ChatPage(FakeApi())
        page._render_readiness(
            {
                "level": "READY",
                "default_target": {
                    "kind": "remote",
                    "model_ref": "verified-chat",
                    "model_name": "verified-chat",
                    "provider_id": 7,
                    "provider_name": "Verified Provider",
                    "protocol": "responses",
                },
            }
        )

        assert page.model_input.text() == "verified-chat"
        assert page._provider_id() == 7
        assert page.send_btn.isEnabled()
        page.shutdown_stream()

    def test_models_page_selects_verified_remote_provider_before_chat(self, qt_app):
        class DefaultApi(FakeApi):
            def __init__(self):
                self.selected = None

            def list_models(self):
                return []

            def list_remote_providers(self):
                return []

            def set_default_model(self, kind, model_ref, provider_id=None):
                self.selected = (kind, model_ref, provider_id)
                return {
                    "level": "READY",
                    "default_target": {
                        "kind": kind,
                        "model_ref": model_ref,
                        "model_name": model_ref,
                        "provider_id": provider_id,
                    },
                }

        api = DefaultApi()
        page = ModelsPage(api)
        page._run_api = lambda operation, on_success, _on_failure, request_key=None: on_success(operation())
        navigated = []
        page.navigate_requested.connect(navigated.append)

        page._open_chat_with_provider(
            {"id": 7, "name": "Verified Provider", "default_model": "verified-chat"}
        )

        assert api.selected == ("remote", "verified-chat", 7)
        assert navigated == ["chat"]
        page.close()

    def test_timeline_renders_event_payload_as_plain_text(self, qt_app):
        timeline = RunTimeline(FakeApi())
        timeline._on_event(
            {
                "event_type": "agent.response",
                "timestamp": "2026-08-28T01:02:03",
                "payload": {"content": "<b>untrusted</b>"},
            }
        )
        assert "<b>untrusted</b>" in timeline.view.toPlainText()
        assert "<b>untrusted</b>" not in timeline.view.document().toHtml()
        assert timeline.approve_btn.accessibleName()
        timeline.shutdown_stream()

    def test_login_uses_labels_accessible_names_and_resizable_geometry(self, qt_app):
        dialog = LoginDialog(FakeApi())
        assert dialog.minimumWidth() >= 420
        assert dialog.maximumWidth() > dialog.minimumWidth()
        assert dialog.login_user.accessibleName()
        assert dialog.login_pwd.accessibleDescription()
        dialog.resize(dialog.minimumSize())
        dialog._show_page(1)
        dialog.show()
        qt_app.processEvents()
        register_page = dialog.stack.currentWidget()
        assert dialog.register_action.isVisible()
        assert dialog.register_action.geometry().bottom() <= register_page.contentsRect().bottom()
        dialog.close()

    def test_register_form_validates_user_inputs(self, qt_app):
        dialog = LoginDialog(FakeApi())
        dialog.reg_user.setText("ab")
        ok, message = dialog._validate_register_form()
        assert not ok
        assert "用户名长度" in message

        dialog.reg_user.setText("alice")
        dialog.reg_email.setText("bad-email")
        ok, message = dialog._validate_register_form()
        assert not ok
        assert "邮箱格式" in message

        dialog.reg_email.clear()
        dialog.reg_pwd.setText("short")
        ok, message = dialog._validate_register_form()
        assert not ok
        assert "密码至少" in message

        dialog.reg_pwd.setText("long-enough")
        dialog.reg_pwd2.setText("different")
        ok, message = dialog._validate_register_form()
        assert not ok
        assert "两次输入" in message

        dialog.reg_pwd2.setText("long-enough")
        ok, message = dialog._validate_register_form()
        assert ok
        assert "通过" in message
        dialog.close()

    def test_registration_fields_keep_roomy_even_spacing(self, qt_app):
        # Measure with the shipped stylesheet so field metrics match the app.
        previous_stylesheet = qt_app.styleSheet()
        apply_theme(qt_app)
        try:
            dialog = LoginDialog(FakeApi())
            dialog.show()
            qt_app.processEvents()
            dialog._show_page(1)
            qt_app.processEvents()

            fields = [dialog.reg_user, dialog.reg_email, dialog.reg_pwd, dialog.reg_pwd2]
            tops = [field.mapTo(dialog, field.rect().topLeft()).y() for field in fields]
            pitches = [later - earlier for earlier, later in zip(tops, tops[1:])]
            # Inputs must render at their natural height instead of being squeezed,
            # and the gap from an input to the next input must stay roomy and even.
            for field in fields:
                assert field.height() >= field.sizeHint().height()
            for field, pitch in zip(fields[1:], pitches):
                assert pitch - field.height() >= 32
            assert max(pitches) - min(pitches) <= 1
            dialog.close()
        finally:
            qt_app.setStyleSheet(previous_stylesheet)

    def test_navigation_collapses_without_losing_destination_names(self, qt_app):
        rail = NavigationRail(I18n())
        rail.set_collapsed(True)
        assert rail.width() == SIDEBAR_COLLAPSED_WIDTH
        assert rail._buttons["developer"].toolTip()
        assert rail._buttons["developer"].accessibleName()
        rail.set_collapsed(False)
        assert rail._buttons["developer"].text().strip()
        assert "API" in rail._buttons["developer"].text()

    def test_developer_api_workspace_renders_project_details(self, qt_app):
        page = DeveloperApiPage(FakeApi())
        page.local_page._render(
            {
                "status": page.api.local_api_status(),
                "keys": page.api.list_local_api_keys(),
                "models": page.api.list_local_api_models(),
                "logs": page.api.list_local_api_logs(80),
            }
        )
        page._render_catalog(
            {
                "organizations": page.api.list_organizations(),
                "projects": page.api.list_api_projects(),
                "agents": page.api.list_agents(),
            }
        )
        page._project_selected()
        page._render_project_details(
            "project-1",
            {
                "bindings": page.api.list_project_agents("project-1"),
                "keys": page.api.list_project_keys("project-1"),
                "usage": page.api.project_usage("project-1"),
            },
        )
        assert page.tabs.tabText(0) == "本地推理 API"
        assert page.local_page.base_url.text() == "http://127.0.0.1:8000/v1"
        assert page.local_page.key_table.rowCount() == 1
        assert page.local_page.model_table.rowCount() == 1
        assert "curl http://127.0.0.1:8000/v1/chat/completions" in page.local_page.examples.toPlainText()
        assert page.project_title.text() == "示例项目"
        assert page.key_list.count() == 1
        assert "今日已计令牌：12" in page.usage.toPlainText()
        page.close()

    def test_settings_page_configures_hf_mirror_download_source(self, qt_app):
        class SettingsApi(FakeApi):
            def __init__(self):
                self.saved = None

            def get_download_source(self):
                return {"source": "hf_mirror", "endpoint": "https://hf-mirror.com"}

            def update_download_source(self, source):
                self.saved = source
                return {"source": source, "endpoint": "https://hf-mirror.com"}

        def run_api(self, operation, on_success, _on_failure, request_key=None):
            on_success(operation())

        api = SettingsApi()
        with patch.object(SettingsPage, "_run_api", run_api), patch(
            "pages.settings_page.QMessageBox.information"
        ):
            page = SettingsPage(api, "test", lambda: None, FakeThemeManager(), I18n())
            assert page.download_source_select.currentData() == "hf_mirror"
            assert "https://hf-mirror.com" in page.download_source_status.text()
            page._save_download_source()

        assert api.saved == "hf_mirror"
        page.close()
