"""Explicit schedule management workspace; opening it never runs an Agent."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.mf.primitives import install_empty_state
from i18n.ui_localizer import current, format_api_error, localize_tree, text
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class AutomationPage(QWidget, AsyncApiMixin):
    """List persistent schedule drafts and require explicit enable/run actions."""

    navigate_requested = Signal(str)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._init_async_api()
        self.api = api
        self._jobs: list[dict] = []
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("自动化")
        title.setProperty("role", "pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        self.new_button = QPushButton("新建计划草稿")
        self.new_button.clicked.connect(self._create_draft)
        header.addWidget(self.new_button)
        layout.addLayout(header)
        self.hint = QLabel("计划默认是草稿。只有点击“启用”后才会在设定时间创建 Agent Run。")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._render_detail)
        layout.addWidget(self.list, 1)
        self._empty_toggle = install_empty_state(
            self.list, "暂无计划", "先创建草稿，再显式启用。启用后才会按计划创建 Agent Run。"
        )[0]
        self._empty_toggle(True)
        self.detail = QLabel("选择一个计划查看详情。")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        self.enable_button = QPushButton("启用")
        self.enable_button.clicked.connect(lambda: self._change_state(True))
        self.enable_button.setEnabled(False)
        actions.addWidget(self.enable_button)
        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(lambda: self._change_state(False))
        self.pause_button.setEnabled(False)
        actions.addWidget(self.pause_button)
        self.run_button = QPushButton("立即运行")
        self.run_button.clicked.connect(self._run_now)
        self.run_button.setEnabled(False)
        actions.addWidget(self.run_button)
        self.preview_button = QPushButton("查看下五次")
        self.preview_button.clicked.connect(self._preview)
        self.preview_button.setEnabled(False)
        actions.addWidget(self.preview_button)
        self.history_button = QPushButton("查看执行历史")
        self.history_button.clicked.connect(self._history)
        self.history_button.setEnabled(False)
        actions.addWidget(self.history_button)
        self.delete_button = QPushButton("删除计划")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setEnabled(False)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        localize_tree(self)
        self.refresh()

    def _sync_plan_actions(self) -> None:
        """Plan operations require a selected schedule."""
        has_selection = self._selected() is not None
        for button in (self.enable_button, self.pause_button, self.run_button,
                       self.preview_button, self.history_button, self.delete_button):
            button.setEnabled(has_selection)

    @staticmethod
    def _tr(source: str, **values) -> str:
        translator = current()
        locale = translator.locale if translator is not None else "zh_CN"
        return text(source, locale).format(**values)

    def _selected(self) -> dict | None:
        row = self.list.currentRow()
        return self._jobs[row] if 0 <= row < len(self._jobs) else None

    def refresh(self):
        self.refresh_button.setEnabled(False)
        worker = self._run_api(self.api.list_schedules, self._loaded, self._failed, request_key="automation-refresh")
        worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self._worker = worker

    def _loaded(self, jobs):
        self._jobs = jobs or []
        self.list.clear()
        for job in self._jobs:
            state = self._tr("已启用") if job.get("enabled") else self._tr("草稿/暂停")
            kind_key = {"once": "一次", "interval": "间隔", "daily": "每日", "weekly": "每周"}.get(job.get("schedule_kind"), "自定义")
            kind = self._tr(kind_key)
            self.list.addItem(QListWidgetItem(f"{job.get('name', '未命名')} · {state} · {kind}"))
        self._empty_toggle(not self._jobs)
        self._render_detail(self.list.currentRow())

    def _failed(self, error):
        self.detail.setText(self._tr("无法加载计划：{error}", error=format_api_error(error)))

    def _render_detail(self, _row):
        job = self._selected()
        self._sync_plan_actions()
        if not job:
            self.detail.setText(self._tr("暂无计划。先创建草稿，再显式启用。"))
            return
        spec = job.get("run_spec") or {}
        self.detail.setText(
            f"Agent：{spec.get('agent_id', '—')}\n"
            f"状态：{'已启用' if job.get('enabled') else '草稿/已暂停'}\n"
            f"下次执行：{job.get('next_run_at') or '启用后计算'}\n"
            f"时区：{job.get('timezone', 'UTC')}\n"
            f"错过触发：{job.get('misfire_policy', 'skip')}（不补跑）\n"
            f"并发策略：{job.get('concurrency_policy', 'skip')}\n"
            f"失败次数：{job.get('failure_count', 0)}/{job.get('max_failures', 3)}\n"
            f"待处理触发：{'是' if job.get('pending_trigger') else '否'}"
        )

    def _create_draft(self):
        agent_id, ok = QInputDialog.getText(self, "新建计划草稿", "Agent 名称")
        if not ok or not agent_id.strip():
            return
        interval, ok = QInputDialog.getInt(self, "计划频率", "间隔秒数（至少 60 秒）", 3600, 60, 604800)
        if not ok:
            return
        payload = {"name": f"{agent_id.strip()} 每 {interval} 秒", "agent_id": agent_id.strip(), "schedule_kind": "interval", "interval_seconds": interval, "input": ""}
        self._call(lambda: self.api.create_schedule(payload), "计划草稿已保存。尚未启用。")

    def _change_state(self, enabled: bool):
        job = self._selected()
        if not job:
            return
        action = self._tr("启用") if enabled else self._tr("暂停")
        if QMessageBox.question(self, self._tr("确认{action}", action=action), self._tr("确定{action}“{name}”吗？", action=action, name=job.get("name") or "-")) != QMessageBox.Yes:
            return
        callback = self.api.enable_schedule if enabled else self.api.pause_schedule
        self._call(lambda: callback(job["id"], confirm=True), self._tr("计划已{action}。", action=action))

    def _run_now(self):
        job = self._selected()
        if not job:
            return
        if QMessageBox.question(self, self._tr("确认立即运行"), self._tr("这会创建一个新的 Agent Run。是否继续？")) != QMessageBox.Yes:
            return
        self._call(lambda: self.api.run_schedule_now(job["id"], confirm=True), self._tr("已创建新的 Agent Run。"))

    def _preview(self):
        job = self._selected()
        if not job:
            return
        worker = self._run_api(lambda: self.api.schedule_preview(job["id"]), lambda data: QMessageBox.information(
            self,
            self._tr("计划预览"),
            self._tr("时区：{timezone}", timezone=str(data.get("timezone", "UTC"))) + "\n\n" + "\n".join(data.get("next_runs") or [self._tr("暂无后续执行。")]),
        ), lambda error: QMessageBox.warning(self, self._tr("计划预览"), format_api_error(error)), request_key="automation-preview")
        self._worker = worker

    def _history(self):
        job = self._selected()
        if not job:
            return
        worker = self._run_api(lambda: self.api.schedule_executions(job["id"]), lambda items: QMessageBox.information(
            self,
            self._tr("计划执行历史"),
            "\n\n".join(
                f"{item.get('created_at', '—')}\n状态：{item.get('status', '—')} · 触发：{item.get('trigger_kind', '—')}\nRun：{item.get('run_id') or '—'}"
                for item in items
            ) or self._tr("暂无执行历史。读取历史不会创建 Agent Run。"),
        ), lambda error: QMessageBox.warning(self, self._tr("计划执行历史"), format_api_error(error)), request_key="automation-history")
        self._worker = worker

    def _delete(self):
        job = self._selected()
        if not job:
            return
        if QMessageBox.question(self, self._tr("确认删除"), self._tr("删除计划不会删除历史执行记录。是否继续？")) != QMessageBox.Yes:
            return
        self._call(lambda: self.api.delete_schedule(job["id"], confirm=True), self._tr("计划已删除。"))

    def _call(self, action, success):
        worker = self._run_api(
            action,
            lambda _result: (QMessageBox.information(self, self._tr("自动化"), success), self.refresh()),
            lambda error: QMessageBox.warning(self, self._tr("自动化"), format_api_error(error)),
            request_key="automation-mutation",
        )
        self._worker = worker

    def closeEvent(self, event):
        self.shutdown_async_api()
        super().closeEvent(event)
