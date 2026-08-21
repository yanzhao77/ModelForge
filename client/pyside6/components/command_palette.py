"""Small command palette for fast keyboard-first ModelForge navigation."""

from __future__ import annotations

from i18n.ui_localizer import localize_tree
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class CommandPalette(QDialog):
    def __init__(self, commands: list[tuple[str, str, callable]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setModal(True)
        self.resize(480, 360)
        self.commands = commands
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索命令…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._run)
        layout.addWidget(self.list)
        localize_tree(self)
        self._filter("")
        self.search.setFocus(Qt.OtherFocusReason)

    def _filter(self, query: str) -> None:
        self.list.clear()
        query = query.lower().strip()
        for title, hint, callback in self.commands:
            if query and query not in f"{title} {hint}".lower():
                continue
            item = QListWidgetItem(f"{title}\n{hint}")
            item.setData(Qt.UserRole, callback)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self, item: QListWidgetItem) -> None:
        callback = item.data(Qt.UserRole)
        self.accept()
        callback()
