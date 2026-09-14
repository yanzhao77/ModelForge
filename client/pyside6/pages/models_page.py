"""Unified local and remote model inventory for the desktop workspace."""

from __future__ import annotations

from functools import partial

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFEmptyState, MFPanel, MFSection, MFStatusBadge
from components.provider_dialog import RemoteProviderDialog
from i18n.ui_localizer import current, format_api_error, text
from pages.model_dialogs import DownloadDialog
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ModelCard(MFPanel):
    """A compact card for one locally available model asset."""

    #: Lifecycle status -> Chinese label + badge tone. The registry owns the
    #: vocabulary; the card only renders it.
    STATUS_LABELS = {
        "ready": ("就绪", "online"),
        "available": ("就绪", "online"),
        "installed": ("待就绪", "warning"),
        "downloading": ("下载中", "warning"),
        "installing": ("安装中", "warning"),
        "loading": ("加载中", "warning"),
        "loaded": ("已加载", "online"),
        "unloading": ("卸载中", "warning"),
        "load_failed": ("加载失败", "error"),
        "invalid": ("文件缺失", "error"),
        "discovered": ("已发现", "warning"),
    }

    def __init__(self, model: dict, on_chat, on_runtime, on_load=None, on_unload=None, on_default=None, parent=None):
        super().__init__(parent)
        name = model.get("display_name") or model.get("name") or model.get("model_id") or "未命名模型"
        runtime_status = str(model.get("runtime_status") or "idle")
        # A loaded runtime always wins over the persisted asset status.
        status_key = "loaded" if runtime_status == "loaded" else str(model.get("status") or "ready").lower()
        label, tone = self.STATUS_LABELS.get(status_key, (str(model.get("status") or "就绪"), "warning"))

        row = QHBoxLayout()
        title = QLabel(str(name))
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        row.addWidget(title)
        row.addStretch(1)
        badge = QLabel(label)
        badge.setProperty("status", tone)
        row.addWidget(badge)
        self.layout.addLayout(row)

        values = (
            model.get("format"),
            model.get("quant"),
            model.get("size") or _human_size(model.get("size_bytes")),
        )
        meta = " · ".join(str(value) for value in values if value) or "本地模型"
        detail = QLabel(meta)
        detail.setProperty("role", "muted")
        self.layout.addWidget(detail)

        capabilities = model.get("capabilities") or []
        caps = QLabel("能力：" + ("、".join(str(item) for item in capabilities) if capabilities else "未知"))
        caps.setProperty("role", "muted")
        self.layout.addWidget(caps)

        actions = QHBoxLayout()
        chat = QPushButton("开始对话")
        chat.clicked.connect(lambda: on_chat())
        chat.setEnabled(bool(model.get("ready")))
        actions.addWidget(chat)
        runtime = QPushButton("查看运行时")
        runtime.clicked.connect(lambda: on_runtime())
        actions.addWidget(runtime)
        if runtime_status == "loaded":
            unload = QPushButton("卸载")
            unload.clicked.connect(lambda: on_unload and on_unload())
            actions.addWidget(unload)
        else:
            load = QPushButton("加载")
            load.clicked.connect(lambda: on_load and on_load())
            actions.addWidget(load)
        if on_default is not None:
            default = QPushButton("设为默认")
            default.clicked.connect(lambda: on_default())
            actions.addWidget(default)
        actions.addStretch(1)
        self.layout.addLayout(actions)


def _human_size(size_bytes) -> str:
    """Render a byte count without depending on the backend's formatting."""
    try:
        amount = float(max(0, int(size_bytes)))
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{int(amount)} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _list_models(api) -> list[dict]:
    """Read the model inventory through the richest signature available."""
    try:
        return api.list_models()
    except TypeError:
        return api.list_models(capability=None)


class RemoteProviderCard(MFPanel):
    """A compact card for one saved OpenAI-compatible provider."""

    def __init__(self, provider: dict, on_chat, on_manage, parent=None):
        super().__init__(parent)
        row = QHBoxLayout()
        title = QLabel(provider["name"])
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        row.addWidget(title)
        row.addStretch(1)

        key_configured = bool(provider.get("key_configured"))
        verified = provider.get("verification_status") == "success"
        label_source = "远程 · 已验证" if key_configured and verified else "远程 · 需要验证" if key_configured else "远程 · 需要密钥"
        translator = current()
        locale = translator.locale if translator is not None else "zh_CN"
        label = text(label_source, locale)
        badge = QLabel(label)
        badge.setProperty("status", "online" if key_configured and verified else "warning")
        row.addWidget(badge)
        self.layout.addLayout(row)

        protocol = str(provider.get("protocol") or "responses").replace("_", " ")
        endpoint = str(provider.get("endpoint") or provider.get("base_url") or "")
        credential_source = "凭据状态：已配置" if provider.get("credential_state") == "configured" or key_configured else "凭据状态：未配置"
        detail = QLabel(
            f"{provider.get('default_model') or '未选择模型'} · {protocol}\n"
            f"{text('服务端点：{endpoint}', locale).format(endpoint=endpoint)}\n"
            f"{text(credential_source, locale)}"
        )
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        self.layout.addWidget(detail)

        actions = QHBoxLayout()
        chat = QPushButton("开始对话")
        # clicked(bool) must not leak its checked flag into the callback: the
        # caller passes a zero-argument callable that closes over the service.
        chat.clicked.connect(lambda: on_chat())
        manage = QPushButton("管理服务")
        manage.clicked.connect(on_manage)
        actions.addWidget(chat)
        actions.addWidget(manage)
        actions.addStretch(1)
        self.layout.addLayout(actions)


class ModelsPage(QWidget, AsyncApiMixin):
    """The single management surface for local models and remote providers."""

    navigate_requested = Signal(str)
    provider_chat_requested = Signal(object)

    def __init__(self, api, readiness_store=None, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.readiness_store = readiness_store

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(MFSection("模型管理", "模型"))
        header.addStretch(1)
        self.status = MFStatusBadge("正在检查模型", "warning")
        header.addWidget(self.status)
        remote = QPushButton("管理远程模型")
        remote.clicked.connect(self._manage_providers)
        header.addWidget(remote)
        root.addLayout(header)

        description = QLabel("在此统一管理本地模型和远程 OpenAI 兼容模型服务。")
        description.setProperty("role", "muted")
        description.setWordWrap(True)
        root.addWidget(description)

        controls = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        download = QPushButton("下载 GGUF 模型")
        download.clicked.connect(self._download_model)
        examples = QPushButton("查看示例")
        examples.clicked.connect(lambda: open_examples("models", self))
        controls.addWidget(refresh)
        controls.addWidget(download)
        controls.addWidget(examples)
        controls.addStretch(1)
        root.addLayout(controls)

        self.empty = MFEmptyState(
            "尚未添加模型", "添加本地模型或配置远程服务后，即可开始对话。"
        )
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards = QWidget()
        self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards)
        root.addWidget(self.empty, 1)
        root.addWidget(self.scroll, 1)
        self.refresh()
        if self.readiness_store:
            self.readiness_store.changed.connect(self._render_readiness)
            self.readiness_store.refresh()

    def refresh(self) -> None:
        self.status.set_state("正在检查模型", "warning")
        self._run_api(
            lambda: (_list_models(self.api), self.api.list_remote_providers()),
            self._render_models,
            self._failed,
            request_key="models.refresh",
        )
        if self.readiness_store:
            self.readiness_store.invalidate()
            self.readiness_store.refresh()

    def _clear_cards(self) -> None:
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render_models(self, result) -> None:
        models, providers = result
        models = models or []
        providers = providers or []
        self._clear_cards()

        for model in models:
            model_ref = model
            card = ModelCard(
                model,
                lambda model=model: self._open_chat_with_local_model(model),
                lambda: self.navigate_requested.emit("runtime"),
                on_load=lambda ref=model_ref: self._load_model(ref),
                on_unload=lambda ref=model_ref: self._unload_model(ref),
                on_default=lambda ref=model_ref: self._set_default(ref),
            )
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        for provider in providers:
            card = RemoteProviderCard(
                provider,
                partial(self.provider_chat_requested.emit, provider.get("id")),
                self._manage_providers,
            )
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        has_items = bool(models or providers)
        self.empty.setVisible(not has_items)
        self.scroll.setVisible(has_items)
        self.status.set_state(
            f"{len(models)} 个本地 · {len(providers)} 个远程", "online"
        )

    def _load_model(self, model: dict) -> None:
        model_id = model.get("model_id") or model.get("id")
        if model_id is None:
            return
        self.status.set_state("正在加载模型…", "warning")
        self._run_api(
            lambda: self.api.load_model(model_id),
            lambda _result: self._operation_done("模型已加载"),
            self._operation_failed,
            request_key="models.load",
        )

    def _unload_model(self, model: dict) -> None:
        model_id = model.get("model_id") or model.get("id")
        if model_id is None:
            return
        self.status.set_state("正在卸载模型…", "warning")
        self._run_api(
            lambda: self.api.unload_model(model_id),
            lambda _result: self._operation_done("模型已卸载"),
            self._operation_failed,
            request_key="models.unload",
        )

    def _set_default(self, model: dict) -> None:
        model_id = model.get("model_id") or model.get("id")
        if model_id is None:
            return
        self._run_api(
            lambda: self.api.set_model_default(model_id),
            lambda _result: self._operation_done("已设为默认模型"),
            self._operation_failed,
            request_key="models.default",
        )

    def _operation_done(self, message: str) -> None:
        if self.readiness_store:
            self.readiness_store.invalidate()
        self.refresh()
        self.status.set_state(message, "online")

    def _operation_failed(self, error: str) -> None:
        from i18n.ui_localizer import format_api_error

        self.status.set_state(f"操作失败：{format_api_error(error)}", "error")

    def _render_readiness(self, snapshot: dict) -> None:
        level = snapshot.get("level")
        if level == "READY":
            targets = snapshot.get("targets") or []
            self.status.set_state(f"模型就绪 · {len(targets)} 个可用", "online")
        elif level == "DEGRADED":
            self.status.set_state("模型配置需要处理", "warning")
        elif level == "SERVICE_UNAVAILABLE":
            self.status.set_state("模型服务不可用", "error")
        else:
            self.status.set_state("尚未配置可用模型", "warning")

    def _open_chat_with_local_model(self, model: dict) -> None:
        model_ref = model.get("id")
        if model_ref is None:
            QMessageBox.warning(self, "无法选择模型", "此本地模型缺少可用的模型 ID，请刷新模型列表后重试。")
            return
        self._select_default_and_open_chat("local", str(model_ref))

    def _open_chat_with_provider(self, provider: dict) -> None:
        provider_id = provider.get("id")
        model_name = str(provider.get("default_model") or "").strip()
        if provider_id is None or not model_name:
            QMessageBox.warning(self, "无法选择模型", "此远程模型服务缺少 provider ID 或默认模型。")
            return
        self._select_default_and_open_chat("remote", model_name, provider_id=int(provider_id))

    def _select_default_and_open_chat(
        self, kind: str, model_ref: str, provider_id: int | None = None
    ) -> None:
        self.status.set_state("正在选择对话模型…", "warning")
        self._run_api(
            lambda: self.api.set_default_model(kind, model_ref, provider_id),
            self._default_selected,
            self._default_failed,
            request_key="models.default.select",
        )

    def _default_selected(self, snapshot: dict) -> None:
        if self.readiness_store:
            self.readiness_store.apply_snapshot(snapshot)
        self._render_readiness(snapshot)
        self.navigate_requested.emit("chat")

    def _default_failed(self, error: str) -> None:
        self.status.set_state("模型选择失败", "error")
        QMessageBox.warning(self, "无法使用该模型", format_api_error(error))

    def _manage_providers(self) -> None:
        dialog = RemoteProviderDialog(self.api, self)
        dialog.exec()
        self.refresh()

    def _download_model(self) -> None:
        dialog = DownloadDialog(self.api, self)
        dialog.exec()
        self.refresh()

    def _failed(self, _error: str) -> None:
        self.status.set_state("模型服务不可用", "error")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
