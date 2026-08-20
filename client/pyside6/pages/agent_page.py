"""Native Agent Run workspace backed by the ModelForge REST and SSE APIs."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFSection, MFStatusBadge
from components.example_library import open_examples
from pages.run_timeline import RunTimeline
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
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


class AgentPage(QWidget, AsyncApiMixin):
    """Agent definitions, runs and live timeline without UI-thread HTTP calls."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.current_run_id = None
        self._agents_loading = False
        self._runs_loading = False
        self._init_ui()
        self.refresh_agents()
        self.refresh_runs()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("智能体工作区", "智能体"))
        header.addStretch(1)
        self.matrix_status = MFStatusBadge("Syncing Agents", "warning")
        header.addWidget(self.matrix_status)
        examples = QPushButton("示例")
        examples.clicked.connect(lambda: open_examples("agents", self, lambda example: self.task_input.setPlainText(example.template)))
        header.addWidget(examples)
        root.addLayout(header)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        lay = QVBoxLayout(left)
        lay.addWidget(QLabel("智能体"))
        self.agent_list = QListWidget()
        self.agent_list.currentItemChanged.connect(lambda *_: self._on_agent_selected())
        lay.addWidget(self.agent_list, 1)
        self.create_btn = QPushButton("新建智能体")
        self.create_btn.clicked.connect(self.create_agent)
        lay.addWidget(self.create_btn)
        self.delete_btn = QPushButton("删除智能体")
        self.delete_btn.clicked.connect(self.delete_agent)
        lay.addWidget(self.delete_btn)
        splitter.addWidget(left)

        mid = QWidget()
        mlay = QVBoxLayout(mid)
        mlay.addWidget(QLabel("最近运行"))
        self.runs_table = QTableWidget()
        self.runs_table.setColumnCount(4)
        self.runs_table.setHorizontalHeaderLabels(["Run", "Agent", "Status", "Output"])
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.runs_table.itemSelectionChanged.connect(self._on_run_selected)
        mlay.addWidget(self.runs_table, 1)
        self.task_input = QTextEdit()
        self.task_input.setPlaceholderText("给 Agent 的任务描述...")
        self.task_input.setMaximumHeight(70)
        mlay.addWidget(self.task_input)
        self.run_btn = QPushButton("运行智能体")
        self.run_btn.clicked.connect(self.run_agent)
        mlay.addWidget(self.run_btn)
        self.cancel_btn = QPushButton("取消运行")
        self.cancel_btn.clicked.connect(self.cancel_run)
        mlay.addWidget(self.cancel_btn)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_runs)
        mlay.addWidget(self.refresh_btn)
        self.status = QLabel("正在加载 Agent 与运行记录…")
        self.status.setWordWrap(True)
        mlay.addWidget(self.status)
        splitter.addWidget(mid)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.addWidget(QLabel("活动记录"))
        self.timeline = RunTimeline(self.api)
        rlay.addWidget(self.timeline, 1)
        splitter.addWidget(right)
        splitter.setSizes([220, 380, 420])
        root.addWidget(splitter, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.refresh_runs(silent=True))
        self._timer.start(2000)

    def _set_agent_busy(self, busy: bool):
        self.create_btn.setEnabled(not busy)
        self.delete_btn.setEnabled(not busy)

    def _set_run_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)

    def _report_error(self, action: str, error: str, popup: bool = True):
        self.status.setText(f"{action}失败：{error}")
        if popup:
            QMessageBox.warning(self, action, error)

    def refresh_agents(self):
        if self._agents_loading:
            return
        self._agents_loading = True
        self._set_agent_busy(True)
        self._run_api(self.api.list_agents, self._render_agents, self._agents_failed)

    def _render_agents(self, agents):
        self._agents_loading = False
        self._set_agent_busy(False)
        selected = self.selected_agent()
        self.matrix_status.set_state(f"{len(agents)} Agents synced", "online")
        self.agent_list.clear()
        for agent in agents:
            item = QListWidgetItem(f"{agent.get('name', '?')}  ({agent.get('model', '')})")
            item.setData(Qt.UserRole, agent.get("name"))
            self.agent_list.addItem(item)
            if agent.get("name") == selected:
                self.agent_list.setCurrentItem(item)
        self.status.setText(f"已同步 {len(agents)} 个 Agent 定义。")

    def _agents_failed(self, error: str):
        self._agents_loading = False
        self._set_agent_busy(False)
        self._report_error("获取 Agent", error)

    def create_agent(self):
        name, ok1 = QInputDialog.getText(self, "新建 Agent", "名称:")
        if not ok1 or not name.strip():
            return
        model, ok2 = QInputDialog.getText(self, "新建 Agent", "模型 (Ollama 名称):")
        if not ok2 or not model.strip():
            return
        tools, ok3 = QInputDialog.getText(self, "新建 Agent", "工具 (逗号分隔, 如 filesystem.read,code.search):")
        if not ok3:
            return
        tool_list = [tool.strip() for tool in tools.split(",") if tool.strip()]
        self._set_agent_busy(True)
        self.status.setText("正在提交 Agent 定义…")
        self._run_api(
            lambda: self.api.create_agent_config(name.strip(), model.strip(), tool_list),
            lambda _result: self._agent_created(name.strip()),
            lambda error: self._agent_action_failed("创建 Agent", error),
        )

    def _agent_created(self, name: str):
        self._set_agent_busy(False)
        self.status.setText(f"已创建 Agent：{name}。正在刷新定义列表…")
        self.refresh_agents()

    def delete_agent(self):
        name = self.selected_agent()
        if not name:
            QMessageBox.information(self, "提示", "请先选择需要删除的 Agent。")
            return
        if QMessageBox.question(self, "确认", f"确定删除 Agent {name}?" ) != QMessageBox.Yes:
            return
        self._set_agent_busy(True)
        self.status.setText(f"正在删除 Agent：{name}…")
        self._run_api(
            lambda: self.api.delete_agent(name),
            lambda _result: self._agent_deleted(name),
            lambda error: self._agent_action_failed("删除 Agent", error),
        )

    def _agent_deleted(self, name: str):
        self._set_agent_busy(False)
        self.status.setText(f"已删除 Agent：{name}。正在刷新定义列表…")
        self.refresh_agents()

    def _agent_action_failed(self, action: str, error: str):
        self._set_agent_busy(False)
        self._report_error(action, error)

    def _on_agent_selected(self):
        self.delete_btn.setEnabled(bool(self.selected_agent()) and not self._agents_loading)

    def selected_agent(self):
        item = self.agent_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def run_agent(self):
        agent = self.selected_agent()
        if not agent:
            QMessageBox.warning(self, "提示", "请先选择 Agent")
            return
        task = self.task_input.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "提示", "请输入任务描述")
            return
        self._set_run_busy(True)
        self.status.setText(f"正在启动 {agent}…")
        self._run_api(
            lambda: self.api.create_agent_run(agent, task),
            self._run_created,
            lambda error: self._run_action_failed("启动 Agent Run", error),
        )

    def _run_created(self, result):
        self._set_run_busy(False)
        self.current_run_id = result["run_id"]
        self.task_input.clear()
        self.status.setText(f"已创建 Run {self.current_run_id[:8]}，正在订阅事件流。")
        self.timeline.watch(self.current_run_id)
        self.refresh_runs()

    def cancel_run(self):
        run_id = self.current_run_id
        if not run_id:
            QMessageBox.information(self, "提示", "请先选择需要取消的 Run。")
            return
        self._set_run_busy(True)
        self.status.setText(f"正在请求取消 Run {run_id[:8]}…")
        self._run_api(
            lambda: self.api.cancel_agent_run(run_id),
            self._run_cancelled,
            lambda error: self._run_action_failed("取消 Agent Run", error),
        )
    def _run_cancelled(self):
        self._set_run_busy(False)
        self.status.setText("取消请求已提交，正在刷新运行记录。")
        self.refresh_runs()

    def _run_action_failed(self, action: str, error: str):
        self._set_run_busy(False)
        self._report_error(action, error)

    def refresh_runs(self, silent: bool = False):
        if self._runs_loading:
            return
        self._runs_loading = True
        self._set_run_busy(True)
        self._run_api(
            lambda: self.api.list_agent_runs(limit=30),
            self._render_runs,
            lambda error: self._runs_failed(error, silent),
        )

    def _render_runs(self, runs):
        self._runs_loading = False
        self._set_run_busy(False)
        selected = self.current_run_id
        self.runs_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            self.runs_table.setItem(row, 0, QTableWidgetItem(str(run.get("run_id", ""))[:8]))
            self.runs_table.setItem(row, 1, QTableWidgetItem(str(run.get("agent_id", ""))))
            self.runs_table.setItem(row, 2, QTableWidgetItem(str(run.get("status", ""))))
            self.runs_table.setItem(row, 3, QTableWidgetItem(str(run.get("output", "") or "")[:60]))
            self.runs_table.item(row, 0).setData(Qt.UserRole, run.get("run_id"))
            if run.get("run_id") == selected:
                self.runs_table.selectRow(row)
        self.status.setText(f"运行记录已更新 · {len(runs)} 项。")

    def _runs_failed(self, error: str, silent: bool):
        self._runs_loading = False
        self._set_run_busy(False)
        if not silent:
            self._report_error("获取运行记录", error)
        else:
            self.status.setText(f"运行记录刷新失败：{error}")

    def _on_run_selected(self):
        rows = self.runs_table.selectionModel().selectedRows()
        if not rows:
            return
        run_id = self.runs_table.item(rows[0].row(), 0).data(Qt.UserRole)
        if run_id and run_id != self.current_run_id:
            self.current_run_id = run_id
            self.timeline.watch(run_id)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
