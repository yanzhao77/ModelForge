"""Resumable, non-destructive first-use model configuration flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from components.provider_dialog import RemoteProviderDialog
from i18n.ui_localizer import localize_tree
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class OnboardingWizard(QDialog):
    """Guide a user to a model configuration without creating background work."""

    navigate_requested = Signal(str)

    def __init__(self, api, readiness_store, recovery, user_key: str, translator=None, parent=None):
        super().__init__(parent)
        self.api = api
        self.readiness_store = readiness_store
        self.recovery = recovery
        self.user_key = user_key
        self.translator = translator
        self.snapshot: dict = readiness_store.snapshot or {}
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setWindowTitle("开始配置 ModelForge")
        root = QVBoxLayout(self)
        root.setSpacing(14)
        self.title = QLabel("准备你的第一个模型")
        self.title.setProperty("role", "pageTitle")
        self.detail = QLabel()
        self.detail.setProperty("role", "muted")
        self.detail.setWordWrap(True)
        root.addWidget(self.title)
        root.addWidget(self.detail)

        actions = QHBoxLayout()
        self.local = QPushButton("使用已有本地模型")
        self.remote = QPushButton("配置远程模型服务")
        self.refresh = QPushButton("重新检查")
        self.continue_btn = QPushButton("开始对话")
        self.continue_btn.setProperty("accent", True)
        self.local.clicked.connect(self._open_local_models)
        self.remote.clicked.connect(self._open_remote_provider)
        self.refresh.clicked.connect(self._refresh)
        self.continue_btn.clicked.connect(self._continue)
        actions.addWidget(self.local)
        actions.addWidget(self.remote)
        actions.addStretch(1)
        actions.addWidget(self.refresh)
        actions.addWidget(self.continue_btn)
        root.addLayout(actions)

        self.later = QPushButton("稍后处理")
        self.later.clicked.connect(self._dismiss)
        root.addWidget(self.later)
        self.readiness_store.changed.connect(self._render)
        self.readiness_store.failed.connect(self._failed)
        if self.translator:
            self.translator.changed.connect(lambda _locale: self._retranslate())
        self._render(self.snapshot)
        localize_tree(self, self.translator)

    def _render(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        level = snapshot.get("level", "SETUP_REQUIRED")
        ready = level == "READY"
        degraded = level == "DEGRADED"
        self.title.setText("模型已准备完成" if ready else "修复模型配置" if degraded else "准备你的第一个模型")
        if ready:
            default = snapshot.get("default_target") or {}
            target = default.get("model_name") or "可用模型"
            self.detail.setText(f"{target} 已可用于对话。你可以立即开始，也可以稍后在模型工作区切换默认模型。")
        elif degraded:
            self.detail.setText("已发现模型或远程服务，但仍需完成密钥配置或连接验证。请选择修复路径。")
        else:
            self.detail.setText("先选择一个已有本地模型，或显式配置并验证远程 OpenAI 兼容模型服务。不会自动下载模型或创建任务。")
        self.continue_btn.setVisible(ready)
        self.local.setVisible(not ready)
        self.remote.setVisible(not ready)
        self.later.setText("完成" if ready else "稍后处理")
        self._retranslate()

    def _retranslate(self) -> None:
        localize_tree(self, self.translator)

    def _failed(self, _error: str) -> None:
        self.title.setText("暂时无法检查模型")
        self.detail.setText("请确认 ModelForge 服务正在运行，然后点击重新检查。")
        self._retranslate()

    def _refresh(self) -> None:
        self.readiness_store.invalidate()
        self.readiness_store.refresh(force=True)

    def _open_local_models(self) -> None:
        self._save_progress("local")
        self.navigate_requested.emit("models")
        self.accept()

    def _open_remote_provider(self) -> None:
        self._save_progress("remote")
        dialog = RemoteProviderDialog(self.api, self)
        dialog.exec()
        self._refresh()

    def _continue(self) -> None:
        self._save_progress("complete", dismissed=False)
        self.navigate_requested.emit("chat")
        self.accept()

    def _dismiss(self) -> None:
        self._save_progress("complete" if self.snapshot.get("level") == "READY" else "dismissed")
        self.reject()

    def _save_progress(self, step: str, dismissed: bool = True) -> None:
        self.recovery.save_onboarding_state(
            self.user_key,
            {
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "dismissed_at": datetime.now(timezone.utc).isoformat() if dismissed else None,
                "last_step": step,
                "last_path": step if step in {"local", "remote"} else None,
                "last_seen_readiness_level": self.snapshot.get("level"),
            },
        )


class OnboardingCoordinator(QObject):
    """Open the wizard once per schema version while respecting local dismissal."""

    SCHEMA_VERSION = 1

    def __init__(self, api, readiness_store, recovery, user_key: str, translator=None, parent=None):
        super().__init__(parent)
        self.api = api
        self.readiness_store = readiness_store
        self.recovery = recovery
        self.user_key = user_key
        self.translator = translator
        self._shown = False
        self.readiness_store.changed.connect(self._readiness_changed)

    def open_manual(self) -> None:
        self._open()

    def _readiness_changed(self, snapshot: dict) -> None:
        if self._shown or snapshot.get("level") == "READY" or self._dismissed_recently():
            return
        self._open()

    def _open(self) -> None:
        self._shown = True
        wizard = OnboardingWizard(
            self.api,
            self.readiness_store,
            self.recovery,
            self.user_key,
            self.translator,
            self.parent(),
        )
        wizard.navigate_requested.connect(self.parent()._navigate_to)
        wizard.exec()

    def _dismissed_recently(self) -> bool:
        state = self.recovery.onboarding_state(self.user_key)
        if state.get("schema_version") != self.SCHEMA_VERSION:
            return False
        dismissed_at = state.get("dismissed_at")
        if not dismissed_at:
            return False
        try:
            then = datetime.fromisoformat(dismissed_at)
        except ValueError:
            return False
        return datetime.now(timezone.utc) - then < timedelta(days=7)
