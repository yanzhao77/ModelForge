from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client", "pyside6"))

from components.app_shell import NavigationRail
from i18n.manager import I18n
from pages.chat_page import ChatPage
from pages.developer_api_page import DeveloperApiPage
from pages.login_dialog import LoginDialog
from pages.run_timeline import RunTimeline
from PySide6.QtWidgets import QApplication
from theme.metrics import SIDEBAR_COLLAPSED_WIDTH


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeApi:
    base_url = "http://127.0.0.1:8000"

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
        dialog.close()

    def test_navigation_collapses_without_losing_destination_names(self, qt_app):
        rail = NavigationRail(I18n())
        rail.set_collapsed(True)
        assert rail.width() == SIDEBAR_COLLAPSED_WIDTH
        assert rail._buttons["developer"].toolTip()
        assert rail._buttons["developer"].accessibleName()
        rail.set_collapsed(False)
        assert "开发者" in rail._buttons["developer"].text()

    def test_developer_api_workspace_renders_project_details(self, qt_app):
        page = DeveloperApiPage(FakeApi())
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
        assert page.project_title.text() == "示例项目"
        assert page.key_list.count() == 1
        assert "今日已计令牌：12" in page.usage.toPlainText()
        page.close()
