"""AgentPage: manage 3.0 agents, trigger runs, watch live timelines (spec 50).

Thin client: all runtime logic lives in the backend; this page only calls
the REST + SSE APIs.
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from pages.run_timeline import RunTimeline


class AgentPage(QWidget):
    """Agent list + create + runs table + live timeline (spec 71)."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.current_run_id = None
        self._init_ui()
        self.refresh_agents()
        self.refresh_runs()

    def _init_ui(self):
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # ---- left: agents ----
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.addWidget(QLabel("<b>Agents</b>"))
        self.agent_list = QListWidget()
        self.agent_list.currentItemChanged.connect(lambda *_: self._on_agent_selected())
        lay.addWidget(self.agent_list, 1)
        create_btn = QPushButton("+ 新建 Agent")
        create_btn.clicked.connect(self.create_agent)
        lay.addWidget(create_btn)
        delete_btn = QPushButton("删除 Agent")
        delete_btn.clicked.connect(self.delete_agent)
        lay.addWidget(delete_btn)
        splitter.addWidget(left)

        # ---- middle: runs ----
        mid = QWidget()
        mlay = QVBoxLayout(mid)
        mlay.addWidget(QLabel("<b>Runs</b>"))
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
        run_btn = QPushButton("▶ 运行选中 Agent")
        run_btn.clicked.connect(self.run_agent)
        mlay.addWidget(run_btn)
        cancel_btn = QPushButton("✖ 取消运行")
        cancel_btn.clicked.connect(self.cancel_run)
        mlay.addWidget(cancel_btn)
        refresh_btn = QPushButton("刷新 Runs")
        refresh_btn.clicked.connect(self.refresh_runs)
        mlay.addWidget(refresh_btn)
        splitter.addWidget(mid)

        # ---- right: timeline ----
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.addWidget(QLabel("<b>Run Timeline</b>"))
        self.timeline = RunTimeline(self.api)
        rlay.addWidget(self.timeline, 1)
        splitter.addWidget(right)
        splitter.setSizes([220, 380, 420])
        root.addWidget(splitter)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_runs)
        self._timer.start(2000)

    def refresh_agents(self):
        try:
            agents = self.api.list_agents()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"获取 Agents 失败: {e}")
            return
        self.agent_list.clear()
        for a in agents:
            self.agent_list.addItem(f"{a.get('name', '?')}  ({a.get('model', '')})")

    def create_agent(self):
        name, ok1 = QInputDialog.getText(self, "新建 Agent", "名称:")
        if not ok1 or not name.strip():
            return
        model, ok2 = QInputDialog.getText(self, "新建 Agent", "模型 (Ollama 名称):")
        if not ok2:
            return
        tools, ok3 = QInputDialog.getText(self, "新建 Agent", "工具 (逗号分隔, 如 filesystem.read,code.search):")
        tool_list = [t.strip() for t in (tools or "").split(",") if t.strip()]
        try:
            self.api.create_agent_config(name.strip(), model.strip(), tool_list)
            self.refresh_agents()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def delete_agent(self):
        item = self.agent_list.currentItem()
        if not item:
            return
        name = item.text().split("  (")[0]
        if QMessageBox.question(self, "确认", f"删除 Agent {name}?") == QMessageBox.Yes:
            try:
                self.api._delete(f"/api/v1/agent/{name}")
                self.refresh_agents()
            except Exception as e:
                QMessageBox.warning(self, "失败", str(e))

    def _on_agent_selected(self):
        pass

    def selected_agent(self):
        item = self.agent_list.currentItem()
        return item.text().split("  (")[0] if item else None

    def run_agent(self):
        agent = self.selected_agent()
        if not agent:
            QMessageBox.warning(self, "提示", "请先选择 Agent")
            return
        task = self.task_input.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "提示", "请输入任务描述")
            return
        try:
            result = self.api.create_agent_run(agent, task)
            self.current_run_id = result["run_id"]
            self.refresh_runs()
            self.timeline.watch(self.current_run_id)
            self.task_input.clear()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def cancel_run(self):
        if self.current_run_id:
            try:
                self.api.cancel_agent_run(self.current_run_id)
                self.refresh_runs()
            except Exception as e:
                QMessageBox.warning(self, "失败", str(e))

    def refresh_runs(self):
        try:
            runs = self.api.list_agent_runs(limit=30)
        except Exception as e:
            return
        self.runs_table.setRowCount(len(runs))
        for row, r in enumerate(runs):
            self.runs_table.setItem(row, 0, QTableWidgetItem(r.get("run_id", "")[:8]))
            self.runs_table.setItem(row, 1, QTableWidgetItem(str(r.get("agent_id", ""))))
            self.runs_table.setItem(row, 2, QTableWidgetItem(str(r.get("status", ""))))
            self.runs_table.setItem(row, 3, QTableWidgetItem(str(r.get("output", "") or "")[:60]))
            self.runs_table.item(row, 0).setData(Qt.UserRole, r.get("run_id"))

    def _on_run_selected(self):
        rows = self.runs_table.selectionModel().selectedRows()
        if not rows:
            return
        run_id = self.runs_table.item(rows[0].row(), 0).data(Qt.UserRole)
        if run_id and run_id != self.current_run_id:
            self.current_run_id = run_id
            self.timeline.watch(run_id)

    def _poll_runs(self):
        try:
            self.refresh_runs()
        except Exception:
            pass

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)