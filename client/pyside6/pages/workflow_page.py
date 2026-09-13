"""Workflow list / definition / run workspace (V1.5)."""
from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

EXAMPLE_DEFINITION = {
    "entry": "start",
    "nodes": [
        {"id": "start", "type": "input", "next": "ask"},
        {"id": "ask", "type": "llm", "config": {"prompt": "{{input.question}}"}, "next": "done"},
        {"id": "done", "type": "output", "config": {"value": "{{nodes.ask.output}}"}},
    ],
}


class WorkflowPage(QWidget, AsyncApiMixin):
    """Create, inspect and run workflows without blocking the UI thread."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._workflows: list[dict] = []
        self._runs: list[dict] = []
        self._current_run_id: str | None = None
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)
        self.refresh()

    # -- ui -----------------------------------------------------------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("工作流", "编排"))
        header.addStretch(1)
        self.status = MFStatusBadge("正在加载工作流", "warning")
        header.addWidget(self.status)
        layout.addLayout(header)
        hint = QLabel("节点类型：input / llm / agent / tool / condition / loop / parallel / approval / output。")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.workflow_list = QListWidget()
        self.workflow_list.currentRowChanged.connect(self._on_workflow_selected)
        left_layout.addWidget(self.workflow_list, 1)
        buttons = QHBoxLayout()
        create = QPushButton("新建工作流")
        create.clicked.connect(self.create_workflow)
        buttons.addWidget(create)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        delete = QPushButton("删除")
        delete.clicked.connect(self.delete_workflow)
        buttons.addWidget(delete)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.addWidget(QLabel("定义（JSON）"))
        self.definition = QTextEdit()
        self.definition.setPlaceholderText(json.dumps(EXAMPLE_DEFINITION, ensure_ascii=False, indent=2))
        middle_layout.addWidget(self.definition, 1)
        run_row = QHBoxLayout()
        self.run_input = QTextEdit()
        self.run_input.setPlaceholderText('运行输入，例如 {"question": "你好"}')
        self.run_input.setMaximumHeight(64)
        run_row.addWidget(self.run_input, 1)
        run = QPushButton("运行")
        run.clicked.connect(self.run_workflow)
        run_row.addWidget(run)
        middle_layout.addLayout(run_row)
        splitter.addWidget(middle)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("运行记录"))
        self.run_table = QTableWidget()
        self.run_table.setColumnCount(3)
        self.run_table.setHorizontalHeaderLabels(["运行", "状态", "当前节点"])
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.run_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.run_table.itemSelectionChanged.connect(self._on_run_selected)
        right_layout.addWidget(self.run_table, 1)
        actions = QHBoxLayout()
        self.trace_btn = QPushButton("查看 Trace")
        self.trace_btn.clicked.connect(self.show_trace)
        actions.addWidget(self.trace_btn)
        approve = QPushButton("批准")
        approve.clicked.connect(self.approve_run)
        actions.addWidget(approve)
        cancel = QPushButton("取消运行")
        cancel.clicked.connect(self.cancel_run)
        actions.addWidget(cancel)
        right_layout.addLayout(actions)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail, 1)
        splitter.addWidget(right)
        splitter.setSizes([260, 460, 420])
        layout.addWidget(splitter, 1)

    # -- data ---------------------------------------------------------------

    def refresh(self) -> None:
        self._run_api(self.api.list_workflows, self._render_workflows, self._failed, request_key="workflows")

    def _render_workflows(self, result) -> None:
        workflows = (result or {}).get("workflows", []) if isinstance(result, dict) else (result or [])
        self._workflows = workflows
        current = self._selected_workflow_id()
        self.workflow_list.blockSignals(True)
        self.workflow_list.clear()
        for workflow in workflows:
            item = QListWidgetItem(workflow.get("name", "-"))
            item.setData(1000, workflow.get("workflow_id"))
            self.workflow_list.addItem(item)
        self.workflow_list.blockSignals(False)
        if current:
            for index in range(self.workflow_list.count()):
                if self.workflow_list.item(index).data(1000) == current:
                    self.workflow_list.setCurrentRow(index)
                    break
        self.status.set_state(f"{len(workflows)} 个工作流", "online")

    def _failed(self, error) -> None:
        self.status.set_state("工作流不可用", "error")
        self.detail.setPlainText(f"工作流加载失败：{format_api_error(error)}")

    def _selected_workflow_id(self) -> str | None:
        item = self.workflow_list.currentItem()
        return item.data(1000) if item else None

    def _selected_workflow(self) -> dict | None:
        workflow_id = self._selected_workflow_id()
        return next((item for item in self._workflows if item.get("workflow_id") == workflow_id), None)

    def _on_workflow_selected(self, _row) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            return
        self.definition.setPlainText(json.dumps(workflow.get("definition") or {}, ensure_ascii=False, indent=2))
        self.detail.setPlainText(json.dumps(workflow, ensure_ascii=False, indent=2))
        self._run_api(
            lambda: self.api.workflow_runs(workflow["workflow_id"]),
            self._render_runs,
            lambda _error: self._render_runs([]),
            request_key="workflow-runs",
        )

    def _render_runs(self, result) -> None:
        runs = (result or {}).get("runs", []) if isinstance(result, dict) else (result or [])
        self._runs = runs
        self.run_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            values = [run.get("run_id", "")[:12], run.get("status", ""), run.get("current_node") or "-"]
            for column, value in enumerate(values):
                self.run_table.setItem(row, column, QTableWidgetItem(str(value)))
            self.run_table.item(row, 0).setData(1000, run.get("run_id"))

    def _on_run_selected(self) -> None:
        rows = self.run_table.selectionModel().selectedRows()
        if not rows:
            return
        self._current_run_id = self.run_table.item(rows[0].row(), 0).data(1000)
        run = next((item for item in self._runs if item.get("run_id") == self._current_run_id), None)
        if run:
            self.detail.setPlainText(json.dumps(run, ensure_ascii=False, indent=2))

    # -- actions ------------------------------------------------------------

    def create_workflow(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建工作流", "名称")
        if not accepted or not name.strip():
            return
        definition = dict(EXAMPLE_DEFINITION)
        self._run_api(
            lambda: self.api.create_workflow(name.strip(), definition),
            lambda _result: self.refresh(),
            self._action_failed,
            request_key="workflow-create",
        )

    def delete_workflow(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            QMessageBox.information(self, "提示", "请先选择工作流。")
            return
        if QMessageBox.question(self, "确认", "删除该工作流及其运行记录？") != QMessageBox.Yes:
            return
        self._run_api(
            lambda: self.api.delete_workflow(workflow["workflow_id"]),
            lambda _result: self.refresh(),
            self._action_failed,
            request_key="workflow-delete",
        )

    def run_workflow(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            QMessageBox.information(self, "提示", "请先选择工作流。")
            return
        try:
            run_input = json.loads(self.run_input.toPlainText() or "{}")
        except ValueError:
            QMessageBox.warning(self, "输入无效", "运行输入必须是 JSON 对象。")
            return
        self._run_api(
            lambda: self.api.run_workflow(workflow["workflow_id"], run_input),
            lambda _result: self._on_workflow_selected(self.workflow_list.currentRow()),
            self._action_failed,
            request_key="workflow-run",
        )

    def _poll(self) -> None:
        if self._current_run_id:
            self._run_api(
                lambda: self.api.workflow_run(self._current_run_id),
                self._render_run_detail,
                lambda _error: None,
                request_key="workflow-poll",
            )

    def _render_run_detail(self, run) -> None:
        if isinstance(run, dict):
            self.detail.setPlainText(json.dumps(run, ensure_ascii=False, indent=2))

    def show_trace(self) -> None:
        if not self._current_run_id:
            QMessageBox.information(self, "提示", "请先选择一次运行。")
            return
        self._run_api(
            lambda: self.api.workflow_trace(self._current_run_id),
            lambda trace: self.detail.setPlainText(json.dumps(trace, ensure_ascii=False, indent=2)),
            self._action_failed,
            request_key="workflow-trace",
        )

    def approve_run(self) -> None:
        if not self._current_run_id:
            QMessageBox.information(self, "提示", "请先选择一次运行。")
            return
        self._run_api(
            lambda: self.api.approve_workflow_run(self._current_run_id),
            lambda _result: self._poll(),
            self._action_failed,
            request_key="workflow-approve",
        )

    def cancel_run(self) -> None:
        if not self._current_run_id:
            QMessageBox.information(self, "提示", "请先选择一次运行。")
            return
        self._run_api(
            lambda: self.api.cancel_workflow_run(self._current_run_id),
            lambda _result: self._poll(),
            self._action_failed,
            request_key="workflow-cancel",
        )

    def _action_failed(self, error) -> None:
        self.status.set_state(f"操作失败：{format_api_error(error)}", "error")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self.shutdown_async_api()
        super().closeEvent(event)
