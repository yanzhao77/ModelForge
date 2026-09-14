import pytest

pytestmark = pytest.mark.desktop

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client" / "pyside6"
if str(CLIENT) not in sys.path:
    sys.path.insert(0, str(CLIENT))

from pages.chat_page import (
    _QTEXT_CURSOR_END,
    ChatPage,
    ComposerInput,
    _mime_local_file_paths,
    _qtext_cursor_end,
)
from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

_APP = None


def _ensure_qapp() -> QApplication:
    """Hold a session-long QApplication reference.

    Running this module after other GUI test files must not inherit a
    destroyed app instance (previously caused a fatal abort during widget
    construction when several desktop test files ran in one session).
    """
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class FakeApi:
    base_url = "http://127.0.0.1:8000"
    username = "test"

    def list_remote_providers(self):
        return []


def test_stream_cursor_uses_compatible_qtextcursor_end():
    _ensure_qapp()
    page = ChatPage(FakeApi())
    page.display.setPlainText("hello")
    page._on_delta(" world")
    assert page.display.toPlainText().endswith("hello world")
    assert (
        page.display.textCursor().position()
        == page.display.document().characterCount() - 1
    )
    expected_end = getattr(QTextCursor, "End", None)
    if expected_end is None:
        expected_end = QTextCursor.MoveOperation.End
    assert _QTEXT_CURSOR_END == expected_end


def test_qtextcursor_end_falls_back_to_move_operation():
    class QtCursorWithoutLegacyEnd:
        class MoveOperation:
            End = "move-operation-end"

    assert _qtext_cursor_end(QtCursorWithoutLegacyEnd) == "move-operation-end"


def test_composer_accepts_only_local_file_mime_paths(tmp_path):
    local_file = tmp_path / "notes.txt"
    local_file.write_text("hello", encoding="utf-8")
    missing_file = tmp_path / "missing.txt"
    mime = QMimeData()
    mime.setUrls([
        QUrl.fromLocalFile(str(local_file)),
        QUrl.fromLocalFile(str(missing_file)),
        QUrl("https://example.test/remote.txt"),
    ])

    assert _mime_local_file_paths(mime) == [str(local_file)]


def test_composer_insert_from_mime_emits_local_files(tmp_path):
    _ensure_qapp()
    local_file = tmp_path / "drop.txt"
    local_file.write_text("hello", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(local_file))])
    composer = ComposerInput()
    captured = []
    composer.files_added.connect(lambda paths: captured.extend(paths))

    composer.insertFromMimeData(mime)

    assert captured == [str(local_file)]


def test_chat_page_applies_structured_turn_events_once(monkeypatch):
    _ensure_qapp()
    page = ChatPage(FakeApi())
    page._active_turn_id = "turn_1"
    page._stream_active = True

    def fake_run_api(operation, on_success, on_failure, request_key=None):
        assert request_key == "chat-turn-snapshot"
        on_success({"turn": {"id": "turn_1", "status": "SUCCEEDED"}, "messages": []})
        return None

    monkeypatch.setattr(page, "_run_api", fake_run_api)

    page._structured_turn_events_done(
        {
            "events": [
                {
                    "turn_id": "turn_1",
                    "sequence": 1,
                    "type": "message.completed",
                    "payload": {"message_id": 7, "content": "answer"},
                },
                {
                    "turn_id": "turn_1",
                    "sequence": 2,
                    "type": "message.completed",
                    "payload": {"message_id": 7, "content": "answer"},
                },
                {
                    "turn_id": "turn_1",
                    "sequence": 3,
                    "type": "turn.finished",
                    "payload": {"status": "SUCCEEDED"},
                },
            ]
        }
    )

    assert page._structured_turn_last_sequence == 3
    assert page.messages == [{"role": "assistant", "content": "answer"}]
    assert page._active_turn_id is None
    assert page._stream_active is False


def test_chat_page_quotes_latest_artifact_version_as_attachment():
    _ensure_qapp()
    page = ChatPage(FakeApi())

    page._quote_latest_artifact_version(
        {"id": "art_1", "name": "report.txt"},
        [
            {"version": 1, "attachment_id": "att_old", "size_bytes": 5, "metadata": {"mime_type": "text/plain"}},
            {"version": 2, "attachment_id": "att_new", "size_bytes": 9, "metadata": {"mime_type": "text/markdown"}},
        ],
    )

    assert page.attachments == [
        {"id": "att_new", "display_name": "report.txt v2", "mime_type": "text/markdown", "size_bytes": 9}
    ]
    assert page.attachment_list.count() == 1
    assert page.attachment_list.item(0).data(Qt.UserRole) == "att_new"


def test_chat_page_turn_payload_uses_agent_mode_for_text_only_message():
    _ensure_qapp()
    page = ChatPage(FakeApi())
    page.mode_select.setCurrentIndex(1)

    payload = page._turn_payload("inspect this", "mock-model", provider_id=None)

    assert payload["mode"] == "agent"
    assert payload["message"]["parts"] == [{"type": "text", "text": "inspect this"}]


def test_chat_page_appends_context_estimate_summary():
    _ensure_qapp()
    page = ChatPage(FakeApi())

    page._append_context_estimate({"text_characters": 4, "estimated_prompt_characters": 13, "attachments": 1, "selected_parts": 1})

    text = page.display.toPlainText()
    assert "本轮上下文" in text
    assert "文本字符：4" in text
    assert "估算提交字符：13" in text
    assert "附件：1" in text
    assert "已选范围：1" in text


def test_chat_page_message_search_results_can_toggle_pin(monkeypatch):
    _ensure_qapp()
    page = ChatPage(FakeApi())
    page.session_id = 42
    calls = []

    def fake_run_api(operation, on_success, on_failure, request_key=None):
        calls.append(request_key)
        if request_key == "message-search":
            on_success([{"id": 7, "role": "user", "content": "needle", "is_pinned": False}])
        elif request_key == "message-pin-7":
            on_success({"id": 7, "role": "user", "content": "needle", "is_pinned": True})
        else:
            on_success([])

    monkeypatch.setattr(page, "_run_api", fake_run_api)

    page.message_search_input.setText("needle")
    page.search_messages()
    page.message_result_list.setCurrentRow(0)
    page.toggle_selected_message_pin()

    assert calls[:2] == ["message-search", "message-pin-7"]
    assert "已固定" in page.display.toPlainText()
