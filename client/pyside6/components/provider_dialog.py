"""Desktop management dialog for user-scoped OpenAI-compatible providers."""

from __future__ import annotations

from components.api_worker import AsyncApiMixin
from i18n.ui_localizer import current, localize_tree, text
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class RemoteProviderDialog(QDialog, AsyncApiMixin):
    def __init__(self, api, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.providers: list[dict] = []
        self.setWindowTitle("远程模型服务")
        self.resize(720, 470)
        root = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setMinimumWidth(210)
        self.list.currentItemChanged.connect(self._selected)
        root.addWidget(self.list, 1)
        right = QVBoxLayout()
        title = QLabel("OpenAI 兼容模型服务")
        title.setProperty("role", "pageTitle")
        right.addWidget(title)
        note = QLabel(
            "密钥将在本机加密保存，保存后不会再次显示。默认使用 Responses API；仅当服务不支持 Responses 时才切换到 Chat Completions API。"
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        right.addWidget(note)
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem("智谱 AI（GLM-4.5-Flash）", "zhipu")
        self.preset.addItem("OpenAI", "openai")
        self.preset.addItem("OrcaRouter", "orcarouter")
        self.preset.addItem("自定义 OpenAI 兼容服务", "custom")
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.name = QLineEdit()
        self.base_url = QLineEdit("https://open.bigmodel.cn/api/paas/v4")
        self.protocol = QComboBox()
        self.protocol.addItem("Responses API（推荐）", "responses")
        self.protocol.addItem("Chat Completions API", "chat_completions")
        self.model = QLineEdit()
        self.model.setText("GLM-4.5-Flash")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("新建服务时必填；编辑时留空可保留已有密钥")
        form.addRow("服务预设", self.preset)
        form.addRow("名称", self.name)
        form.addRow("服务地址", self.base_url)
        form.addRow("协议", self.protocol)
        form.addRow("默认模型", self.model)
        form.addRow("API 密钥", self.api_key)
        right.addLayout(form)
        self.state = QLabel("")
        self.state.setWordWrap(True)
        right.addWidget(self.state)
        actions = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setProperty("accent", True)
        self.save_btn.clicked.connect(self.save)
        self.verify_btn = QPushButton("验证连接")
        self.verify_btn.clicked.connect(self.verify)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self.delete)
        self.new_btn = QPushButton("新建")
        self.new_btn.clicked.connect(self.clear)
        actions.addWidget(self.new_btn)
        actions.addWidget(self.delete_btn)
        actions.addStretch(1)
        actions.addWidget(self.verify_btn)
        actions.addWidget(self.save_btn)
        right.addLayout(actions)
        root.addLayout(right, 2)
        localize_tree(self)
        self.refresh()

    @staticmethod
    def _tr(source: str, **values) -> str:
        translator = current()
        locale = translator.locale if translator is not None else "zh_CN"
        return text(source, locale).format(**values)

    def current(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def clear(self) -> None:
        self.list.clearSelection()
        self.preset.setCurrentIndex(0)
        self.name.setText("智谱 AI")
        self.base_url.setText("https://open.bigmodel.cn/api/paas/v4")
        self.protocol.setCurrentIndex(0)
        self.model.setText("GLM-4.5-Flash")
        self.api_key.clear()
        self.state.setText(self._tr("新建模型服务配置。点击验证连接前不会发起网络请求。"))

    def _preset_changed(self, _index: int) -> None:
        preset = self.preset.currentData()
        if preset == "zhipu":
            self.name.setText("智谱 AI")
            self.base_url.setText("https://open.bigmodel.cn/api/paas/v4")
            self.model.setText("GLM-4.5-Flash")
            self.protocol.setCurrentIndex(0)
        elif preset == "openai":
            self.name.setText("OpenAI")
            self.base_url.setText("https://api.openai.com/v1")
            self.model.setText("gpt-4.1-mini")
            self.protocol.setCurrentIndex(0)
        elif preset == "orcarouter":
            self.name.setText("OrcaRouter")
            self.base_url.setText("https://api.orcarouter.ai/v1")
            self.model.setText("orcarouter/auto")
            self.protocol.setCurrentIndex(0)

    def refresh(self) -> None:
        self.state.setText(self._tr("正在加载模型服务…"))
        self._run_api(self.api.list_remote_providers, self._render, self._failed)

    def _render(self, providers: list[dict]) -> None:
        self.providers = providers
        self.list.clear()
        for provider in providers:
            item = QListWidgetItem(f"{provider['name']}\n{provider['default_model']}")
            item.setData(Qt.UserRole, provider)
            self.list.addItem(item)
        self.state.setText(self._tr("选择已有模型服务，或新建一个配置。"))
        if providers:
            self.list.setCurrentRow(0)

    def _selected(self, item) -> None:
        provider = item.data(Qt.UserRole) if item else None
        if not provider:
            return
        self.name.setText(provider["name"])
        self.preset.setCurrentIndex(self.preset.findData("custom"))
        self.base_url.setText(provider["base_url"])
        self.protocol.setCurrentIndex(
            max(self.protocol.findData(provider["protocol"]), 0)
        )
        self.model.setText(provider["default_model"])
        self.api_key.clear()
        status = provider.get("verification_status", "unknown")
        status_text = {
            "success": self._tr("连接状态：已验证"),
            "failed": self._tr("连接状态：验证失败（{code}）", code=provider.get("verification_error_code") or "UNKNOWN"),
        }.get(status, self._tr("连接状态：未验证"))
        credential_text = self._tr(
            "凭据状态：已配置" if provider.get("credential_state") == "configured" or provider.get("key_configured") else "凭据状态：未配置"
        )
        endpoint = str(provider.get("endpoint") or provider.get("base_url") or "")
        self.state.setText(
            f"{self._tr('服务端点：{endpoint}', endpoint=endpoint)}\n{credential_text}；{status_text}"
        )

    def save(self) -> None:
        name, url, protocol, model, key = (
            self.name.text().strip(),
            self.base_url.text().strip(),
            self.protocol.currentData(),
            self.model.text().strip(),
            self.api_key.text().strip(),
        )
        if not all((name, url, model)):
            QMessageBox.warning(
                self, "信息不完整", "名称、Base URL 和默认模型均为必填项。"
            )
            return
        self.state.setText("正在保存加密的模型服务配置…")
        self._run_api(
            lambda: self.api.save_remote_provider(
                name, url, protocol, model, key or None
            ),
            lambda _: self.refresh(),
            self._failed,
        )

    def verify(self) -> None:
        provider = self.current()
        if not provider:
            QMessageBox.information(
                self, "请选择模型服务", "请先保存模型服务，再验证连接。"
            )
            return
        if QMessageBox.question(
            self,
            self._tr("验证模型服务"),
            self._tr("验证将访问此服务并请求模型列表，是否继续？"),
        ) != QMessageBox.Yes:
            return
        self.state.setText(self._tr("正在验证连接并获取模型列表…"))
        self._run_api(
            lambda: self.api.verify_remote_provider(provider["id"], confirm=True),
            self._verified,
            self._failed,
        )

    def _verified(self, result: dict) -> None:
        models = result.get("models", [])
        self.state.setText(self._tr("连接验证成功，发现 {count} 个模型。", count=len(models)))
        self.refresh()

    def delete(self) -> None:
        provider = self.current()
        if not provider:
            return
        if (
            QMessageBox.question(self, "删除模型服务", "删除此模型服务及其加密密钥？")
            != QMessageBox.Yes
        ):
            return
        self._run_api(
            lambda: self.api.delete_remote_provider(provider["id"]),
            lambda _: self.refresh(),
            self._failed,
        )

    def _failed(self, error) -> None:
        code = getattr(error, "code", None) or "REMOTE_PROVIDER_REQUEST_FAILED"
        correlation = getattr(error, "correlation_id", None) or "-"
        self.state.setText(
            self._tr("远程模型服务请求未完成（{code}）。关联标识：{correlation}", code=code, correlation=correlation)
        )

    def closeEvent(self, event):
        self.shutdown_async_api()
        super().closeEvent(event)
