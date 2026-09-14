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

# Known endpoints offered by the 服务预设 selector. "custom" keeps whatever the
# user typed, so every other entry must describe a complete, working target.
_PROVIDER_PRESETS: tuple[dict[str, str], ...] = (
    {
        "key": "zhipu",
        "label": "智谱 AI（GLM-4.7）",
        "name": "智谱 AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "protocol": "responses",
        # 模型编码为小写（glm-4.7 / glm-4.7-flash / glm-5.3-flash…）；此前的
        # GLM-4.5-Flash 是文档里的展示名，验证连接会返回真实编码。
        "model": "glm-4.7",
        "api_key": "",
        "hint": "",
    },
    {
        "key": "openai",
        "label": "OpenAI",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "protocol": "responses",
        "model": "gpt-4.1-mini",
        "api_key": "",
        "hint": "",
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "protocol": "chat_completions",
        "model": "deepseek-flash",
        "api_key": "",
        "hint": "DeepSeek 官方 OpenAI 兼容接口：默认使用 Chat Completions 协议，"
        "输入密钥后获取模型列表，再选择一个模型保存为默认。密钥在 platform.deepseek.com 创建。",
    },
    {
        "key": "ccswitch",
        "label": "CC Switch 本地路由（127.0.0.1:15721）",
        "name": "CC Switch",
        "base_url": "http://127.0.0.1:15721/v1",
        "protocol": "responses",
        "model": "",
        "api_key": "cc-switch",
        "hint": "先在 CC Switch「设置 → 路由」中启动本地路由（默认 127.0.0.1:15721）；"
        "输入占位密钥后获取模型列表，再选择该路由当前供应商支持的模型。"
        "本地路由会用自己的凭据替换这里的占位密钥。",
    },
    {
        "key": "custom",
        "label": "自定义 OpenAI 兼容服务",
        "name": "",
        "base_url": "",
        "protocol": "",
        "model": "",
        "api_key": "",
        "hint": "",
    },
)


class RemoteProviderDialog(QDialog, AsyncApiMixin):
    def __init__(self, api, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.providers: list[dict] = []
        self._pending_notice = ""
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
            "预设已包含智谱、OpenAI、DeepSeek 与 CC Switch 本地路由。"
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        right.addWidget(note)
        form = QFormLayout()
        self.preset = QComboBox()
        for preset in _PROVIDER_PRESETS:
            self.preset.addItem(preset["label"], preset["key"])
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.name = QLineEdit()
        self.base_url = QLineEdit()
        self.protocol = QComboBox()
        self.protocol.addItem("Responses API（推荐）", "responses")
        self.protocol.addItem("Chat Completions API", "chat_completions")
        self.model = QLineEdit()
        self.available_models = QComboBox()
        self.available_models.setEnabled(False)
        self.available_models.activated.connect(self._available_model_selected)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("新建服务时必填；编辑时留空可保留已有密钥")
        form.addRow("服务预设", self.preset)
        form.addRow("名称", self.name)
        form.addRow("服务地址", self.base_url)
        form.addRow("协议", self.protocol)
        form.addRow("默认模型", self.model)
        form.addRow("可用模型", self.available_models)
        form.addRow("API 密钥", self.api_key)
        right.addLayout(form)
        self.state = QLabel("")
        self.state.setWordWrap(True)
        right.addWidget(self.state)
        # The preset list is the single source for the initial form values, so a
        # preset edit cannot leave the pre-filled fields behind.
        self._preset_changed(self.preset.currentIndex())
        actions = QHBoxLayout()
        self.save_btn = QPushButton("保存默认模型")
        self.save_btn.setProperty("accent", True)
        self.save_btn.clicked.connect(self.save)
        self.verify_btn = QPushButton("获取模型列表")
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
        self._pending_notice = ""
        self.preset.setCurrentIndex(0)
        # setCurrentIndex() is a no-op when the preset is already selected, so
        # the fields are reset explicitly instead of relying on the signal.
        self._preset_changed(0)
        self.api_key.clear()
        self._set_available_models([])
        self.state.setText(self._tr("新建模型服务配置。点击获取模型列表前不会发起网络请求。"))

    def _preset(self) -> dict | None:
        key = self.preset.currentData()
        return next((item for item in _PROVIDER_PRESETS if item["key"] == key), None)

    def _preset_changed(self, _index: int) -> None:
        """Prefill every field a preset can answer, leaving 自定义 untouched."""
        preset = self._preset()
        if preset is None or preset["key"] == "custom":
            return
        self.name.setText(preset["name"])
        self.base_url.setText(preset["base_url"])
        self.protocol.setCurrentIndex(max(self.protocol.findData(preset["protocol"]), 0))
        self.model.setText(preset["model"])
        # A preset switch also switches services, so a key typed for the
        # previous one must not be saved against the new one.
        self.api_key.clear()
        if preset["api_key"]:
            self.api_key.setText(preset["api_key"])
        self._set_available_models([])
        if preset["hint"]:
            self.state.setText(self._tr(preset["hint"]))

    def _set_available_models(self, models: list[str], selected: str = "") -> None:
        self.available_models.blockSignals(True)
        self.available_models.clear()
        if models:
            sources = ["请选择模型…", *models]
            self.available_models.addItem("请选择模型…", "")
            for model in models:
                self.available_models.addItem(model, model)
            index = self.available_models.findData(selected)
            self.available_models.setCurrentIndex(index if index >= 0 else 0)
            self.available_models.setEnabled(True)
        else:
            sources = ["保存密钥后获取模型列表"]
            self.available_models.addItem("保存密钥后获取模型列表", "")
            self.available_models.setEnabled(False)
        self.available_models.setProperty("mf_i18n_items", sources)
        self.available_models.blockSignals(False)

    def _available_model_selected(self, _index: int) -> None:
        model = str(self.available_models.currentData() or "").strip()
        if model:
            self.model.setText(model)
            self.state.setText(self._tr("已选择默认模型：{model}", model=model))

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
            # Selecting a row rewrites the state text, so a notice raised by the
            # action that triggered this refresh is appended afterwards.
            self.list.setCurrentRow(0)
        if self._pending_notice:
            self.state.setText(f"{self.state.text()}\n{self._pending_notice}")
            self._pending_notice = ""

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
        self._set_available_models(
            [str(item) for item in provider.get("verified_models", [])],
            str(provider.get("default_model") or ""),
        )
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
        if not all((name, url)):
            QMessageBox.warning(
                self, "信息不完整", "名称和 Base URL 为必填项。"
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
        name = self.name.text().strip()
        url = self.base_url.text().strip()
        key = self.api_key.text().strip()
        has_saved_key = bool(
            provider
            and (
                provider.get("credential_state") == "configured"
                or provider.get("key_configured")
            )
        )
        if not all((name, url)) or not (key or has_saved_key):
            QMessageBox.information(
                self, "请选择模型服务", "请先填写名称、Base URL 和 API 密钥。"
            )
            return
        if QMessageBox.question(
            self,
            self._tr("验证模型服务"),
            self._tr("验证将访问此服务并请求模型列表，是否继续？"),
        ) != QMessageBox.Yes:
            return
        self.state.setText("正在保存加密的模型服务配置…")
        self._run_api(
            lambda: self.api.save_remote_provider(
                self.name.text().strip(),
                self.base_url.text().strip(),
                self.protocol.currentData(),
                self.model.text().strip(),
                self.api_key.text().strip() or None,
            ),
            self._saved_then_verify,
            self._failed,
        )

    def _verify_provider(self, provider_id: int) -> None:
        self.state.setText(self._tr("正在验证连接并获取模型列表…"))
        self._run_api(
            lambda: self.api.verify_remote_provider(provider_id, confirm=True),
            self._verified,
            self._failed,
        )

    def _saved_then_verify(self, provider: dict) -> None:
        provider_id = provider.get("id")
        if provider_id is None:
            self._failed("REMOTE_PROVIDER_RESPONSE_INVALID")
            return
        self._verify_provider(int(provider_id))

    def _verified(self, result: dict) -> None:
        models = [str(item) for item in result.get("models", [])]
        provider = self.current() or {}
        self._set_available_models(
            models, str(provider.get("default_model") or self.model.text().strip())
        )
        notice = self._tr("连接验证成功，发现 {count} 个模型。", count=len(models))
        default_model = str(provider.get("default_model") or "")
        if models and not default_model:
            notice = self._tr("连接验证成功，发现 {count} 个模型。请选择一个模型并保存为默认模型。", count=len(models))
        elif models and default_model and default_model not in models:
            # A display name such as "GLM-4.7-Flash" is not a model code: the
            # service verifies, but readiness and agents never treat it as a
            # usable target. Say so instead of reporting a plain success.
            notice = self._tr(
                "连接验证成功，但默认模型 {model} 不在服务返回的模型列表中；"
                "请改用列表中的模型编码（例如 {preview}），否则该服务不会被视为可用。",
                model=default_model,
                preview="、".join(models[:5]),
            )
        self.refresh()
        # refresh() reports "正在加载…" and the reloaded list rewrites the state
        # again, so the notice is shown now and re-appended after that render.
        self._pending_notice = notice
        self.state.setText(notice)

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
