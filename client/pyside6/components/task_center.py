"""Global native task center with filters, recoverable SSE state and audit export."""
from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from i18n.ui_localizer import format_api_error, format_text
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

STATUS_ICON = {
    "RUNNING": "◐", "QUEUED": "◌", "SCHEDULED": "◌", "WAITING_INPUT": "!",
    "CANCEL_REQUESTED": "◔", "FAILED": "✕", "PARTIAL": "!", "SUCCEEDED": "✓", "CANCELLED": "–",
}
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "PARTIAL"}


class TaskCenterDock(QDockWidget, AsyncApiMixin):
    """Task control surface for retries, logs, audit export and live-state visibility."""

    def __init__(self, store, parent=None):
        QDockWidget.__init__(self, "任务中心", parent)
        self._init_async_api()
        self.store = store
        self._logs_by_task = {}
        self._loading_logs = False
        self.setObjectName("TaskCenterDock")
        self.setMinimumWidth(380)
        self._init_ui()
        self.store.changed.connect(self.refresh)
        self.store.connection_changed.connect(self._snapshot_state_changed)
        self.store.stream_changed.connect(self._stream_state_changed)
        self.store.batch_retried.connect(self._batch_retry_completed)
        self.refresh()

    def _init_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        self.connection = QLabel("● 正在建立任务连接…")
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        self.summary = QLabel("正在加载任务…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        filters = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("全部状态", "")
        for status in ("RUNNING", "QUEUED", "WAITING_INPUT", "FAILED", "PARTIAL", "SUCCEEDED", "CANCELLED"):
            self.status_filter.addItem(status, status)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.status_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选任务标题或来源…")
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._show_selected)
        self.list.itemChanged.connect(lambda _: self._update_batch_action())
        splitter.addWidget(self.list)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(155)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat("执行进度：%p%")
        layout.addWidget(self.progress)
        splitter.addWidget(self.detail)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setLineWrapMode(QTextEdit.NoWrap)
        self.logs.setPlaceholderText("选择任务后点击“查看日志”加载执行日志与事件轨迹。")
        splitter.addWidget(self.logs)
        splitter.setSizes([250, 140, 190])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.store.refresh)
        actions.addWidget(self.refresh_btn)
        examples_btn = QPushButton("示例")
        examples_btn.clicked.connect(lambda: open_examples("tasks", self))
        actions.addWidget(examples_btn)
        self.retry_btn = QPushButton("重试")
        self.retry_btn.clicked.connect(self._retry_selected)
        actions.addWidget(self.retry_btn)
        self.batch_retry_btn = QPushButton("批量重试")
        self.batch_retry_btn.clicked.connect(self._retry_checked)
        self.batch_retry_btn.setEnabled(False)
        actions.addWidget(self.batch_retry_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel_selected)
        actions.addWidget(self.cancel_btn)
        self.logs_btn = QPushButton("查看日志")
        self.logs_btn.clicked.connect(self._load_selected_logs)
        actions.addWidget(self.logs_btn)
        layout.addLayout(actions)

        export_actions = QHBoxLayout()
        self.export_json_btn = QPushButton("导出 JSON")
        self.export_json_btn.clicked.connect(lambda: self._export_selected("json"))
        export_actions.addWidget(self.export_json_btn)
        self.export_text_btn = QPushButton("导出文本")
        self.export_text_btn.clicked.connect(lambda: self._export_selected("text"))
        export_actions.addWidget(self.export_text_btn)
        export_actions.addStretch()
        layout.addLayout(export_actions)
        self.setWidget(container)

    def _snapshot_state_changed(self, connected, error):
        if connected:
            self.connection.setText("● 任务快照已同步")
            self.connection.setStyleSheet("color: #2e7d32;")
        else:
            self.connection.setText(f"● {format_text('任务快照不可达。{error}', error=format_api_error(error))}")
            self.connection.setStyleSheet("color: #c62828;")

    def _stream_state_changed(self, online, error):
        if online:
            self.connection.setText("● 实时任务流已连接")
            self.connection.setStyleSheet("color: #1565c0;")
        else:
            self.connection.setText(f"◌ {format_text('实时任务流已断开，正在重连。{error}', error=format_api_error(error))}")
            self.connection.setStyleSheet("color: #ef6c00;")

    def refresh(self):
        active = self.store.summary.get("active", 0)
        attention = self.store.summary.get("needs_attention", 0)
        suffix = f" · {attention} 项需要处理" if attention else ""
        self.summary.setText(f"{active} 项正在进行{suffix}" if not self.store.last_error else format_text("任务同步未完成。{error}", error=format_api_error(self.store.last_error)))
        selected = self._selected_task_id()
        checked = self._checked_retry_task_ids()
        status = self.status_filter.currentData()
        query = self.search.text().strip().lower()
        self.list.clear()
        for task in self.store.ordered_tasks():
            if status and task.get("status") != status:
                continue
            haystack = " ".join(str(task.get(key, "")) for key in ("title", "source", "task_type")).lower()
            if query and query not in haystack:
                continue
            progress = f" · {task.get('progress_percent')}%" if task.get("progress_percent") is not None else ""
            item = QListWidgetItem(f"{STATUS_ICON.get(task.get('status'), '·')} {task.get('title', '未命名任务')}\n{task.get('status', '')}{progress} · {task.get('source', '-')}")
            item.setData(Qt.UserRole, task.get("task_id"))
            if self._can_retry(task):
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if task.get("task_id") in checked else Qt.Unchecked)
            self.list.addItem(item)
            if task.get("task_id") == selected:
                self.list.setCurrentItem(item)
        self._show_selected()
        self._update_batch_action()

    def _selected_task_id(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selected_task(self):
        return self.store.tasks.get(self._selected_task_id(), {})

    @staticmethod
    def _can_retry(task):
        attempt = int(task.get("attempt") or 1)
        max_attempts = int(task.get("max_attempts") or 0)
        remaining = max(0, max_attempts - attempt) if max_attempts else None
        return bool(task.get("retryable")) and task.get("status") in {"FAILED", "PARTIAL", "CANCELLED"} and (remaining is None or remaining > 0)

    def _checked_retry_task_ids(self):
        return [
            self.list.item(index).data(Qt.UserRole)
            for index in range(self.list.count())
            if self.list.item(index).checkState() == Qt.Checked
        ]

    def _update_batch_action(self):
        count = len(self._checked_retry_task_ids())
        self.batch_retry_btn.setText(f"批量重试（{count}）")
        self.batch_retry_btn.setEnabled(count > 0)

    def _show_selected(self):
        task = self._selected_task()
        has_task = bool(task)
        attempt = int(task.get("attempt") or 1)
        max_attempts = int(task.get("max_attempts") or 0)
        retries_left = max(0, max_attempts - attempt) if max_attempts else None
        retryable = bool(task.get("retryable")) and task.get("status") in {"FAILED", "PARTIAL", "CANCELLED"} and (retries_left is None or retries_left > 0)
        cancellable = bool(task.get("cancelable")) and task.get("status") not in TERMINAL
        self.retry_btn.setEnabled(retryable)
        self.cancel_btn.setEnabled(cancellable)
        self.logs_btn.setEnabled(has_task and not self._loading_logs)
        self.export_json_btn.setEnabled(has_task)
        self.export_text_btn.setEnabled(has_task)
        if not has_task:
            self.progress.setValue(0)
            self.detail.clear()
            self.logs.clear()
            return
        progress = int(task.get("progress_percent") or 0)
        self.progress.setValue(max(0, min(100, progress)))
        self.progress.setFormat(f"Progress: {progress}% · {task.get('status', '-')}")
        fields = [
            ("Status", task.get("status")), ("Source", task.get("source")), ("Task type", task.get("task_type")),
            ("Summary", task.get("summary") or "-"), ("Created", task.get("created_at") or "-"),
            ("Updated", task.get("updated_at") or "-"), ("Progress", task.get("progress_percent")),
        ]
        if max_attempts:
            fields.append(("重试额度", f"第 {attempt} / {max_attempts} 次；剩余 {retries_left} 次"))
        if task.get("error_code"):
            fields.append(("Failure category", task["error_code"]))
        lines = [f"{label}: {value}" for label, value in fields if value is not None]
        if task.get("status") in {"FAILED", "PARTIAL", "CANCELLED"}:
            lines.append(format_text("任务未成功完成（{code}）。请查看脱敏日志或在确认后重试。", code=task.get("error_code") or "TASK_NOT_COMPLETED"))
        self.detail.setPlainText("\n".join(lines))
        cached = self._logs_by_task.get(task.get("task_id"))
        if cached:
            self._render_logs(cached)
        else:
            self.logs.setPlainText("尚未加载日志。点击“查看日志”获取执行日志和任务事件。")

    def _retry_selected(self):
        task = self._selected_task()
        task_id = task.get("task_id")
        if not task_id:
            return
        if QMessageBox.question(self, format_text("确认重试"), format_text("确定重试“{title}”？", title=task.get("title", "该任务"))) == QMessageBox.Yes:
            self.store.retry(task_id, confirm=True)

    def _retry_checked(self):
        task_ids = self._checked_retry_task_ids()
        if not task_ids:
            return
        message = format_text("将为所选的 {count} 个失败任务创建受审计的重试任务，是否继续？", count=len(task_ids))
        if QMessageBox.question(self, format_text("确认批量重试"), message) == QMessageBox.Yes:
            self.batch_retry_btn.setEnabled(False)
            self.store.retry_many(task_ids, confirm=True)

    def _batch_retry_completed(self, result):
        succeeded = len(result.get("tasks", []))
        failures = result.get("failures", [])
        details = "\n".join(f"- {format_text('任务 {task_id} 未创建（{code}）。', task_id=item.get('task_id', '-'), code=item.get('code', 'OPERATION_REJECTED'))}" for item in failures)
        message = format_text("已创建 {count} 个重试任务。", count=succeeded)
        if details:
            message += f"\n\n{format_text('未创建：')}\n{details}"
        QMessageBox.information(self, format_text("批量重试结果"), message)

    def _cancel_selected(self):
        task = self._selected_task()
        task_id = task.get("task_id")
        if not task_id:
            return
        if QMessageBox.question(self, format_text("确认取消"), format_text("确定请求取消“{title}”？", title=task.get("title", "该任务"))) == QMessageBox.Yes:
            self.store.cancel(task_id, confirm=True)

    def _load_selected_logs(self):
        task_id = self._selected_task_id()
        if not task_id or self._loading_logs:
            return
        self._loading_logs = True
        self.logs_btn.setEnabled(False)
        self.logs.setPlainText("正在加载执行日志与事件轨迹…")
        self._run_api(
            lambda: (self.store.api.task_events(task_id), self.store.api.task_logs(task_id)),
            lambda result: self._logs_loaded(task_id, result),
            self._logs_failed,
        )

    def _logs_loaded(self, task_id, result):
        self.logs_btn.setEnabled(True)
        self._loading_logs = False
        events, logs = result
        payload = {"events": events, "logs": logs}
        self._logs_by_task[task_id] = payload
        self._show_selected()

    def _logs_failed(self, error):
        self.logs_btn.setEnabled(True)
        self._loading_logs = False
        self.logs.setPlainText(f"{format_text('日志加载失败')}：{format_api_error(error)}")
        self._show_selected()

    def _render_logs(self, payload):
        logs = payload.get("logs") or {}
        lines = [f"执行日志 · 来源：{logs.get('source', '-')}", ""]
        lines.extend(str(line) for line in logs.get("lines", []))
        events = payload.get("events") or []
        if events:
            lines.extend(["", "事件轨迹"])
            for event in events:
                detail = json.dumps(event.get("payload", {}), ensure_ascii=False, indent=None)
                lines.append(f"[{event.get('created_at', '-')}] {event.get('event_type', '-')} · {detail}")
        self.logs.setPlainText("\n".join(lines) if lines else "暂无日志。")

    def _export_selected(self, fmt):
        task = self._selected_task()
        task_id = task.get("task_id")
        if not task_id:
            return
        payload = {"exported_from": "ModelForge Desktop", "task": task, **self._logs_by_task.get(task_id, {"events": [], "logs": {"lines": []}})}
        if fmt == "json":
            path, _ = QFileDialog.getSaveFileName(self, "导出任务审计 JSON", f"{task_id}.json", "JSON 文件 (*.json)")
            if not path:
                return
            content = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            path, _ = QFileDialog.getSaveFileName(self, "导出任务日志文本", f"{task_id}.txt", "文本文件 (*.txt)")
            if not path:
                return
            lines = [f"Task: {task.get('title', task_id)}", f"Task ID: {task_id}", f"Status: {task.get('status', '-')}", "", "Execution logs:"]
            lines.extend(str(line) for line in (payload.get("logs") or {}).get("lines", []))
            lines.extend(["", "Events:"])
            lines.extend(json.dumps(event, ensure_ascii=False) for event in payload.get("events", []))
            content = "\n".join(lines)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError:
            QMessageBox.warning(self, format_text("导出失败"), format_text("无法写入所选文件。请检查文件路径和权限后重试。"))
            return
        QMessageBox.information(self, "导出完成", f"已保存到：{path}")
