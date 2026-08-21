import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client" / "pyside6"
if str(CLIENT) not in sys.path:
    sys.path.insert(0, str(CLIENT))

from pages.chat_page import ChatPage
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication


class FakeApi:
    base_url = "http://127.0.0.1:8000"
    username = "test"

    def list_remote_providers(self):
        return []


def test_stream_cursor_uses_qtextcursor_end():
    QApplication.instance() or QApplication([])
    page = ChatPage(FakeApi())
    page.display.setPlainText("hello")
    page._on_delta(" world")
    assert page.display.toPlainText().endswith("hello world")
    assert (
        page.display.textCursor().position()
        == page.display.document().characterCount() - 1
    )
    assert QTextCursor.End.value >= 0
