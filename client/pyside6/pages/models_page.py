"""Unified local and remote model inventory for the desktop workspace."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFEmptyState, MFPanel, MFSection, MFStatusBadge
from components.provider_dialog import RemoteProviderDialog
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class ModelCard(MFPanel):
    def __init__(self, model: dict, on_chat, on_runtime, parent=None):
        super().__init__(parent)
        name = model.get("name") or model.get("model_id") or "Unnamed model"
        status = str(model.get("status") or "Ready")
        meta = " · ".join(str(value) for value in (model.get("parameters") or model.get("params"), model.get("quantization"), model.get("vram") or model.get("size")) if value) or "Local model"
        row = QHBoxLayout()
        title = QLabel(name); title.setStyleSheet("font-size: 15px; font-weight: 600;")
        row.addWidget(title); row.addStretch(1)
        badge = QLabel(status); badge.setProperty("status", "online" if status.lower() in {"ready", "running", "loaded", "available"} else "warning")
        row.addWidget(badge); self.layout.addLayout(row)
        detail = QLabel(meta); detail.setProperty("role", "muted"); self.layout.addWidget(detail)
        actions = QHBoxLayout()
        chat = QPushButton("对话"); chat.clicked.connect(on_chat)
        runtime = QPushButton("运行时"); runtime.clicked.connect(on_runtime)
        actions.addWidget(chat); actions.addWidget(runtime); actions.addStretch(1); self.layout.addLayout(actions)


class RemoteProviderCard(MFPanel):
    def __init__(self, provider: dict, on_chat, on_settings, parent=None):
        super().__init__(parent)
        row = QHBoxLayout()
        title = QLabel(provider["name"]); title.setStyleSheet("font-size: 15px; font-weight: 600;")
        row.addWidget(title); row.addStretch(1)
        badge = QLabel("远程 · " + ("已配置" if provider.get("key_configured") else "需要密钥"))
        badge.setProperty("status", "online" if provider.get("key_configured") else "warning")
        row.addWidget(badge); self.layout.addLayout(row)
        detail = QLabel(f"{provider['default_model']} · {provider['protocol'].replace('_', ' ')}\n{provider['base_url']}")
        detail.setProperty("role", "muted"); detail.setWordWrap(True); self.layout.addWidget(detail)
        actions = QHBoxLayout()
        chat = QPushButton("对话"); chat.clicked.connect(on_chat)
        manage = QPushButton("管理"); manage.clicked.connect(on_settings)
        actions.addWidget(chat); actions.addWidget(manage); actions.addStretch(1); self.layout.addLayout(actions)


class ModelsPage(QWidget, AsyncApiMixin):
    navigate_requested = Signal(str)

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api(); self.api = api
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(16)
        header = QHBoxLayout()
        header.addWidget(MFSection("模型管理", "模型")); header.addStretch(1)
        self.status = MFStatusBadge("正在检查模型", "warning"); header.addWidget(self.status)
        remote = QPushButton("管理远程模型"); remote.clicked.connect(self._manage_providers); header.addWidget(remote)
        root.addLayout(header)
        description = QLabel("在此统一管理本地模型和远程 OpenAI 兼容模型服务。")
        description.setProperty("role", "muted"); description.setWordWrap(True); root.addWidget(description)
        controls = QHBoxLayout()
        refresh = QPushButton("刷新"); refresh.clicked.connect(self.refresh)
        examples = QPushButton("示例"); examples.clicked.connect(lambda: open_examples("models", self))
        controls.addWidget(refresh); controls.addWidget(examples); controls.addStretch(1); root.addLayout(controls)
        self.empty = MFEmptyState("尚未添加模型", "添加本地模型或配置远程服务后，即可开始对话。")
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.cards = QWidget(); self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 0, 0); self.cards_layout.setSpacing(10); self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards)
        root.addWidget(self.empty, 1); root.addWidget(self.scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        self.status.set_state("正在检查模型", "warning")
        self._run_api(lambda: (self.api.list_models(), self.api.list_remote_providers()), self._render_models, self._failed)

    def _clear_cards(self) -> None:
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _render_models(self, result) -> None:
        models, providers = result
        models, providers = models or [], providers or []
        self._clear_cards()
        for model in models:
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, ModelCard(model, lambda: self.navigate_requested.emit("chat"), lambda: self.navigate_requested.emit("runtime")))
        for provider in providers:
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, RemoteProviderCard(provider, lambda: self.navigate_requested.emit("chat"), self._manage_providers))
        has_items = bool(models or providers)
        self.empty.setVisible(not has_items); self.scroll.setVisible(has_items)
        self.status.set_state(f"{len(models)} local · {len(providers)} remote", "online")

    def _manage_providers(self) -> None:
        dialog = RemoteProviderDialog(self.api, self)
        dialog.exec()
        self.refresh()

    def _failed(self, _error: str) -> None:
        self.status.set_state("Models unavailable", "error")
        self.empty.setVisible(True); self.scroll.setVisible(False)

    def closeEvent(self, event):
        self.shutdown_async_api(); super().closeEvent(event)
