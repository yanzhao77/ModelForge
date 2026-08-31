from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFEmptyState, MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SecretKeyDialog(QDialog):
    """Displays a newly issued API key exactly once and only after explicit issuance."""

    def __init__(self, secret: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存项目 API 密钥")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        notice = QLabel("该密钥只会显示一次。请立即复制并保存到受保护的密钥管理工具中。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.secret = QLineEdit(secret)
        self.secret.setReadOnly(True)
        self.secret.setEchoMode(QLineEdit.Normal)
        self.secret.setAccessibleName("新签发的项目 API 密钥")
        layout.addWidget(self.secret)
        actions = QDialogButtonBox(QDialogButtonBox.Close)
        copy = actions.addButton("复制密钥", QDialogButtonBox.ActionRole)
        copy.clicked.connect(self._copy)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.secret.text())
        self.secret.selectAll()


class DeveloperApiPage(QWidget, AsyncApiMixin):
    """Project API control plane for the API-centric commercial surface."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.organizations: list[dict] = []
        self.projects: list[dict] = []
        self.agents: list[dict] = []
        self._selected_project_id: str | None = None
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("开发者", "项目 API"))
        header.addStretch(1)
        self.status = MFStatusBadge("正在加载项目…", "warning")
        header.addWidget(self.status)
        layout.addLayout(header)
        intro = QLabel("在此管理用于 Agent API 调用的组织、项目、已授权 Agent、访问密钥、强制额度和用量账本。页面访问不会计费。")
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        layout.addWidget(intro)

        body = QGridLayout()
        body.setColumnStretch(1, 1)
        organization_column = QVBoxLayout()
        organization_column.addWidget(QLabel("组织"))
        self.organization_select = QComboBox()
        self.organization_select.setAccessibleName("组织")
        organization_column.addWidget(self.organization_select)
        create_organization = QPushButton("新建组织")
        create_organization.clicked.connect(self.create_organization)
        organization_column.addWidget(create_organization)
        organization_column.addStretch(1)
        org_widget = QWidget()
        org_widget.setLayout(organization_column)
        body.addWidget(org_widget, 0, 0)

        project_column = QVBoxLayout()
        project_header = QHBoxLayout()
        project_header.addWidget(QLabel("项目"))
        project_header.addStretch(1)
        create_project = QPushButton("新建项目")
        create_project.clicked.connect(self.create_project)
        project_header.addWidget(create_project)
        project_column.addLayout(project_header)
        self.project_list = QListWidget()
        self.project_list.setAccessibleName("API 项目列表")
        self.project_list.itemSelectionChanged.connect(self._project_selected)
        project_column.addWidget(self.project_list, 1)
        self.project_empty = MFEmptyState("暂无项目", "选择或创建组织后，新建一个 test 或 live 项目。")
        self.project_stack = QStackedWidget()
        projects_widget = QWidget()
        projects_widget.setLayout(project_column)
        self.project_stack.addWidget(projects_widget)
        self.project_stack.addWidget(self.project_empty)
        body.addWidget(self.project_stack, 0, 1)
        layout.addLayout(body, 1)

        self.details = QStackedWidget()
        self.details.addWidget(self._empty_details())
        self.details.addWidget(self._project_details())
        layout.addWidget(self.details, 2)

    def _empty_details(self) -> QWidget:
        return MFEmptyState("选择一个项目", "选择项目后可管理授权 Agent、密钥、强制额度和用量账本。")

    def _project_details(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        project_header = QHBoxLayout()
        self.project_title = QLabel("未选择项目")
        self.project_title.setProperty("role", "pageTitle")
        project_header.addWidget(self.project_title)
        project_header.addStretch(1)
        self.environment = MFStatusBadge("", "warning")
        project_header.addWidget(self.environment)
        layout.addLayout(project_header)
        self.project_endpoint = QLabel("API 端点：/api/v2/runs")
        self.project_endpoint.setProperty("role", "muted")
        layout.addWidget(self.project_endpoint)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._agents_panel(), 0, 0)
        grid.addWidget(self._keys_panel(), 0, 1)
        grid.addWidget(self._quota_panel(), 1, 0)
        grid.addWidget(self._usage_panel(), 1, 1)
        layout.addLayout(grid, 1)
        return page

    def _agents_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("已授权 Agent"))
        self.project_agents = QListWidget()
        self.project_agents.setAccessibleName("已授权 Agent 列表")
        layout.addWidget(self.project_agents, 1)
        action = QHBoxLayout()
        self.available_agents = QComboBox()
        self.available_agents.setAccessibleName("可授权 Agent")
        action.addWidget(self.available_agents, 1)
        self.bind_agent_btn = QPushButton("授权 Agent")
        self.bind_agent_btn.clicked.connect(self.bind_agent)
        action.addWidget(self.bind_agent_btn)
        layout.addLayout(action)
        return panel

    def _keys_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("项目 API 密钥"))
        self.key_list = QListWidget()
        self.key_list.setAccessibleName("项目 API 密钥列表")
        layout.addWidget(self.key_list, 1)
        actions = QHBoxLayout()
        self.issue_key_btn = QPushButton("签发密钥")
        self.issue_key_btn.setProperty("accent", True)
        self.issue_key_btn.clicked.connect(self.issue_key)
        actions.addWidget(self.issue_key_btn)
        self.revoke_key_btn = QPushButton("撤销所选密钥")
        self.revoke_key_btn.clicked.connect(self.revoke_key)
        actions.addWidget(self.revoke_key_btn)
        layout.addLayout(actions)
        return panel

    def _quota_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        form.addRow(QLabel("强制额度"))
        self.concurrent_limit = self._limit_input(1, 100, 3)
        self.daily_limit = self._limit_input(1, 100_000_000, 100_000)
        self.monthly_limit = self._limit_input(1, 1_000_000_000, 1_000_000)
        self.per_run_limit = self._limit_input(1, 1_000_000, 8_192)
        form.addRow("最大并发运行", self.concurrent_limit)
        form.addRow("每日令牌上限", self.daily_limit)
        form.addRow("每月令牌上限", self.monthly_limit)
        form.addRow("单次运行上限", self.per_run_limit)
        self.save_quota_btn = QPushButton("保存强制额度")
        self.save_quota_btn.clicked.connect(self.save_quota)
        form.addRow(self.save_quota_btn)
        return panel

    @staticmethod
    def _limit_input(minimum: int, maximum: int, value: int) -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setGroupSeparatorShown(True)
        return control

    def _usage_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        header = QHBoxLayout()
        header.addWidget(QLabel("不可变用量账本"))
        header.addStretch(1)
        self.refresh_usage_btn = QPushButton("刷新用量")
        self.refresh_usage_btn.clicked.connect(self.refresh_project_details)
        header.addWidget(self.refresh_usage_btn)
        layout.addLayout(header)
        self.usage = QTextEdit()
        self.usage.setReadOnly(True)
        self.usage.setAccessibleName("项目用量账本摘要")
        self.usage.setPlaceholderText("选择项目后显示用量和额度摘要。")
        layout.addWidget(self.usage, 1)
        return panel

    def refresh(self) -> None:
        self.status.set_state("正在加载项目…", "warning")
        self._run_api(
            lambda: {
                "organizations": self.api.list_organizations(),
                "projects": self.api.list_api_projects(),
                "agents": self.api.list_agents(),
            },
            self._render_catalog,
            self._load_failed,
            request_key="developer-api-catalog",
        )

    def _render_catalog(self, data: dict) -> None:
        self.organizations = data.get("organizations", [])
        self.projects = data.get("projects", [])
        self.agents = data.get("agents", [])
        current_org = self.organization_select.currentData()
        self.organization_select.blockSignals(True)
        self.organization_select.clear()
        for organization in self.organizations:
            self.organization_select.addItem(organization.get("name", "未命名组织"), organization.get("id"))
        if current_org:
            index = self.organization_select.findData(current_org)
            if index >= 0:
                self.organization_select.setCurrentIndex(index)
        self.organization_select.blockSignals(False)
        self._render_projects()
        self.status.set_state("项目 API 已就绪", "online")

    def _render_projects(self) -> None:
        selected = self._selected_project_id
        self.project_list.clear()
        for project in self.projects:
            item = QListWidgetItem(f"{project.get('name', '未命名项目')} · {project.get('environment', 'test')}")
            item.setData(32, project.get("id"))
            self.project_list.addItem(item)
            if project.get("id") == selected:
                self.project_list.setCurrentItem(item)
        self.project_stack.setCurrentIndex(0 if self.project_list.count() else 1)
        if self.project_list.currentItem() is None and self.project_list.count():
            self.project_list.setCurrentRow(0)

    def _project_selected(self) -> None:
        item = self.project_list.currentItem()
        self._selected_project_id = item.data(32) if item else None
        self.details.setCurrentIndex(1 if self._selected_project_id else 0)
        if self._selected_project_id:
            self.refresh_project_details()

    def _selected_project(self) -> dict | None:
        return next((item for item in self.projects if item.get("id") == self._selected_project_id), None)

    def refresh_project_details(self) -> None:
        project_id = self._selected_project_id
        if not project_id:
            return
        self._set_details_enabled(False)
        self._run_api(
            lambda: {
                "bindings": self.api.list_project_agents(project_id),
                "keys": self.api.list_project_keys(project_id),
                "usage": self.api.project_usage(project_id),
            },
            lambda data: self._render_project_details(project_id, data),
            self._details_failed,
            request_key="developer-api-details",
        )

    def _render_project_details(self, project_id: str, data: dict) -> None:
        if project_id != self._selected_project_id:
            return
        project = self._selected_project() or {}
        self.project_title.setText(project.get("name", "项目"))
        environment = project.get("environment", "test")
        self.environment.set_state("生产环境" if environment == "live" else "测试环境", "online" if environment == "live" else "warning")
        self.project_endpoint.setText(f"API 端点：{self.api.base_url}/api/v2/runs")
        self.project_agents.clear()
        for binding in data.get("bindings", []):
            self.project_agents.addItem(str(binding.get("agent_id", "未知 Agent")))
        if not self.project_agents.count():
            self.project_agents.addItem("尚未授权 Agent；项目密钥暂不能执行 Agent Run。")
        bound = {item.get("agent_id") for item in data.get("bindings", [])}
        self.available_agents.clear()
        for agent in self.agents:
            agent_id = agent.get("name") or agent.get("id")
            if agent_id and agent_id not in bound:
                self.available_agents.addItem(str(agent_id), str(agent_id))
        self.key_list.clear()
        for key in data.get("keys", []):
            status = "已撤销" if key.get("revoked_at") else "可用"
            self.key_list.addItem(f"{key.get('name', '未命名')} · {key.get('prefix', '-') } · {status}")
            self.key_list.item(self.key_list.count() - 1).setData(32, key.get("id"))
        if not self.key_list.count():
            self.key_list.addItem("尚未签发项目密钥。")
        quota = (data.get("usage") or {}).get("quota") or {}
        self.concurrent_limit.setValue(int(quota.get("max_concurrent_runs") or 3))
        self.daily_limit.setValue(int(quota.get("daily_token_limit") or 100_000))
        self.monthly_limit.setValue(int(quota.get("monthly_token_limit") or 1_000_000))
        self.per_run_limit.setValue(int(quota.get("per_run_token_limit") or 8_192))
        self.usage.setPlainText(self._format_usage(data.get("usage") or {}))
        self._set_details_enabled(True)

    @staticmethod
    def _format_usage(usage: dict) -> str:
        lines = [
            f"账本版本：{usage.get('ledger_version', 'trial-v1')}",
            f"今日已计令牌：{usage.get('daily_tokens', 0)}",
            f"本月已计令牌：{usage.get('monthly_tokens', 0)}",
            f"当前运行中调用：{usage.get('active_invocations', 0)}",
        ]
        for entry in usage.get("entries", [])[:50]:
            lines.append(
                f"{entry.get('created_at', '-')} · {entry.get('tokens', 0)} tokens · {entry.get('status', '-')}"
            )
        return "\n".join(lines)

    def _set_details_enabled(self, enabled: bool) -> None:
        for widget in (self.bind_agent_btn, self.available_agents, self.issue_key_btn, self.revoke_key_btn, self.save_quota_btn, self.refresh_usage_btn):
            widget.setEnabled(enabled)

    def _load_failed(self, error: str) -> None:
        self.status.set_state("项目 API 加载失败", "error")
        QMessageBox.warning(self, "项目 API", format_api_error(error))

    def _details_failed(self, error: str) -> None:
        self._set_details_enabled(True)
        QMessageBox.warning(self, "项目详情", format_api_error(error))

    def create_organization(self) -> None:
        name, ok = QInputDialog.getText(self, "新建组织", "组织名称")
        if ok and name.strip():
            self._mutate(lambda: self.api.create_organization(name.strip()))

    def create_project(self) -> None:
        organization_id = self.organization_select.currentData()
        if not organization_id:
            QMessageBox.information(self, "请先创建组织", "创建项目之前，请先选择或创建一个组织。")
            return
        name, ok = QInputDialog.getText(self, "新建项目", "项目名称")
        if not ok or not name.strip():
            return
        environment, ok = QInputDialog.getItem(self, "选择环境", "环境", ["test", "live"], 0, False)
        if ok:
            self._mutate(lambda: self.api.create_api_project(str(organization_id), name.strip(), environment))

    def bind_agent(self) -> None:
        project_id = self._selected_project_id
        agent_id = self.available_agents.currentData()
        if project_id and agent_id:
            self._mutate(lambda: self.api.bind_project_agent(project_id, str(agent_id)), refresh_details=True)

    def issue_key(self) -> None:
        project_id = self._selected_project_id
        if not project_id:
            return
        name, ok = QInputDialog.getText(self, "签发项目 API 密钥", "密钥名称", text="desktop")
        if not ok or not name.strip():
            return
        self._run_api(
            lambda: self.api.create_project_key(project_id, name.strip()),
            self._key_issued,
            lambda error: QMessageBox.warning(self, "签发密钥失败", format_api_error(error)),
            request_key="issue-project-key",
        )

    def _key_issued(self, result: dict) -> None:
        secret = result.get("secret")
        if isinstance(secret, str) and secret:
            SecretKeyDialog(secret, self).exec()
        self.refresh_project_details()

    def revoke_key(self) -> None:
        project_id = self._selected_project_id
        item = self.key_list.currentItem()
        key_id = item.data(32) if item else None
        if not project_id or not key_id:
            return
        if QMessageBox.question(self, "确认撤销密钥", "撤销后该密钥立即失效，且无法恢复。是否继续？") == QMessageBox.Yes:
            self._mutate(lambda: self.api.revoke_project_key(project_id, str(key_id), confirm=True), refresh_details=True)

    def save_quota(self) -> None:
        project_id = self._selected_project_id
        if not project_id:
            return
        if QMessageBox.question(self, "确认修改强制额度", "新的额度将立即用于后续项目 API 调用。是否继续？") != QMessageBox.Yes:
            return
        self._mutate(
            lambda: self.api.update_project_quota(
                project_id,
                max_concurrent_runs=self.concurrent_limit.value(),
                daily_token_limit=self.daily_limit.value(),
                monthly_token_limit=self.monthly_limit.value(),
                per_run_token_limit=self.per_run_limit.value(),
            ),
            refresh_details=True,
        )

    def _mutate(self, operation, *, refresh_details: bool = False) -> None:
        self._run_api(
            operation,
            lambda _result: self.refresh_project_details() if refresh_details else self.refresh(),
            lambda error: QMessageBox.warning(self, "项目 API 操作未完成", format_api_error(error)),
            request_key="developer-api-mutation",
        )

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
