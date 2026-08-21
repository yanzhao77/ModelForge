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

    def __init__(self, task_store, readiness_store=None, parent=None):
        super().__init__(parent)
        self.task_store = task_store
        self.readiness_store = readiness_store
        self._init_ui()
        self.task_store.changed.connect(self.refresh)
        self.task_store.connection_changed.connect(self._connection_changed)
        if self.readiness_store:
            self.readiness_store.changed.connect(self._render_readiness)
            self.readiness_store.failed.connect(self._readiness_failed)
            self.readiness_store.refresh()
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

        self.readiness = MFPanel()
        readiness_row = QHBoxLayout()
        self.readiness_title = QLabel("正在检查模型就绪状态…")
        self.readiness_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.readiness_detail = QLabel("将自动识别本地模型与已验证的远程模型服务。")
        self.readiness_detail.setProperty("role", "muted")
        self.readiness_detail.setWordWrap(True)
        text_column = QVBoxLayout()
        text_column.addWidget(self.readiness_title)
        text_column.addWidget(self.readiness_detail)
        readiness_row.addLayout(text_column, 1)
        self.readiness_action = QPushButton("配置模型")
        self.readiness_action.setProperty("accent", True)
        self.readiness_action.clicked.connect(lambda: self.navigate_requested.emit("models"))
        readiness_row.addWidget(self.readiness_action)
        self.readiness.layout.addLayout(readiness_row)
        layout.addWidget(self.readiness)

        composer = MFPanel()
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("向 ModelForge 提问…")
        self.prompt.setFixedHeight(96)
        composer.layout.addWidget(self.prompt)
        actions = QHBoxLayout()
        self.hint = QLabel("准备好后，请先在“对话”中选择模型。")
        self.hint.setProperty("role", "muted")
        actions.addWidget(self.hint)
        actions.addStretch(1)
        self.start = QPushButton("开始对话")
        self.start.setProperty("accent", True)
        self.start.clicked.connect(self._start_chat)
        actions.addWidget(self.start)
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

    def _start_chat(self) -> None:
        snapshot = self.readiness_store.snapshot if self.readiness_store else None
        destination = "chat" if snapshot and snapshot.get("level") == "READY" else "models"
        self.navigate_requested.emit(destination)

    def _render_readiness(self, snapshot: dict) -> None:
        level = snapshot.get("level")
        targets = snapshot.get("targets") or []
        if level == "READY":
            default = snapshot.get("default_target") or {}
            model_name = default.get("model_name") or (targets[0].get("model_name") if targets else "")
            self.readiness_title.setText("模型已就绪")
            self.readiness_detail.setText(f"可使用 {len(targets)} 个模型目标。当前推荐：{model_name or '请选择默认模型'}。")
            self.readiness_action.setText("开始对话")
            self.start.setEnabled(True)
            self.hint.setText("模型已准备完成，可以开始新的对话。")
        elif level == "DEGRADED":
            self.readiness_title.setText("模型配置需要处理")
            self.readiness_detail.setText("已有模型或远程服务尚不可用，请完成密钥配置或连接验证。")
            self.readiness_action.setText("修复配置")
            self.start.setEnabled(False)
            self.hint.setText("请先修复模型配置后再开始对话。")
        elif level == "SERVICE_UNAVAILABLE":
            self.readiness_title.setText("暂时无法检查模型")
            self.readiness_detail.setText("请确认 ModelForge 服务已连接，然后重试。")
            self.readiness_action.setText("查看模型")
            self.start.setEnabled(False)
            self.hint.setText("模型服务不可用，暂时无法开始对话。")
        else:
            self.readiness_title.setText("尚未配置可用模型")
            self.readiness_detail.setText("添加本地模型或连接远程 OpenAI 兼容模型服务后，即可开始对话。")
            self.readiness_action.setText("配置模型")
            self.start.setEnabled(False)
            self.hint.setText("请先配置一个可用模型。")

    def _readiness_failed(self, _error: str) -> None:
        self._render_readiness({"level": "SERVICE_UNAVAILABLE", "targets": []})

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
