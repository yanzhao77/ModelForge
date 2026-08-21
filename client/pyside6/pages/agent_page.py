"""Native Agent Run workspace backed by the ModelForge REST and SSE APIs."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
from pages.run_timeline import RunTimeline
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
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

AGENT_TEMPLATES = {
    "自定义（最小权限）": {
        "tools": [],
        "prompt": "",
        "policy": {"network_access": False, "shell_access": False, "filesystem_write": False},
    },
    "研究摘要（只读）": {
        "tools": ["filesystem.read"],
        "prompt": "收集已有材料中的事实与不确定项，输出结构化摘要。不得修改文件或主动执行网络操作。",
        "policy": {
            "network_access": False,
            "shell_access": False,
            "filesystem_write": False,
            "require_approval_for": ["filesystem.read"],
        },
    },
    "代码审查（只读）": {
        "tools": ["filesystem.read", "code.search"],
        "prompt": "审查给定代码变更的正确性、安全性和可维护性。仅输出发现和建议，不修改文件。",
        "policy": {
            "network_access": False,
            "shell_access": False,
            "filesystem_write": False,
            "require_approval_for": ["filesystem.read", "code.search"],
        },
    },
    "数据质量检查（只读）": {
        "tools": ["filesystem.read"],
        "prompt": "检查数据中的重复、缺失字段、格式问题和隐私风险。返回可执行的验证报告，不删除数据。",
        "policy": {
            "network_access": False,
            "shell_access": False,
            "filesystem_write": False,
            "require_approval_for": ["filesystem.read"],
        },
    },
}


class AgentCreateDialog(QDialog):
    """Collect an agent definition in one reviewable, non-executing step."""

    def __init__(self, default_model: str = "", model_target: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建智能体")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        route = "已选默认模型目标会随定义保存。" if model_target else "将使用本地模型名称；可在模型工作区选择已验证目标。"
        note = QLabel(f"创建定义不会启动 Agent Run。默认策略拒绝网络、Shell 和文件写入，敏感操作仍需审批。{route}")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)
        form = QFormLayout()
        self.template = QComboBox()
        self.template.addItems(AGENT_TEMPLATES)
        self.name = QLineEdit()
        self.model = QLineEdit(default_model)
        self.model.setReadOnly(bool(model_target))
        self.tools = QLineEdit()
        self.tools.setPlaceholderText("例如：filesystem.read, code.search")
        self.system_prompt = QTextEdit()
        self.system_prompt.setMaximumHeight(92)
        self.policy_summary = QLabel()
        self.policy_summary.setWordWrap(True)
        self.policy_summary.setProperty("role", "muted")
        self._policy = dict(AGENT_TEMPLATES["自定义（最小权限）"]["policy"])
        form.addRow("模板", self.template)
        form.addRow("名称", self.name)
        form.addRow("模型", self.model)
        form.addRow("工具（可选）", self.tools)
        form.addRow("系统提示（可编辑）", self.system_prompt)
        form.addRow("策略预览", self.policy_summary)
        layout.addLayout(form)
        self.template.currentTextChanged.connect(self._apply_template)
        self._apply_template(self.template.currentText())
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("创建定义")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _apply_template(self, name: str) -> None:
        template = AGENT_TEMPLATES.get(name, AGENT_TEMPLATES["自定义（最小权限）"])
        self.tools.setText(", ".join(template["tools"]))
        self.system_prompt.setPlainText(template["prompt"])
        self._policy = dict(template["policy"])
        approvals = self._policy.get("require_approval_for") or []
        approval_text = f"；以下工具每次运行前需要人工审批：{', '.join(approvals)}" if approvals else ""
        self.policy_summary.setText(
            "网络、Shell 和文件写入均默认禁止" + approval_text + "。创建定义不会创建或启动 Run。"
        )

    def values(self) -> tuple[str, str, list[str], str, dict]:
        tools = [tool.strip() for tool in self.tools.text().split(",") if tool.strip()]
        return (
            self.name.text().strip(),
            self.model.text().strip(),
            tools,
            self.system_prompt.toPlainText().strip(),
            dict(self._policy),
        )


class AgentPage(QWidget, AsyncApiMixin):
    """Agent definitions, runs and live timeline without UI-thread HTTP calls."""

    def __init__(self, api, readiness_store=None, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.readiness_store = readiness_store
        self._model_ready = False
        self._default_model = ""
        self._default_target: dict = {}
        self._pending_agent_name: str | None = None
        self.current_run_id = None
        self._agents_loading = False
        self._runs_loading = False
        self._init_ui()
        self.refresh_agents()
        self.refresh_runs()
        if self.readiness_store:
            self.readiness_store.changed.connect(self._render_readiness)
            self.readiness_store.failed.connect(lambda _error: self._render_readiness({"level": "SERVICE_UNAVAILABLE"}))
            self.readiness_store.refresh()

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
        self.replay_btn = QPushButton("回放所选 Run")
        self.replay_btn.clicked.connect(self.replay_selected_run)
        mlay.addWidget(self.replay_btn)
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
        self.create_btn.setEnabled(not busy and self._model_ready)
        self.delete_btn.setEnabled(not busy)

    def _set_run_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy and self._model_ready)
        self.cancel_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.replay_btn.setEnabled(not busy and bool(self.current_run_id))

    def _report_error(self, action: str, error: str, popup: bool = True):
        self.status.setText(f"{action}失败：{error}")
        if popup:
            QMessageBox.warning(self, action, error)

    def _render_readiness(self, snapshot: dict) -> None:
        self._model_ready = snapshot.get("level") == "READY"
        target = snapshot.get("default_target") or {}
        self._default_model = target.get("model_name") or ""
        self._default_target = target
        self.create_btn.setEnabled(self._model_ready and not self._agents_loading)
        self.run_btn.setEnabled(self._model_ready and not self._runs_loading)
        if not self._model_ready:
            self.status.setText("请先在模型工作区配置并验证一个可用模型，再创建或运行智能体。")

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
            if agent.get("name") in {selected, self._pending_agent_name}:
                self.agent_list.setCurrentItem(item)
                self._pending_agent_name = None
        self.status.setText(f"已同步 {len(agents)} 个 Agent 定义。")

    def _agents_failed(self, error: str):
        self._agents_loading = False
        self._set_agent_busy(False)
        self._report_error("获取 Agent", error)

    def create_agent(self):
        if not self._model_ready:
            QMessageBox.information(self, "模型尚未就绪", "请先在模型工作区完成模型配置或远程服务验证。")
            return
        dialog = AgentCreateDialog(self._default_model, self._default_target, self)
        if dialog.exec() != QDialog.Accepted:
            return
        name, model, tool_list, system_prompt, policy = dialog.values()
        if not name or not model:
            QMessageBox.warning(self, "信息不完整", "智能体名称和模型均为必填项。")
            return
        self._set_agent_busy(True)
        self.status.setText("正在提交 Agent 定义…")
        self._run_api(
            lambda: self.api.create_agent_config(
                name.strip(), model.strip(), tool_list,
                system_prompt=system_prompt or None,
                policy=policy,
                model_target=self._default_target or None,
            ),
            lambda _result: self._agent_created(name.strip()),
            lambda error: self._agent_action_failed("创建 Agent", error),
        )

    def _agent_created(self, name: str):
        self._set_agent_busy(False)
        self._pending_agent_name = name
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
        if not self._model_ready:
            QMessageBox.information(self, "模型尚未就绪", "请先在模型工作区完成模型配置或远程服务验证。")
            return
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

    def replay_selected_run(self):
        if not self.current_run_id:
            QMessageBox.information(self, "提示", "请先选择已有 Run 再回放。")
            return
        self.timeline.watch(self.current_run_id, after_sequence=0)
        self.status.setText(f"正在从持久化事件回放 Run {self.current_run_id[:8]}。")

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
        self.replay_btn.setEnabled(bool(self.current_run_id) and not self._runs_loading)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
