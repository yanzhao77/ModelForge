"""Activity stream derived solely from real TaskStore state."""
from __future__ import annotations

from components.mf.primitives import MFEmptyState, MFSection
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget


class ActivityPage(QWidget):
    def __init__(self, task_store, parent=None):
        super().__init__(parent)
        self.task_store = task_store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(MFSection("运行记录", "活动"))
        self.events = QListWidget()
        self.events.setAlternatingRowColors(True)
        layout.addWidget(self.events, 1)
        self.empty = MFEmptyState("暂无活动记录", "已连接的 ModelForge 服务发布任务事件后，将显示在这里。")
        layout.addWidget(self.empty, 1)
        self.task_store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        tasks = self.task_store.ordered_tasks()
        self.events.clear()
        self.empty.setVisible(not bool(tasks))
        self.events.setVisible(bool(tasks))
        for task in tasks[:100]:
            timestamp = task.get("updated_at") or task.get("created_at") or "Unavailable"
            title = task.get("title") or task.get("task_id") or "Unnamed task"
            status = task.get("status") or "UNKNOWN"
            source = task.get("source") or "service"
            item = QListWidgetItem(f"{timestamp}\n{status}  ·  {title}\nSOURCE  {source}")
            self.events.addItem(item)
