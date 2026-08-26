"""Unified local and remote model inventory for the desktop workspace."""

from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFEmptyState, MFPanel, MFSection, MFStatusBadge
from components.provider_dialog import RemoteProviderDialog
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ModelCard(MFPanel):
    """A compact card for one locally available model."""

    def __init__(self, model: dict, on_chat, on_runtime, parent=None):
        super().__init__(parent)
        name = model.get("name") or model.get("model_id") or "未命名模型"
        status = str(model.get("status") or "就绪")
        values = (
            model.get("parameters") or model.get("params"),
            model.get("quantization"),
            model.get("vram") or model.get("size"),
        )
        meta = " · ".join(str(value) for value in values if value) or "本地模型"

        row = QHBoxLayout()
        title = QLabel(name)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        row.addWidget(title)
        row.addStretch(1)

        badge = QLabel(status)
        ready_states = {"ready", "running", "loaded", "available", "就绪", "运行中"}
        badge.setProperty(
            "status", "online" if status.lower() in ready_states else "warning"
        )
        row.addWidget(badge)
        self.layout.addLayout(row)

        detail = QLabel(meta)
        detail.setProperty("role", "muted")
        self.layout.addWidget(detail)

        actions = QHBoxLayout()
        chat = QPushButton("开始对话")
        chat.clicked.connect(on_chat)
        runtime = QPushButton("查看运行时")
        runtime.clicked.connect(on_runtime)
        actions.addWidget(chat)
        actions.addWidget(runtime)
        actions.addStretch(1)
        self.layout.addLayout(actions)


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
        label = "远程 · 已验证" if key_configured and verified else "远程 · 需要验证" if key_configured else "远程 · 需要密钥"
        badge = QLabel(label)
        badge.setProperty("status", "online" if key_configured and verified else "warning")
        row.addWidget(badge)
        self.layout.addLayout(row)

        protocol = str(provider.get("protocol") or "responses").replace("_", " ")
        detail = QLabel(
            f"{provider.get('default_model') or '未选择模型'} · {protocol}\n"
            f"{provider.get('base_url') or ''}"
        )
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        self.layout.addWidget(detail)

        actions = QHBoxLayout()
        chat = QPushButton("开始对话")
        chat.clicked.connect(on_chat)
        manage = QPushButton("管理服务")
        manage.clicked.connect(on_manage)
        actions.addWidget(chat)
        actions.addWidget(manage)
        actions.addStretch(1)
        self.layout.addLayout(actions)


class ModelsPage(QWidget, AsyncApiMixin):
    """The single management surface for local models and remote providers."""

    navigate_requested = Signal(str)

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
        examples = QPushButton("查看示例")
        examples.clicked.connect(lambda: open_examples("models", self))
        controls.addWidget(refresh)
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
            lambda: (self.api.list_models(), self.api.list_remote_providers()),
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
            card = ModelCard(
                model,
                lambda: self.navigate_requested.emit("chat"),
                lambda: self.navigate_requested.emit("runtime"),
            )
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        for provider in providers:
            card = RemoteProviderCard(
                provider,
                lambda: self.navigate_requested.emit("chat"),
                self._manage_providers,
            )
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        has_items = bool(models or providers)
        self.empty.setVisible(not has_items)
        self.scroll.setVisible(has_items)
        self.status.set_state(
            f"{len(models)} 个本地 · {len(providers)} 个远程", "online"
        )

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

    def _manage_providers(self) -> None:
        dialog = RemoteProviderDialog(self.api, self)
        dialog.exec()
        self.refresh()

    def _failed(self, _error: str) -> None:
        self.status.set_state("模型服务不可用", "error")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
