from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFEmptyState, MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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


class LocalInferenceApiPage(QWidget, AsyncApiMixin):
    """Control console for the local OpenAI-compatible /v1 API."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.models: list[dict] = []
        self.keys: list[dict] = []
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("API 接口", "本地 OpenAI 兼容服务"))
        header.addStretch(1)
        self.status = MFStatusBadge("正在读取状态…", "warning")
        header.addWidget(self.status)
        self.start_btn = QPushButton("启动")
        self.start_btn.setToolTip("启用本地 OpenAI 兼容 /v1 API。默认只监听 127.0.0.1。")
        self.start_btn.clicked.connect(self.start_service)
        header.addWidget(self.start_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setToolTip("停止接受外部 /v1 API 请求；桌面控制台仍可管理设置。")
        self.stop_btn.clicked.connect(self.stop_service)
        header.addWidget(self.stop_btn)
        self.restart_btn = QPushButton("重启")
        self.restart_btn.setToolTip("用最新配置重新启用本地 API。")
        self.restart_btn.clicked.connect(self.restart_service)
        header.addWidget(self.restart_btn)
        layout.addLayout(header)

        settings = QGridLayout()
        self.base_url = QLineEdit()
        self.base_url.setReadOnly(True)
        self.base_url.setAccessibleName("OpenAI 兼容 API Base URL")
        self.host = QLineEdit("127.0.0.1")
        self.host.setAccessibleName("API 主机")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8000)
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 64)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 3600)
        self.timeout.setSuffix(" 秒")
        self.auto_load = QPushButton("自动加载：开")
        self.auto_load.setCheckable(True)
        self.auto_load.setToolTip("允许外部请求触发模型加载。")
        self.auto_load.clicked.connect(self.save_settings)
        self.save_settings_btn = QPushButton("保存设置")
        self.save_settings_btn.setToolTip("保存本地 API 主机、端口、并发和超时设置。")
        self.save_settings_btn.clicked.connect(self.save_settings)
        self.copy_url_btn = QPushButton("复制 Base URL")
        self.copy_url_btn.setToolTip("复制给 OpenAI SDK 使用的 base_url。")
        self.copy_url_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.base_url.text()))
        settings.addWidget(QLabel("Base URL"), 0, 0)
        settings.addWidget(self.base_url, 0, 1, 1, 3)
        settings.addWidget(self.copy_url_btn, 0, 4)
        settings.addWidget(QLabel("主机"), 1, 0)
        settings.addWidget(self.host, 1, 1)
        settings.addWidget(QLabel("端口"), 1, 2)
        settings.addWidget(self.port, 1, 3)
        settings.addWidget(self.auto_load, 1, 4)
        settings.addWidget(QLabel("并发"), 2, 0)
        settings.addWidget(self.concurrent, 2, 1)
        settings.addWidget(QLabel("超时"), 2, 2)
        settings.addWidget(self.timeout, 2, 3)
        settings.addWidget(self.save_settings_btn, 2, 4)
        layout.addLayout(settings)

        body = QGridLayout()
        body.setColumnStretch(0, 1)
        body.setColumnStretch(1, 2)
        body.addWidget(self._keys_panel(), 0, 0)
        body.addWidget(self._models_panel(), 0, 1)
        body.addWidget(self._examples_panel(), 1, 0)
        body.addWidget(self._logs_panel(), 1, 1)
        body.addWidget(self._test_panel(), 2, 0, 1, 2)
        layout.addLayout(body, 1)

    def _keys_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        row.addWidget(QLabel("本地 API Key"))
        row.addStretch(1)
        self.create_key_btn = QPushButton("新建")
        self.create_key_btn.setToolTip("签发新的 mf- API key；密钥原文只显示一次。")
        self.create_key_btn.clicked.connect(self.create_key)
        row.addWidget(self.create_key_btn)
        self.revoke_key_btn = QPushButton("撤销")
        self.revoke_key_btn.setToolTip("撤销所选 key，撤销后不能恢复。")
        self.revoke_key_btn.clicked.connect(self.revoke_key)
        row.addWidget(self.revoke_key_btn)
        self.enable_key_btn = QPushButton("启用")
        self.enable_key_btn.setToolTip("重新启用所选未撤销的 API key。")
        self.enable_key_btn.clicked.connect(self.enable_key)
        row.addWidget(self.enable_key_btn)
        self.disable_key_btn = QPushButton("禁用")
        self.disable_key_btn.setToolTip("临时禁用所选 API key，但保留记录。")
        self.disable_key_btn.clicked.connect(self.disable_key)
        row.addWidget(self.disable_key_btn)
        self.delete_key_btn = QPushButton("删除")
        self.delete_key_btn.setToolTip("删除所选 API key；后端会先撤销该 key。")
        self.delete_key_btn.clicked.connect(self.delete_key)
        row.addWidget(self.delete_key_btn)
        layout.addLayout(row)
        self.key_table = QTableWidget(0, 5)
        self.key_table.setHorizontalHeaderLabels(["名称", "前缀", "范围", "状态", "最近使用"])
        self.key_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.key_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.key_table.setAccessibleName("本地 API Key 表")
        layout.addWidget(self.key_table, 1)
        return panel

    def _models_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        row.addWidget(QLabel("API 模型"))
        row.addStretch(1)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setToolTip("重新读取 API 服务状态、模型和日志。")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        self.alias_btn = QPushButton("设置别名")
        self.alias_btn.setToolTip("给所选模型设置外部 API 使用的模型 ID。")
        self.alias_btn.clicked.connect(self.set_alias)
        row.addWidget(self.alias_btn)
        self.load_btn = QPushButton("加载")
        self.load_btn.setToolTip("加载所选模型到本地运行后端。")
        self.load_btn.clicked.connect(self.load_model)
        row.addWidget(self.load_btn)
        self.unload_btn = QPushButton("卸载")
        self.unload_btn.setToolTip("卸载所选模型。")
        self.unload_btn.clicked.connect(self.unload_model)
        row.addWidget(self.unload_btn)
        layout.addLayout(row)
        self.model_table = QTableWidget(0, 8)
        self.model_table.setHorizontalHeaderLabels(["API ID", "名称", "格式", "能力", "端点", "运行", "兼容", "大小"])
        self.model_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.model_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.model_table.setAccessibleName("API 模型表")
        layout.addWidget(self.model_table, 1)
        return panel

    def _examples_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("调用示例"))
        self.examples = QPlainTextEdit()
        self.examples.setReadOnly(True)
        self.examples.setAccessibleName("本地 API 调用示例")
        layout.addWidget(self.examples, 1)
        return panel

    def _logs_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        row.addWidget(QLabel("请求日志"))
        row.addStretch(1)
        self.clear_logs_btn = QPushButton("清空")
        self.clear_logs_btn.setToolTip("清空当前账号的本地 API 请求日志。")
        self.clear_logs_btn.clicked.connect(self.clear_logs)
        row.addWidget(self.clear_logs_btn)
        layout.addLayout(row)
        self.logs = QTableWidget(0, 6)
        self.logs.setHorizontalHeaderLabels(["时间", "端点", "模型", "状态", "耗时", "错误"])
        self.logs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.logs.setAccessibleName("本地 API 请求日志")
        layout.addWidget(self.logs, 1)
        return panel

    def _test_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        row.addWidget(QLabel("API 测试台"))
        self.test_model = QComboBox()
        self.test_model.setAccessibleName("测试模型")
        row.addWidget(self.test_model, 1)
        self.test_stream = QCheckBox("流式")
        self.test_stream.setToolTip("测试流式协议可用性；当前控制台显示聚合后的文本结果。")
        row.addWidget(self.test_stream)
        self.send_test_btn = QPushButton("发送测试")
        self.send_test_btn.setToolTip("向所选模型发送一条轻量测试请求。")
        self.send_test_btn.clicked.connect(self.send_test)
        row.addWidget(self.send_test_btn)
        self.cancel_test_btn = QPushButton("取消")
        self.cancel_test_btn.setToolTip("取消当前测试请求，忽略迟到结果。")
        self.cancel_test_btn.clicked.connect(lambda: self.invalidate_api_requests("local-api-test"))
        row.addWidget(self.cancel_test_btn)
        layout.addLayout(row)
        self.test_input = QPlainTextEdit()
        self.test_input.setPlainText("hello")
        self.test_input.setAccessibleName("API 测试输入")
        self.test_input.setMaximumHeight(72)
        layout.addWidget(self.test_input)
        self.test_result = QPlainTextEdit()
        self.test_result.setReadOnly(True)
        self.test_result.setAccessibleName("API 测试结果")
        self.test_result.setMaximumHeight(120)
        layout.addWidget(self.test_result)
        return panel

    def refresh(self) -> None:
        self.status.set_state("正在读取状态…", "warning")
        if not hasattr(self.api, "local_api_status"):
            self._render({"status": {}, "keys": {"keys": []}, "models": [], "logs": []})
            return
        self._run_api(
            lambda: {
                "status": self.api.local_api_status(),
                "keys": self.api.list_local_api_keys(),
                "models": self.api.list_local_api_models(),
                "logs": self.api.list_local_api_logs(80),
            },
            self._render,
            self._failed,
            request_key="local-api-console",
        )

    def _render(self, data: dict) -> None:
        status = data.get("status") or {}
        self.base_url.setText(str(status.get("base_url") or f"{getattr(self.api, 'base_url', 'http://127.0.0.1:8000')}/v1"))
        self.host.setText(str(status.get("host") or "127.0.0.1"))
        self.port.setValue(int(status.get("port") or 8000))
        self.concurrent.setValue(int(status.get("max_concurrent_requests") or 4))
        self.timeout.setValue(int(status.get("request_timeout_seconds") or 120))
        self.auto_load.setChecked(bool(status.get("auto_load_models", True)))
        self.auto_load.setText("自动加载：开" if self.auto_load.isChecked() else "自动加载：关")
        loaded = int(status.get("loaded_models") or 0)
        enabled = bool(status.get("enabled", True))
        self.status.set_state(f"{'运行中' if enabled else '已停止'} · 已加载 {loaded} 个模型", "online" if enabled else "warning")
        self.start_btn.setEnabled(not enabled)
        self.stop_btn.setEnabled(enabled)
        self.keys = (data.get("keys") or {}).get("keys", []) if isinstance(data.get("keys"), dict) else []
        self.models = data.get("models") or []
        self._render_keys()
        self._render_models()
        self._render_logs(data.get("logs") or [])
        self._render_examples()

    def _render_keys(self) -> None:
        self.key_table.setRowCount(len(self.keys))
        for row, key in enumerate(self.keys):
            status = "已撤销" if key.get("revoked_at") else ("启用" if key.get("enabled", True) else "禁用")
            values = [key.get("name", "-"), key.get("prefix", "-"), ", ".join(key.get("scopes", [])), status, key.get("last_used_at") or "-"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(32, key.get("id"))
                self.key_table.setItem(row, col, item)

    def _render_models(self) -> None:
        self.model_table.setRowCount(len(self.models))
        self.test_model.blockSignals(True)
        self.test_model.clear()
        for row, model in enumerate(self.models):
            compat = model.get("compatibility") or {}
            values = [
                model.get("id", "-"),
                model.get("display_name") or model.get("name") or "-",
                model.get("format") or "-",
                ", ".join(model.get("api_capabilities") or model.get("capabilities") or []),
                ", ".join(model.get("endpoints") or []),
                "已加载" if model.get("loaded") else model.get("runtime_status", "idle"),
                compat.get("state", "unknown"),
                self._format_bytes(model.get("size_bytes")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(32, model.get("model_id"))
                item.setToolTip("\n".join(compat.get("reasons") or []))
                self.model_table.setItem(row, col, item)
            self.test_model.addItem(str(model.get("id") or model.get("name") or "model"), model.get("model_id"))
        self.test_model.blockSignals(False)

    def _render_logs(self, logs: list[dict]) -> None:
        self.logs.setRowCount(len(logs))
        for row, entry in enumerate(logs):
            values = [entry.get("created_at") or "-", entry.get("endpoint") or "-", entry.get("model") or "-", entry.get("status_code") or "-", f"{entry.get('duration_ms') or 0} ms", entry.get("error_code") or "-"]
            for col, value in enumerate(values):
                self.logs.setItem(row, col, QTableWidgetItem(str(value)))

    def _render_examples(self) -> None:
        model_id = self.models[0].get("id", "model-id") if self.models else "model-id"
        base = self.base_url.text() or "http://127.0.0.1:8000/v1"
        self.examples.setPlainText(
            "curl {base}/chat/completions \\\n  -H 'Authorization: Bearer mf-...' \\\n  -H 'Content-Type: application/json' \\\n  -d '{{\"model\":\"{model}\",\"messages\":[{{\"role\":\"user\",\"content\":\"hello\"}}]}}'\n\n"
            "from openai import OpenAI\nclient = OpenAI(base_url='{base}', api_key='mf-...')\n"
            "client.chat.completions.create(model='{model}', messages=[{{'role':'user','content':'hello'}}])\n\n"
            "import OpenAI from 'openai';\n"
            "const client = new OpenAI({{ baseURL: '{base}', apiKey: 'mf-...' }});\n"
            "await client.chat.completions.create({{ model: '{model}', messages: [{{ role: 'user', content: 'hello' }}] }});"
            .format(base=base, model=model_id)
        )

    @staticmethod
    def _format_bytes(value) -> str:
        try:
            size = float(value or 0)
        except (TypeError, ValueError):
            return "-"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return "-"

    def _selected_model_id(self) -> int | None:
        item = self.model_table.item(self.model_table.currentRow(), 0)
        value = item.data(32) if item else None
        return int(value) if value is not None else None

    def _selected_key_id(self) -> str | None:
        item = self.key_table.item(self.key_table.currentRow(), 0)
        value = item.data(32) if item else None
        return str(value) if value else None

    def create_key(self) -> None:
        name, ok = QInputDialog.getText(self, "新建本地 API Key", "名称", text="desktop")
        if not ok or not name.strip():
            return
        self._run_api(lambda: self.api.create_local_api_key(name.strip()), self._key_created, self._failed, request_key="local-api-create-key")

    def _key_created(self, result: dict) -> None:
        secret = result.get("secret")
        if secret:
            SecretKeyDialog(secret, self).exec()
        self.refresh()

    def revoke_key(self) -> None:
        key_id = self._selected_key_id()
        if not key_id:
            return
        if QMessageBox.question(self, "撤销 API Key", "撤销后该 key 立即失效，是否继续？") == QMessageBox.Yes:
            self._run_api(lambda: self.api.revoke_local_api_key(key_id), lambda _data: self.refresh(), self._failed, request_key="local-api-revoke-key")

    def enable_key(self) -> None:
        key_id = self._selected_key_id()
        if key_id:
            self._run_api(lambda: self.api.enable_local_api_key(key_id), lambda _data: self.refresh(), self._failed, request_key="local-api-enable-key")

    def disable_key(self) -> None:
        key_id = self._selected_key_id()
        if key_id:
            self._run_api(lambda: self.api.disable_local_api_key(key_id), lambda _data: self.refresh(), self._failed, request_key="local-api-disable-key")

    def delete_key(self) -> None:
        key_id = self._selected_key_id()
        if not key_id:
            return
        if QMessageBox.question(self, "删除 API Key", "删除前会立即撤销该 key，是否继续？") == QMessageBox.Yes:
            self._run_api(lambda: self.api.delete_local_api_key(key_id), lambda _data: self.refresh(), self._failed, request_key="local-api-delete-key")

    def set_alias(self) -> None:
        model_id = self._selected_model_id()
        if model_id is None:
            return
        alias, ok = QInputDialog.getText(self, "设置 API 模型 ID", "API ID / alias")
        if ok:
            self._run_api(lambda: self.api.update_local_api_model_alias(model_id, alias.strip() or None), lambda _data: self.refresh(), self._failed, request_key="local-api-alias")

    def load_model(self) -> None:
        model_id = self._selected_model_id()
        if model_id is not None:
            self._run_api(lambda: self.api.load_local_api_model(model_id), lambda _data: self.refresh(), self._failed, request_key="local-api-load")

    def unload_model(self) -> None:
        model_id = self._selected_model_id()
        if model_id is not None:
            self._run_api(lambda: self.api.unload_local_api_model(model_id), lambda _data: self.refresh(), self._failed, request_key="local-api-unload")

    def save_settings(self) -> None:
        self._run_api(
            lambda: self.api.update_local_api_settings({
                "host": self.host.text().strip() or "127.0.0.1",
                "port": self.port.value(),
                "max_concurrent_requests": self.concurrent.value(),
                "request_timeout_seconds": self.timeout.value(),
                "auto_load_models": self.auto_load.isChecked(),
            }),
            lambda data: self._render({"status": data, "keys": {"keys": self.keys}, "models": self.models, "logs": []}),
            self._failed,
            request_key="local-api-settings",
        )

    def clear_logs(self) -> None:
        self._run_api(lambda: self.api.clear_local_api_logs(), lambda _data: self.refresh(), self._failed, request_key="local-api-clear-logs")

    def send_test(self) -> None:
        model_id = self.test_model.currentData()
        if model_id is None:
            self.test_result.setPlainText("请选择一个模型。")
            return
        message = self.test_input.toPlainText().strip() or "hello"
        self.test_result.setPlainText("正在请求…")
        self._run_api(
            lambda: self.api.test_local_api_model(int(model_id), message),
            lambda data: self.test_result.setPlainText(str(data.get("content") or data)),
            lambda error: self.test_result.setPlainText(format_api_error(error)),
            request_key="local-api-test",
        )

    def start_service(self) -> None:
        self._run_api(lambda: self.api.start_local_api(), lambda _data: self.refresh(), self._failed, request_key="local-api-start")

    def stop_service(self) -> None:
        if QMessageBox.question(self, "停止本地 API", "停止后外部 OpenAI SDK 请求会被拒绝，是否继续？") == QMessageBox.Yes:
            self._run_api(lambda: self.api.stop_local_api(), lambda _data: self.refresh(), self._failed, request_key="local-api-stop")

    def restart_service(self) -> None:
        self._run_api(lambda: self.api.restart_local_api(), lambda _data: self.refresh(), self._failed, request_key="local-api-restart")

    def _failed(self, error: str) -> None:
        self.status.set_state("本地 API 加载失败", "error")
        QMessageBox.warning(self, "本地 API", format_api_error(error))

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)


class ProjectApiControlPage(QWidget, AsyncApiMixin):
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


class DeveloperApiPage(QWidget):
    """Developer API workspace: local inference API first, project API preserved."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.local_page = LocalInferenceApiPage(api)
        self.project_page = ProjectApiControlPage(api)
        self._api_state = {"suppressed": False}
        self._api_workers = set()
        for name in ("project_title", "key_list", "usage"):
            setattr(self, name, getattr(self.project_page, name))
        self.tabs.addTab(self.local_page, "本地推理 API")
        self.tabs.addTab(self.project_page, "项目 API")
        layout.addWidget(self.tabs)

    def refresh(self) -> None:
        self.local_page.refresh()
        self.project_page.refresh()

    def _render_catalog(self, data: dict) -> None:
        self.project_page._render_catalog(data)

    def _project_selected(self) -> None:
        self.project_page._project_selected()

    def _render_project_details(self, project_id: str, data: dict) -> None:
        self.project_page._render_project_details(project_id, data)

    def shutdown_async_api(self) -> None:
        self._api_state["suppressed"] = True
        self.local_page.shutdown_async_api()
        self.project_page.shutdown_async_api()

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
