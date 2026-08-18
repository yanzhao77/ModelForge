"""Goal-oriented workspace and first-success onboarding page."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout, QWidget,
)


class WorkspacePage(QWidget):
    """Default landing page that turns system readiness into concrete next actions."""

    navigate_requested = Signal(str)

    def __init__(self, task_store, parent=None):
        super().__init__(parent)
        self.task_store = task_store
        self._init_ui()
        self.task_store.changed.connect(self.refresh)
        self.task_store.connection_changed.connect(self._connection_changed)
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("工作台")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        self.connection = QLabel("正在检查服务状态…")
        layout.addWidget(self.connection)

        onboarding = QGroupBox("首次使用：完成一次成功体验")
        onboarding_layout = QVBoxLayout(onboarding)
        self.onboarding_text = QLabel()
        self.onboarding_text.setWordWrap(True)
        onboarding_layout.addWidget(self.onboarding_text)
        self.progress = QProgressBar()
        self.progress.setRange(0, 4)
        onboarding_layout.addWidget(self.progress)
        onboarding_buttons = QHBoxLayout()
        self.primary = QPushButton("准备模型")
        self.primary.clicked.connect(self._primary_action)
        onboarding_buttons.addWidget(self.primary)
        example = QPushButton("使用示例 Agent")
        example.clicked.connect(lambda: self.navigate_requested.emit("agents"))
        onboarding_buttons.addWidget(example)
        onboarding_buttons.addStretch()
        onboarding_layout.addLayout(onboarding_buttons)
        layout.addWidget(onboarding)

        top = QHBoxLayout()
        self.model_card = self._card("模型与运行时", "正在检查可用模型…", "打开模型中心", "models")
        top.addWidget(self.model_card)
        self.task_card = self._card("正在进行的任务", "正在加载任务…", "打开任务中心", "tasks")
        top.addWidget(self.task_card)
        layout.addLayout(top)

        shortcuts = QGroupBox("快捷开始")
        shortcut_layout = QHBoxLayout(shortcuts)
        for label, destination in (("新建聊天", "chat"), ("创建 Agent", "agents"), ("导入知识文档", "knowledge"), ("创建训练实验", "training")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, target=destination: self.navigate_requested.emit(target))
            shortcut_layout.addWidget(button)
        layout.addWidget(shortcuts)
        layout.addStretch()

    def _card(self, title, text, action, destination):
        group = QGroupBox(title)
        group.setMinimumHeight(145)
        layout = QVBoxLayout(group)
        label = QLabel(text)
        label.setObjectName(f"{destination}_summary")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = QPushButton(action)
        button.clicked.connect(lambda: self.navigate_requested.emit(destination))
        layout.addWidget(button)
        return group

    def _label(self, card):
        return card.findChild(QLabel)

    def _connection_changed(self, connected, error):
        self.connection.setText("● 服务正常" if connected else f"● 服务不可达：{error}")
        self.connection.setStyleSheet("color: #2e7d32;" if connected else "color: #c62828;")

    def refresh(self):
        state = self.task_store.onboarding
        completed = int(bool(state.get("server_connected"))) + int(state.get("ready_model_count", 0) > 0) + int(bool(state.get("has_sent_message"))) + int(bool(state.get("has_completed_agent_run")))
        self.progress.setValue(completed)
        step = state.get("next_recommended_step", "select_model")
        labels = {
            "select_model": ("下一步：准备一个可用模型，然后即可开始对话。", "准备模型"),
            "send_message": ("下一步：发送第一条消息，验证模型与运行时。", "开始对话"),
            "run_agent": ("下一步：运行示例 Agent，体验可观察的自动化任务。", "运行示例 Agent"),
            "complete": ("已完成核心引导。你可以继续使用聊天、Agent、知识空间或训练。", "开始探索"),
        }
        sentence, action = labels.get(step, labels["select_model"])
        self.onboarding_text.setText(sentence)
        self.primary.setText(action)
        model_count = state.get("ready_model_count", 0)
        self._label(self.model_card).setText(f"{model_count} 个可用模型。" if model_count else "尚未检测到可用模型。可下载、扫描本地模型或配置兼容运行时。")
        active = self.task_store.summary.get("active", 0)
        attention = self.task_store.summary.get("needs_attention", 0)
        self._label(self.task_card).setText(f"{active} 项任务正在进行；{attention} 项需要处理。" if active or attention else "当前没有进行中的任务。")

    def _primary_action(self):
        step = self.task_store.onboarding.get("next_recommended_step")
        target = {"select_model": "models", "send_message": "chat", "run_agent": "agents", "complete": "chat"}.get(step, "models")
        self.navigate_requested.emit(target)
