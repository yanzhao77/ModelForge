"""Calm AI-native home workspace backed by real task state."""
from __future__ import annotations

from components.mf.primitives import MFEmptyState, MFPanel
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class WorkspacePage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, task_store, parent=None):
        super().__init__(parent)
        self.task_store = task_store
        self._init_ui()
        self.task_store.changed.connect(self.refresh)
        self.task_store.connection_changed.connect(self._connection_changed)
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 22, 0, 0)
        layout.setSpacing(18)
        greeting = QLabel("你想先完成什么工作？")
        greeting.setProperty("role", "pageTitle")
        layout.addWidget(greeting)
        detail = QLabel("使用 ModelForge 对话、管理本地与远程模型、运行智能体，并持续推进工作。")
        detail.setProperty("role", "muted")
        layout.addWidget(detail)

        composer = MFPanel()
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("向 ModelForge 提问…")
        self.prompt.setFixedHeight(96)
        composer.layout.addWidget(self.prompt)
        actions = QHBoxLayout()
        hint = QLabel("准备好后，请先在“对话”中选择模型。")
        hint.setProperty("role", "muted")
        actions.addWidget(hint)
        actions.addStretch(1)
        start = QPushButton("开始对话")
        start.setProperty("accent", True)
        start.clicked.connect(lambda: self.navigate_requested.emit("chat"))
        actions.addWidget(start)
        composer.layout.addLayout(actions)
        layout.addWidget(composer)

        title = QLabel("最近使用")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title)
        self.recent = QListWidget()
        self.recent.setMaximumHeight(240)
        self.recent.itemDoubleClicked.connect(lambda _item: self.navigate_requested.emit("tasks"))
        layout.addWidget(self.recent)
        self.empty = MFEmptyState("这里还没有内容", "开始对话、添加模型或创建智能体运行后，最近工作会显示在这里。")
        layout.addWidget(self.empty)
        self.connection = QLabel("正在连接 ModelForge 服务…")
        self.connection.setProperty("role", "muted")
        layout.addWidget(self.connection)
        layout.addStretch(1)

    def _connection_changed(self, connected: bool, error: str) -> None:
        self.connection.setText("已连接 ModelForge 服务" if connected else "无法连接服务，请确认 ModelForge 服务正在运行。")

    def refresh(self) -> None:
        tasks = self.task_store.ordered_tasks()
        self.recent.clear()
        self.recent.setVisible(bool(tasks))
        self.empty.setVisible(not bool(tasks))
        for task in tasks[:8]:
            title = task.get("title") or task.get("task_id") or "Untitled work"
            status = task.get("status") or "Pending"
            progress = task.get("progress_percent")
            suffix = f" · {progress}%" if isinstance(progress, (int, float)) else ""
            self.recent.addItem(QListWidgetItem(f"{title}\n{status}{suffix}"))
