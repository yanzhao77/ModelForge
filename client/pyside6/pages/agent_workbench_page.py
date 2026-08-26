"""Definition-first Agent workbench; it never creates a run on page load."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from components.api_worker import AsyncApiMixin


class AgentWorkbenchPage(QWidget, AsyncApiMixin):
    """Review templates and immutable definition snapshots before explicit runs."""

    navigate_requested = Signal(str)

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._agents: list[dict] = []
        self._templates: list[dict] = []
        self._versions: list[dict] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("Agent 工作台")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("在这里审阅定义、模板、模型目标、工具权限和知识范围。查看、保存模板和版本回放均不会创建 Agent Run。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        split = QSplitter(Qt.Horizontal)

        definitions = QWidget()
        definition_layout = QVBoxLayout(definitions)
        definition_layout.addWidget(QLabel("定义"))
        self.agent_list = QListWidget()
        self.agent_list.currentRowChanged.connect(self._load_versions)
        definition_layout.addWidget(self.agent_list, 1)
        self.save_template_button = QPushButton("将所选定义保存为模板")
        self.save_template_button.clicked.connect(self._save_template)
        definition_layout.addWidget(self.save_template_button)
        self.open_agents_button = QPushButton("前往智能体页面并显式运行")
        self.open_agents_button.clicked.connect(lambda: self.navigate_requested.emit("agents"))
        definition_layout.addWidget(self.open_agents_button)
        split.addWidget(definitions)

        templates = QWidget()
        template_layout = QVBoxLayout(templates)
        template_layout.addWidget(QLabel("模板"))
        self.template_list = QListWidget()
        self.template_list.currentRowChanged.connect(self._render_template)
        template_layout.addWidget(self.template_list, 1)
        self.delete_template_button = QPushButton("删除所选模板")
        self.delete_template_button.clicked.connect(self._delete_template)
        template_layout.addWidget(self.delete_template_button)
        split.addWidget(templates)

        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.addWidget(QLabel("定义版本与权限审阅"))
        self.version_list = QListWidget()
        self.version_list.currentRowChanged.connect(self._render_version)
        review_layout.addWidget(self.version_list, 1)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选择定义、模板或版本查看模型目标、工具、策略和知识范围。")
        review_layout.addWidget(self.detail, 2)
        self.refresh_button = QPushButton("刷新工作台")
        self.refresh_button.clicked.connect(self.refresh)
        review_layout.addWidget(self.refresh_button)
        split.addWidget(review)

        split.setSizes([300, 300, 520])
        layout.addWidget(split, 1)

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self._run_api(
            lambda: {"agents": self.api.list_agents(), "templates": self.api.list_agent_templates()},
            self._refresh_loaded,
            self._refresh_failed,
            request_key="agent_workbench.refresh",
        )

    def _refresh_loaded(self, data: dict) -> None:
        self.refresh_button.setEnabled(True)
        self._loaded(data)

    def _refresh_failed(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.detail.setPlainText(f"无法加载 Agent 工作台：{message}")

    def _loaded(self, data: dict) -> None:
        self._agents = data.get("agents") or []
        self._templates = data.get("templates") or []
        self.agent_list.clear()
        self.template_list.clear()
        for agent in self._agents:
            item = QListWidgetItem(f"{agent.get('name', '未命名')} · {agent.get('model', '—')}")
            item.setData(Qt.ItemDataRole.UserRole, agent)
            self.agent_list.addItem(item)
        for template in self._templates:
            item = QListWidgetItem(template.get("name", "未命名模板"))
            item.setData(Qt.ItemDataRole.UserRole, template)
            self.template_list.addItem(item)
        if not self._agents:
            self.detail.setPlainText("尚无 Agent 定义。请在智能体页面创建定义；创建定义不会自动启动 Run。")

    def _selected_agent(self) -> dict | None:
        item = self.agent_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_template(self) -> dict | None:
        item = self.template_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _load_versions(self) -> None:
        agent = self._selected_agent()
        self.version_list.clear()
        self._versions = []
        if not agent:
            return
        self._render_definition(agent)
        self._run_api(
            lambda: self.api.agent_versions(agent["name"]),
            self._versions_loaded,
            lambda message: self.detail.append(f"\n版本记录不可用：{message}"),
            request_key="agent_workbench.versions",
        )

    def _versions_loaded(self, data: dict) -> None:
        self._versions = data.get("versions") or []
        for version in self._versions:
            item = QListWidgetItem(f"v{version.get('version', '?')} · {version.get('created_at', '—')}")
            item.setData(Qt.ItemDataRole.UserRole, version)
            self.version_list.addItem(item)

    def _render_definition(self, agent: dict) -> None:
        self.detail.setPlainText(self._definition_text(agent, "当前定义"))

    def _render_template(self) -> None:
        template = self._selected_template()
        if not template:
            return
        definition = template.get("definition") or {}
        self.detail.setPlainText(self._definition_text(definition, f"模板：{template.get('name', '未命名')}") + "\n\n导入模板需要在智能体页面显式创建定义；该操作不会自动运行 Agent。")

    def _render_version(self) -> None:
        item = self.version_list.currentItem()
        if not item:
            return
        version = item.data(Qt.ItemDataRole.UserRole) or {}
        snapshot = version.get("snapshot") or {}
        self.detail.setPlainText(self._definition_text(snapshot, f"定义版本 v{version.get('version', '?')}") + "\n\n版本为历史快照；恢复时应创建新版本，不改写历史 Run。")

    @staticmethod
    def _definition_text(definition: dict, heading: str) -> str:
        target = definition.get("model_target") or {}
        knowledge = definition.get("knowledge_config") or {}
        policy = definition.get("policy") or {}
        tools = definition.get("tools") or []
        return "\n".join([
            heading,
            f"模型：{definition.get('model', '—')}",
            f"模型目标：{target.get('kind', '本地/未指定')} · {target.get('model_ref') or target.get('model_name') or '—'}",
            f"工具：{', '.join(tools) if tools else '无'}",
            f"人工审批：{', '.join(policy.get('require_approval_for') or []) or '未额外声明'}",
            f"知识范围：{json.dumps(knowledge, ensure_ascii=False) if knowledge else '未配置（兼容既有行为）'}",
            f"系统提示：{definition.get('system_prompt') or '—'}",
        ])

    def _save_template(self) -> None:
        agent = self._selected_agent()
        if not agent:
            QMessageBox.information(self, "Agent 工作台", "请先选择要保存为模板的 Agent 定义。")
            return
        name, ok = QInputDialog.getText(self, "保存模板", "模板名称", text=f"{agent.get('name', 'Agent')} 模板")
        if not ok or not name.strip():
            return
        self._run_api(
            lambda: self.api.create_agent_template(name.strip(), agent, f"从 {agent.get('name', 'Agent')} 定义保存"),
            lambda _result: self.refresh(),
            lambda message: QMessageBox.warning(self, "保存模板", str(message)),
            request_key="agent_workbench.template.save",
        )

    def _delete_template(self) -> None:
        template = self._selected_template()
        if not template:
            return
        if QMessageBox.question(self, "删除模板", f"删除模板“{template.get('name')}”？不会删除任何 Agent 定义或 Run。") != QMessageBox.StandardButton.Yes:
            return
        self._run_api(
            lambda: self.api.delete_agent_template(template["id"]),
            lambda _result: self.refresh(),
            lambda message: QMessageBox.warning(self, "删除模板", str(message)),
            request_key="agent_workbench.template.delete",
        )

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
