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

from pages.chat_page import _QTEXT_CURSOR_END, ChatPage, _qtext_cursor_end
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
