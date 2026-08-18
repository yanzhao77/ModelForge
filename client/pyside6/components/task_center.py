"""Right-side global task center dock for long-running work."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)


STATUS_ICON = {
    "RUNNING": "◐", "QUEUED": "◌", "SCHEDULED": "◌", "WAITING_INPUT": "!",
    "CANCEL_REQUESTED": "◔", "FAILED": "✕", "PARTIAL": "!", "SUCCEEDED": "✓", "CANCELLED": "–",
}


class TaskCenterDock(QDockWidget):
    """Global task list and safe cancellation surface backed by TaskStore."""

    def __init__(self, store, parent=None):
        super().__init__("任务中心", parent)
        self.store = store
        self.setObjectName("TaskCenterDock")
        self.setMinimumWidth(340)
        self._init_ui()
        self.store.changed.connect(self.refresh)
        self.refresh()

    def _init_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        self.summary = QLabel("正在加载任务…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self.list, 1)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        layout.addWidget(self.detail)
        buttons = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.store.refresh)
        buttons.addWidget(refresh)
        self.cancel = QPushButton("取消任务")
        self.cancel.clicked.connect(self._cancel_selected)
        buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        self.setWidget(container)

    def refresh(self):
        active = self.store.summary.get("active", 0)
        attention = self.store.summary.get("needs_attention", 0)
        suffix = f" · {attention} 项需要处理" if attention else ""
        if self.store.last_error:
            self.summary.setText(f"任务同步失败：{self.store.last_error}")
        else:
            self.summary.setText(f"{active} 项正在进行{suffix}")
        selected = self._selected_task_id()
        self.list.clear()
        for task in self.store.ordered_tasks():
            percent = task.get("progress_percent")
            progress = f" · {percent}%" if percent is not None else ""
            item = QListWidgetItem(
                f"{STATUS_ICON.get(task.get('status'), '·')} {task.get('title', '未命名任务')}\n"
                f"{task.get('status', '')}{progress}"
            )
            item.setData(Qt.UserRole, task.get("task_id"))
            self.list.addItem(item)
            if task.get("task_id") == selected:
                self.list.setCurrentItem(item)
        self._show_selected()

    def _selected_task_id(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _show_selected(self):
        task_id = self._selected_task_id()
        task = self.store.tasks.get(task_id, {})
        self.cancel.setEnabled(bool(task.get("cancelable")) and task.get("status") not in {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIAL"})
        if not task:
            self.detail.clear()
            return
        lines = [
            f"状态：{task.get('status')}",
            f"来源：{task.get('source')}",
            f"摘要：{task.get('summary') or '-'}",
            f"创建：{task.get('created_at') or '-'}",
        ]
        if task.get("error_message"):
            lines.append(f"错误：{task['error_message']}")
        self.detail.setPlainText("\n".join(lines))

    def _cancel_selected(self):
        task_id = self._selected_task_id()
        task = self.store.tasks.get(task_id, {})
        if not task_id:
            return
        if QMessageBox.question(self, "确认取消", f"确定请求取消“{task.get('title', '该任务')}”？") == QMessageBox.Yes:
            self.store.cancel(task_id)
