from __future__ import annotations

import contextlib
import os
import tempfile
import uuid

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFPageHeader, MFStatusBadge
from i18n.ui_localizer import current, format_api_error, format_text, localize_tree
from i18n.ui_localizer import text as localize_text
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _list_chat_models(api) -> list[dict]:
    """Registry query used by the selector; tolerates narrow test doubles."""
    try:
        return api.list_models(capability="CHAT")
    except TypeError:
        try:
            return api.list_models()
        except Exception:
            return []
    except Exception:
        return []


def _qtext_cursor_end(cursor_type=QTextCursor):
    end = getattr(cursor_type, "End", None)
    if end is not None:
        return end
    return cursor_type.MoveOperation.End


_QTEXT_CURSOR_END = _qtext_cursor_end()


class StreamWorker(QThread):
    """Reads a chat stream outside the GUI event loop."""

    delta = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, api, model, messages, session_id, provider_id=None, model_id=None):
        super().__init__()
        self.api, self.model, self.messages = api, model, messages
        self.session_id, self.provider_id = session_id, provider_id
        self.model_id = model_id

    def run(self):
        full = ""
        try:
            for event in self.api.stream_chat(
                self.model, self.messages, self.session_id, self.provider_id, self.model_id,
                cancel_event=self.interruption_requested,
            ):
                if self.isInterruptionRequested():
                    return
                kind = event.get("type")
                if kind == "delta":
                    content = str(event.get("data", ""))
                    full += content
                    self.delta.emit(content)
                elif kind == "done":
                    self.done.emit(full)
                    return
                elif kind == "error":
                    self.failed.emit(self._format_error(event.get("data")))
                    return
            if not self.isInterruptionRequested():
                self.done.emit(full)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(format_api_error(exc))

    def interruption_requested(self) -> bool:
        return self.isInterruptionRequested()

    @staticmethod
    def _format_error(data) -> str:
        if not isinstance(data, dict):
            return "模型服务返回错误。"
        code = data.get("code", "REMOTE_ERROR")
        message = data.get("message", "模型服务返回错误。")
        retry = "当前消息未自动重发，请确认后手动重试。" if data.get("retryable") else "请修复配置后再重试。"
        return f"[{code}] {message} {retry}"


class ComposerInput(QPlainTextEdit):
    submitted = Signal()
    files_added = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(88)
        self.setMaximumHeight(200)
        self.setAcceptDrops(True)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:  # compatibility with existing example callbacks
        self.setPlainText(value)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if _mime_local_file_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = _mime_local_file_paths(event.mimeData())
        if paths:
            self.files_added.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def insertFromMimeData(self, source) -> None:
        paths = _mime_local_file_paths(source)
        if paths:
            self.files_added.emit(paths)
            return
        if source.hasImage():
            image = source.imageData()
            tmp = tempfile.NamedTemporaryFile(prefix="modelforge-paste-", suffix=".png", delete=False)
            tmp.close()
            if image.save(tmp.name, "PNG"):
                self.files_added.emit([tmp.name])
                return
            with contextlib.suppress(OSError):
                os.unlink(tmp.name)
        super().insertFromMimeData(source)


def _mime_local_file_paths(mime_data) -> list[str]:
    if mime_data is None or not mime_data.hasUrls():
        return []
    paths: list[str] = []
    for url in mime_data.urls():
        if isinstance(url, QUrl) and url.isLocalFile():
            path = url.toLocalFile()
            if path and os.path.isfile(path):
                paths.append(path)
    return paths[:10]


class ChatPage(QWidget, AsyncApiMixin):
    """Streaming conversation workspace with safe, plain-text message rendering."""

    def __init__(self, api, readiness_store=None, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api, self.session_id, self.messages, self.worker = api, None, [], None
        self.readiness_store = readiness_store
        self._model_ready = False
        self._remote_provider_count = 0
        self._pending_provider_id = None
        self._local_models: list[dict] = []
        self._selected_model_id: int | None = None
        self._ready_target: dict = {}
        self.attachments: list[dict] = []
        self.artifacts: list[dict] = []
        self._pending_turn_payload: dict | None = None
        self._active_turn_id: str | None = None
        self._structured_turn_last_sequence = 0
        self._structured_turn_poll_inflight = False
        self._seen_structured_message_ids: set[int] = set()
        self.session_refresher = None
        self._stream_active = False
        self._init_ui()
        self._turn_poll_timer = QTimer(self)
        self._turn_poll_timer.setInterval(1200)
        self._turn_poll_timer.timeout.connect(self._poll_structured_turn_events)
        self.refresh_providers()
        self.refresh_local_models()
        if self.readiness_store:
            self.readiness_store.changed.connect(self._render_readiness)
            self.readiness_store.failed.connect(
                lambda _error: self._render_readiness({"level": "SERVICE_UNAVAILABLE"})
            )
            self.readiness_store.refresh()

    def showEvent(self, event):
        """Re-read model state on entry: services may be added while hidden."""
        super().showEvent(event)
        self.refresh_providers()
        self.refresh_local_models()
        if self.readiness_store:
            self.readiness_store.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.chat_status = MFStatusBadge("未选择模型", "warning")
        self.header = MFPageHeader("对话", "选择模型后开始会话。参数与知识库范围保持在当前页。", self.chat_status)
        layout.addWidget(self.header)
        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        self.local_model_select = QComboBox()
        self.local_model_select.setAccessibleName("本地模型")
        self.local_model_select.setToolTip("来自模型中心（Model Registry）的本地模型")
        self.local_model_select.currentIndexChanged.connect(self._local_model_changed)
        model_row.addWidget(self.local_model_select)
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("选择本地模型，或已配置的远程模型")
        self.model_input.setAccessibleName("模型名称")
        model_row.addWidget(self.model_input, 1)
        self.provider_select = QComboBox()
        self.provider_select.setAccessibleName("模型服务")
        self.provider_select.addItem("本地运行时", None)
        self.provider_select.currentIndexChanged.connect(self._provider_changed)
        model_row.addWidget(self.provider_select)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        self.load_btn = QPushButton("使用模型")
        self.load_btn.setAccessibleName("使用所选模型")
        self.load_btn.clicked.connect(self.load_model)
        action_row.addWidget(self.load_btn)
        self.kb_check = QCheckBox("使用知识库")
        self.kb_check.setAccessibleName("使用知识库回答")
        action_row.addWidget(self.kb_check)
        self.mode_select = QComboBox()
        self.mode_select.setAccessibleName("对话模式")
        self.mode_select.addItem("对话", "chat")
        self.mode_select.addItem("Agent", "agent")
        self.mode_select.setToolTip("Agent 模式会先执行后端预检；沙箱未就绪时不会运行工具。")
        action_row.addWidget(self.mode_select)
        action_row.addStretch(1)
        controls.addLayout(model_row)
        controls.addLayout(action_row)
        layout.addLayout(controls)
        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setAccessibleName("对话记录")
        self.display.setPlaceholderText("对话内容将显示在这里。")
        layout.addWidget(self.display, 1)
        attachment_row = QHBoxLayout()
        attachment_row.setContentsMargins(0, 0, 0, 0)
        self.attachment_list = QListWidget()
        self.attachment_list.setAccessibleName("附件队列")
        self.attachment_list.setMaximumHeight(86)
        self.attachment_list.setToolTip("本轮消息将引用的已上传附件")
        self.attachment_list.itemDoubleClicked.connect(self.preview_attachment)
        attachment_row.addWidget(self.attachment_list, 1)
        self.add_attachment_btn = QPushButton("添加附件")
        self.add_attachment_btn.setAccessibleName("添加附件")
        self.add_attachment_btn.clicked.connect(self.select_attachments)
        attachment_row.addWidget(self.add_attachment_btn)
        self.clear_attachment_btn = QPushButton("清空")
        self.clear_attachment_btn.setAccessibleName("清空附件")
        self.clear_attachment_btn.clicked.connect(self.clear_attachments)
        attachment_row.addWidget(self.clear_attachment_btn)
        layout.addLayout(attachment_row)
        artifact_row = QHBoxLayout()
        artifact_row.setContentsMargins(0, 0, 0, 0)
        self.artifact_list = QListWidget()
        self.artifact_list.setAccessibleName("成果列表")
        self.artifact_list.setMaximumHeight(86)
        self.artifact_list.setToolTip("当前会话生成的成果文件")
        self.artifact_list.itemDoubleClicked.connect(self.preview_artifact_versions)
        self.artifact_list.currentItemChanged.connect(lambda _current, _previous: self._set_composer_enabled())
        artifact_row.addWidget(self.artifact_list, 1)
        self.refresh_artifact_btn = QPushButton("刷新成果")
        self.refresh_artifact_btn.setAccessibleName("刷新成果")
        self.refresh_artifact_btn.clicked.connect(self.refresh_artifacts)
        artifact_row.addWidget(self.refresh_artifact_btn)
        self.quote_artifact_btn = QPushButton("引用最新版")
        self.quote_artifact_btn.setAccessibleName("引用最新版成果")
        self.quote_artifact_btn.clicked.connect(self.quote_selected_artifact)
        artifact_row.addWidget(self.quote_artifact_btn)
        layout.addLayout(artifact_row)
        message_tools = QHBoxLayout()
        message_tools.setContentsMargins(0, 0, 0, 0)
        self.message_search_input = QLineEdit()
        self.message_search_input.setAccessibleName("搜索消息")
        self.message_search_input.setPlaceholderText("搜索当前会话消息")
        self.message_search_input.returnPressed.connect(self.search_messages)
        message_tools.addWidget(self.message_search_input, 1)
        self.search_messages_btn = QPushButton("搜索")
        self.search_messages_btn.setAccessibleName("搜索消息")
        self.search_messages_btn.clicked.connect(self.search_messages)
        message_tools.addWidget(self.search_messages_btn)
        self.pinned_messages_btn = QPushButton("固定消息")
        self.pinned_messages_btn.setAccessibleName("查看固定消息")
        self.pinned_messages_btn.clicked.connect(self.show_pinned_messages)
        message_tools.addWidget(self.pinned_messages_btn)
        self.pin_message_btn = QPushButton("固定/取消")
        self.pin_message_btn.setAccessibleName("固定或取消固定选中消息")
        self.pin_message_btn.clicked.connect(self.toggle_selected_message_pin)
        message_tools.addWidget(self.pin_message_btn)
        layout.addLayout(message_tools)
        self.message_result_list = QListWidget()
        self.message_result_list.setAccessibleName("消息搜索结果")
        self.message_result_list.setMaximumHeight(86)
        self.message_result_list.setToolTip("当前会话的搜索或固定消息结果")
        self.message_result_list.currentItemChanged.connect(lambda _current, _previous: self._set_composer_enabled())
        layout.addWidget(self.message_result_list)
        composer = QHBoxLayout()
        self.msg_input = ComposerInput()
        self.msg_input.setAccessibleName("消息内容")
        self.msg_input.setPlaceholderText("向 ModelForge 发送消息…")
        self.msg_input.submitted.connect(self.send_message)
        self.msg_input.files_added.connect(self.add_attachment_paths)
        composer.addWidget(self.msg_input, 1)
        examples = QPushButton("示例")
        examples.setAccessibleName("打开对话示例")
        examples.clicked.connect(
            lambda: open_examples(
                "chat", self, lambda example: self.msg_input.setText(example.template)
            )
        )
        composer.addWidget(examples)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setAccessibleName("停止生成")
        self.stop_btn.setToolTip("停止当前生成")
        self.stop_btn.clicked.connect(self.stop_stream)
        self.stop_btn.setEnabled(False)
        composer.addWidget(self.stop_btn)
        self.send_btn = QPushButton("发送")
        self.send_btn.setProperty("accent", True)
        self.send_btn.setAccessibleName("发送消息")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setEnabled(False)
        composer.addWidget(self.send_btn)
        layout.addLayout(composer)
        self.retranslate()

    def retranslate(self, translator=None) -> None:
        translator = translator or current()
        if translator is not None:
            self.header.set_text(
                translator.t("nav.chat", "对话"),
                translator.t("chat.subtitle", "选择模型后开始会话。参数与知识库范围保持在当前页。"),
            )
        localize_tree(self, translator)
        self._render_local_models(self._local_models)

    def _append_notice(self, title: str, detail: str = "") -> None:
        self.display.appendPlainText(title)
        if detail:
            self.display.appendPlainText(detail)
        self.display.appendPlainText("")
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        self.display.verticalScrollBar().setValue(self.display.verticalScrollBar().maximum())

    def refresh_providers(self) -> None:
        """Re-read the saved remote services so newly configured ones appear."""
        self._run_api(
            self.api.list_remote_providers,
            self._render_remote_providers,
            self._providers_failed,
            request_key="providers",
        )

    # ---- local models come from the unified registry ---------------------

    def refresh_local_models(self) -> None:
        """Populate the local model selector from the model registry."""
        self._run_api(
            lambda: _list_chat_models(self.api),
            self._render_local_models,
            self._local_models_failed,
            request_key="local-models",
        )

    def _render_local_models(self, models) -> None:
        locale = current().locale if current() is not None else "zh_CN"
        self._local_models = [model for model in (models or []) if isinstance(model, dict)]
        previous = self._selected_model_id
        self.local_model_select.blockSignals(True)
        self.local_model_select.clear()
        self.local_model_select.addItem(localize_text("本地模型…", locale), None)
        for model in self._local_models:
            name = model.get("display_name") or model.get("name") or str(model.get("model_id"))
            loaded = model.get("runtime_status") == "loaded"
            state = localize_text("已加载" if loaded else "未加载", locale)
            self.local_model_select.addItem(f"{name} {'●' if loaded else '○'} {state}", model.get("model_id") or model.get("id"))
        if previous is not None:
            index = self.local_model_select.findData(previous)
            if index >= 0:
                self.local_model_select.setCurrentIndex(index)
        self.local_model_select.blockSignals(False)
        self._local_model_changed(self.local_model_select.currentIndex())

    def _local_models_failed(self, _error) -> None:
        self._local_models = []
        self._refresh_status()

    def _selected_local_model(self) -> dict | None:
        for model in self._local_models:
            if (model.get("model_id") or model.get("id")) == self._selected_model_id:
                return model
        return None

    def _local_model_changed(self, index) -> None:
        model_id = self.local_model_select.itemData(index)
        self._selected_model_id = model_id if isinstance(model_id, int) else None
        if model_id is None:
            self._refresh_status()
            self._set_composer_enabled()
            return
        model = self._selected_local_model() or {}
        name = model.get("display_name") or model.get("name") or ""
        if name:
            self.model_input.setText(name)
        # Selecting a local model means "use the local runtime", not a provider.
        if self.provider_select.currentData() is not None:
            self.provider_select.blockSignals(True)
            self.provider_select.setCurrentIndex(0)
            self.provider_select.blockSignals(False)
            self.load_btn.setText("使用模型")
        self._refresh_status()
        self._set_composer_enabled()

    @staticmethod
    def _provider_selectable(provider: dict) -> bool:
        """A saved service is selectable once it is enabled and holds a key.

        Verification only unlocks the agent runtime; the chat route resolves an
        enabled provider with a stored credential, so hiding unverified
        services here made a configured model impossible to pick.
        """
        if provider.get("enabled") is False:
            return False
        return bool(provider.get("key_configured") or provider.get("credential_state") == "configured")

    def _render_remote_providers(self, providers):
        locale = current().locale if current() is not None else "zh_CN"
        previous = self._provider_id()
        selected = previous if previous is not None else self._pending_provider_id
        selectable = [p for p in (providers or []) if self._provider_selectable(p)]
        selectable.sort(key=lambda p: p.get("verification_status") != "success")
        self.provider_select.blockSignals(True)
        self.provider_select.clear()
        self.provider_select.addItem(localize_text("本地运行时", locale), None)
        for provider in selectable:
            verified = provider.get("verification_status") == "success"
            label = f"{provider['name']} · {provider['default_model']}"
            if not verified:
                label += localize_text("（未验证）", locale)
            self.provider_select.addItem(label, provider)
            index = self.provider_select.count() - 1
            if not verified:
                self.provider_select.setItemData(
                    index,
                    localize_text("该服务已保存但尚未验证连接；可直接对话，建议在模型管理中验证。", locale),
                    Qt.ToolTipRole,
                )
            if provider.get("id") == selected:
                self.provider_select.setCurrentIndex(index)
        self.provider_select.blockSignals(False)
        self._remote_provider_count = len(selectable)
        if selected is not None and self._provider_id() == selected:
            self._pending_provider_id = None
        if self._provider() is not None and previous != self._provider_id():
            # Sync the model field only when the effective service changed, so a
            # manually typed model name survives a background refresh.
            self._provider_changed(self.provider_select.currentIndex())
        else:
            self._refresh_status()

    def _providers_failed(self, _error) -> None:
        self._remote_provider_count = 0
        self._refresh_status()

    def select_provider(self, provider_id) -> None:
        """Select one saved service, retrying once the list has been loaded."""
        self._pending_provider_id = provider_id
        for index in range(self.provider_select.count()):
            provider = self.provider_select.itemData(index)
            if isinstance(provider, dict) and provider.get("id") == provider_id:
                self.provider_select.setCurrentIndex(index)
                self._pending_provider_id = None
                return
        self.refresh_providers()

    def _provider(self):
        value = self.provider_select.currentData()
        return value if isinstance(value, dict) else None

    def _provider_id(self):
        provider = self._provider()
        if provider:
            return provider.get("id")
        if (
            self._ready_target.get("kind") == "remote"
            and self.model_input.text().strip() == self._ready_target.get("model_name")
        ):
            return self._ready_target.get("provider_id")
        return None

    def _provider_changed(self, _index):
        provider = self._provider()
        if provider:
            self.model_input.setText(provider["default_model"])
            self.load_btn.setText("使用远程服务")
            # A remote service supersedes any local registry selection.
            self._selected_model_id = None
            if self.local_model_select.currentIndex() != 0:
                self.local_model_select.blockSignals(True)
                self.local_model_select.setCurrentIndex(0)
                self.local_model_select.blockSignals(False)
        else:
            self.load_btn.setText("使用模型")
        self._refresh_status()
        self._set_composer_enabled()

    def _render_readiness(self, snapshot: dict) -> None:
        if not isinstance(snapshot, dict):
            return
        previous_target = self._ready_target
        self._model_ready = snapshot.get("level") == "READY"
        target = snapshot.get("default_target") or {}
        self._ready_target = target if self._model_ready else {}
        if target and (not self.model_input.text().strip() or target != previous_target):
            self.model_input.setText(target.get("model_name") or "")
            provider_id = target.get("provider_id")
            if provider_id is not None:
                matched = False
                for index in range(self.provider_select.count()):
                    provider = self.provider_select.itemData(index)
                    if isinstance(provider, dict) and provider.get("id") == provider_id:
                        self.provider_select.setCurrentIndex(index)
                        matched = True
                        break
                if not matched:
                    self.refresh_providers()
        self._set_composer_enabled()
        self._refresh_status()

    def _refresh_status(self) -> None:
        """Report the model status without hiding a configured remote service."""
        provider = self._provider()
        if provider is not None:
            model = self.model_input.text().strip() or provider.get("default_model", "")
            self.chat_status.set_state(f"{provider['name']} · {model}", "online")
            return
        local = self._selected_local_model()
        if local is not None:
            name = local.get("display_name") or local.get("name") or ""
            if local.get("runtime_status") == "loaded":
                self.chat_status.set_state(f"{name} · {format_text('已加载')}", "online")
            elif local.get("ready"):
                self.chat_status.set_state(f"{name} · {format_text('未加载（发送时自动加载）')}", "online")
            else:
                self.chat_status.set_state(f"{name} · {format_text('尚不可用')}", "warning")
            return
        if self._model_ready:
            self.chat_status.set_state(format_text("模型已就绪"), "online")
            return
        if self._remote_provider_count:
            self.chat_status.set_state(
                format_text("已配置 {count} 个远程模型，请在上方选择", count=self._remote_provider_count), "warning"
            )
            return
        self.chat_status.set_state(format_text("请先配置可用模型"), "warning")

    def _chat_ready(self) -> bool:
        return (
            self._model_ready
            or self._provider() is not None
            or self._selected_model_id is not None
        )

    def _chat_mode(self) -> str:
        mode = self.mode_select.currentData()
        return mode if mode in {"chat", "agent"} else "chat"

    def _set_composer_enabled(self) -> None:
        self.send_btn.setEnabled(self._chat_ready() and not self._stream_active)
        self.msg_input.setEnabled(not self._stream_active)
        self.add_attachment_btn.setEnabled(not self._stream_active)
        self.clear_attachment_btn.setEnabled(not self._stream_active and bool(self.attachments))
        self.refresh_artifact_btn.setEnabled(self.session_id is not None and not self._stream_active)
        self.quote_artifact_btn.setEnabled(self.session_id is not None and not self._stream_active and self.artifact_list.currentItem() is not None)
        self.search_messages_btn.setEnabled(self.session_id is not None and not self._stream_active)
        self.pinned_messages_btn.setEnabled(self.session_id is not None and not self._stream_active)
        self.pin_message_btn.setEnabled(self.session_id is not None and not self._stream_active and self.message_result_list.currentItem() is not None)
        self.stop_btn.setEnabled(self._stream_active)

    def select_attachments(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "选择附件",
            "",
            "Supported files (*.txt *.md *.json *.jsonl *.csv *.tsv *.log *.py *.js *.ts *.html *.xml *.yaml *.yml *.toml *.png *.jpg *.jpeg *.webp *.pdf *.wav *.mp4 *.m4v *.mov *.webm);;All files (*)",
        )
        self.add_attachment_paths(paths)

    def add_attachment_paths(self, paths: list[str]) -> None:
        remaining = max(0, 10 - self.attachment_list.count())
        for path in paths[:remaining]:
            self._queue_upload(path)
        if len(paths) > remaining:
            self._append_notice("附件数量已达上限", "每条结构化消息最多加入 10 个附件。")

    def _queue_upload(self, path: str) -> None:
        name = os.path.basename(path)
        row = QListWidgetItem(f"上传中 · {name}")
        self.attachment_list.addItem(row)
        self._run_api(
            lambda p=path: self.api.upload_attachment(p),
            lambda payload, item=row: self._attachment_uploaded(item, payload),
            lambda error, item=row, label=name: self._attachment_failed(item, label, error),
            request_key=f"attachment-upload-{uuid.uuid4().hex}",
        )

    def _attachment_uploaded(self, row: QListWidgetItem, payload: dict) -> None:
        self.attachments.append(payload)
        size = payload.get("size_bytes", 0)
        row.setText(f"已就绪 · {payload.get('display_name', payload.get('id'))} · {size} bytes")
        row.setData(Qt.UserRole, payload.get("id"))
        self._set_composer_enabled()

    def _attach_existing_attachment(self, payload: dict) -> None:
        attachment_id = payload.get("id")
        if not attachment_id:
            return
        if any(item.get("id") == attachment_id for item in self.attachments):
            self._append_notice("已在附件队列中", str(payload.get("display_name", attachment_id)))
            return
        if self.attachment_list.count() >= 10:
            self._append_notice("附件数量已达上限", "每条结构化消息最多加入 10 个附件。")
            return
        self.attachments.append(payload)
        size = payload.get("size_bytes", 0)
        row = QListWidgetItem(f"已就绪 · {payload.get('display_name', attachment_id)} · {size} bytes")
        row.setData(Qt.UserRole, attachment_id)
        self.attachment_list.addItem(row)
        self._set_composer_enabled()

    def _attachment_failed(self, row: QListWidgetItem, label: str, error) -> None:
        row.setText(f"上传失败 · {label} · {format_api_error(error)}")
        self._set_composer_enabled()

    def preview_attachment(self, row: QListWidgetItem) -> None:
        attachment_id = row.data(Qt.UserRole)
        if not attachment_id:
            return
        self._run_api(
            lambda aid=attachment_id: self.api.attachment_preview(aid),
            self._show_attachment_preview,
            lambda error: self._append_notice("附件预览失败", format_api_error(error)),
            request_key="attachment-preview",
        )

    def _show_attachment_preview(self, payload: dict) -> None:
        attachment = payload.get("attachment", {}) if isinstance(payload, dict) else {}
        lines = [
            f"名称：{attachment.get('display_name', '-')}",
            f"类型：{attachment.get('mime_type', '-')}",
            f"大小：{attachment.get('size_bytes', 0)} bytes",
        ]
        text = payload.get("text") if isinstance(payload, dict) else None
        if isinstance(text, str) and text:
            lines.append(text[:1200])
        else:
            derivatives = payload.get("derivatives", []) if isinstance(payload, dict) else []
            for derivative in derivatives[:3]:
                if isinstance(derivative, dict):
                    lines.append(f"{derivative.get('kind')} · {derivative.get('state')} · {derivative.get('metadata', {})}")
        self._append_notice("附件预览", "\n".join(lines))

    def clear_attachments(self) -> None:
        self.attachments = []
        self.attachment_list.clear()
        self._set_composer_enabled()

    def refresh_artifacts(self) -> None:
        if self.session_id is None:
            return
        self._run_api(
            lambda: self.api.list_session_artifacts(self.session_id),
            self._render_session_artifacts,
            lambda error: self._append_notice("成果列表刷新失败", format_api_error(error)),
            request_key="session-artifacts",
        )

    def _render_session_artifacts(self, artifacts) -> None:
        self.artifacts = [item for item in artifacts or [] if isinstance(item, dict)]
        self.artifact_list.clear()
        for artifact in self.artifacts:
            name = artifact.get("name") or artifact.get("id") or "artifact"
            version = artifact.get("current_version", "-")
            row = QListWidgetItem(f"{name} · v{version}")
            row.setData(Qt.UserRole, artifact)
            self.artifact_list.addItem(row)
        self._set_composer_enabled()

    def _selected_artifact(self) -> dict | None:
        row = self.artifact_list.currentItem()
        artifact = row.data(Qt.UserRole) if row else None
        return artifact if isinstance(artifact, dict) else None

    def preview_artifact_versions(self, row: QListWidgetItem | None = None) -> None:
        artifact = row.data(Qt.UserRole) if row is not None else self._selected_artifact()
        if not isinstance(artifact, dict):
            return
        artifact_id = artifact.get("id")
        if not artifact_id:
            return
        self._run_api(
            lambda aid=artifact_id: self.api.list_chat_artifact_versions(aid),
            lambda versions, art=artifact: self._show_artifact_versions(art, versions),
            lambda error: self._append_notice("成果版本读取失败", format_api_error(error)),
            request_key="artifact-versions",
        )

    def _show_artifact_versions(self, artifact: dict, versions) -> None:
        rows = []
        for version in versions or []:
            if isinstance(version, dict):
                rows.append(f"v{version.get('version')} · {version.get('size_bytes', 0)} bytes · {version.get('sha256', '')[:12]}")
        self._append_notice(f"成果版本 · {artifact.get('name', artifact.get('id', 'artifact'))}", "\n".join(rows) or "暂无版本。")

    def quote_selected_artifact(self) -> None:
        artifact = self._selected_artifact()
        if not artifact:
            self._append_notice("未选择成果", "请先在成果列表中选择一个文件。")
            return
        artifact_id = artifact.get("id")
        if not artifact_id:
            return
        self._run_api(
            lambda aid=artifact_id: self.api.list_chat_artifact_versions(aid),
            lambda versions, art=artifact: self._quote_latest_artifact_version(art, versions),
            lambda error: self._append_notice("成果引用失败", format_api_error(error)),
            request_key="artifact-quote",
        )

    def _quote_latest_artifact_version(self, artifact: dict, versions) -> None:
        candidates = [item for item in versions or [] if isinstance(item, dict)]
        if not candidates:
            self._append_notice("成果引用失败", "该成果没有可引用版本。")
            return
        latest = max(candidates, key=lambda item: int(item.get("version") or 0))
        metadata = latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {}
        attachment = {
            "id": latest.get("attachment_id"),
            "display_name": f"{artifact.get('name', artifact.get('id', 'artifact'))} v{latest.get('version')}",
            "mime_type": metadata.get("mime_type") or "text/plain",
            "size_bytes": latest.get("size_bytes", 0),
        }
        self._attach_existing_attachment(attachment)
        self._append_notice("已引用成果", str(attachment["display_name"]))

    def search_messages(self) -> None:
        if self.session_id is None:
            self._append_notice("请先选择或创建会话")
            return
        query = self.message_search_input.text().strip()
        self._run_api(
            lambda: self.api.search_messages(self.session_id, query, pinned_only=False, limit=50),
            self._render_message_results,
            lambda error: self._append_notice("消息搜索失败", format_api_error(error)),
            request_key="message-search",
        )

    def show_pinned_messages(self) -> None:
        if self.session_id is None:
            self._append_notice("请先选择或创建会话")
            return
        self._run_api(
            lambda: self.api.search_messages(self.session_id, "", pinned_only=True, limit=50),
            self._render_message_results,
            lambda error: self._append_notice("固定消息读取失败", format_api_error(error)),
            request_key="message-pinned",
        )

    def toggle_selected_message_pin(self) -> None:
        if self.session_id is None:
            self._append_notice("请先选择或创建会话")
            return
        row = self.message_result_list.currentItem()
        if row is None:
            self._append_notice("请先选择一条搜索结果")
            return
        message = row.data(Qt.UserRole) or {}
        message_id = message.get("id")
        if not isinstance(message_id, int):
            self._append_notice("选中消息缺少有效 ID")
            return
        next_state = not bool(message.get("is_pinned"))
        self._run_api(
            lambda: self.api.set_message_pinned(self.session_id, message_id, next_state),
            self._message_pin_updated,
            lambda error: self._append_notice("固定消息更新失败", format_api_error(error)),
            request_key=f"message-pin-{message_id}",
        )

    def _message_pin_updated(self, message: dict) -> None:
        state = "已固定" if message.get("is_pinned") else "已取消固定"
        self._append_notice(state, str(message.get("content", ""))[:160])
        query = self.message_search_input.text().strip()
        if query:
            self.search_messages()
        else:
            self.show_pinned_messages()

    def _render_message_results(self, messages) -> None:
        self.message_result_list.clear()
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            marker = "★ " if message.get("is_pinned") else ""
            role = message.get("role", "message")
            content = str(message.get("content", "")).replace("\n", " ")[:140]
            row = QListWidgetItem(f"{marker}{role}: {content}")
            row.setData(Qt.UserRole, message)
            self.message_result_list.addItem(row)
        self._set_composer_enabled()

    def set_session(self, session_id):
        self.stop_stream(silent=True)
        self.session_id = session_id
        self.display.clear()
        self.messages = []
        self.artifacts = []
        self.artifact_list.clear()
        self.message_result_list.clear()
        self._append_notice("正在加载对话…")
        self._run_api(
            lambda: self.api.list_messages(session_id),
            lambda messages: self._render_session(session_id, messages),
            self._session_load_failed,
            request_key="session-load",
        )

    def _render_session(self, session_id, messages):
        if session_id != self.session_id:
            return
        self.display.clear()
        self.messages = []
        self.message_result_list.clear()
        for message in messages:
            self._append_msg(message["role"], str(message["content"]))
            self.messages.append({"role": message["role"], "content": message["content"]})
        self.refresh_artifacts()

    def _session_load_failed(self, error):
        self._append_notice("会话加载未完成", format_api_error(error))

    def load_model(self):
        if not self._chat_ready():
            QMessageBox.information(self, "模型尚未就绪", "请先在模型工作区完成模型配置或远程服务验证。")
            return
        model = self.model_input.text().strip()
        if not model:
            QMessageBox.warning(self, "请选择模型", "请输入模型名称，或选择已配置的远程模型服务。")
            return
        provider = self._provider()
        if provider:
            self.chat_status.set_state(f"{provider['name']} · {model}", "online")
            self._append_notice("远程模型已就绪", "消息将发送到所选的 OpenAI 兼容服务。")
            return
        if self._selected_model_id is not None:
            # Loading is owned by the runtime manager; the page just asks.
            self.load_btn.setEnabled(False)
            self._append_notice("正在通过运行时管理器加载本地模型…")
            self._run_api(
                lambda: self.api.load_model(self._selected_model_id),
                lambda result: self._local_model_loaded(model, result),
                self._model_load_failed,
                request_key="model-start",
            )
            return
        self.load_btn.setEnabled(False)
        self._append_notice("正在准备本地模型…")
        self._run_api(
            lambda: self.api.runtime_start(model),
            lambda _result: self._model_loaded(model),
            self._model_load_failed,
            request_key="model-start",
        )

    def _local_model_loaded(self, model, result):
        self.load_btn.setEnabled(True)
        self.chat_status.set_state(f"{model} 已加载", "online")
        self._append_notice("模型已加载", "现在可以开始对话。")
        self.refresh_local_models()

    def _model_loaded(self, model):
        self.load_btn.setEnabled(True)
        self.chat_status.set_state(f"{model} 已就绪", "online")
        self._append_notice("模型已就绪", "现在可以开始对话。")

    def _model_load_failed(self, error):
        self.load_btn.setEnabled(True)
        QMessageBox.warning(self, "无法加载模型", format_api_error(error))

    def _append_msg(self, role, content):
        name = "你" if role == "user" else "ModelForge"
        self._append_notice(name, content)

    def send_message(self):
        text, model = self.msg_input.text().strip(), self.model_input.text().strip()
        if not self._chat_ready():
            QMessageBox.information(self, "模型尚未就绪", "请先在模型工作区配置并验证一个可用模型。")
            return
        if not text and not self.attachments:
            return
        if not model:
            QMessageBox.warning(self, "请选择模型", "请先输入或选择模型名称。")
            return
        if self.worker and self.worker.isRunning():
            return
        provider_id = self._provider_id()
        if self.kb_check.isChecked() and provider_id:
            QMessageBox.information(
                self,
                "知识库与远程模型",
                "知识库检索目前使用本地运行时。请关闭“使用知识库”，或选择本地模型。",
            )
            return
        if self.attachments or self._chat_mode() == "agent":
            self._send_structured_turn(text, model)
            return
        self._append_msg("user", text)
        self.messages.append({"role": "user", "content": text})
        self.msg_input.clear()
        self._stream_active = True
        self._set_composer_enabled()
        if self.kb_check.isChecked():
            self._run_api(
                lambda: self.api.knowledge_answer(model=model, question=text, top_k=3),
                self._show_kb_answer,
                self._show_kb_failure,
                request_key="knowledge-answer",
            )
            return
        self.display.appendPlainText("ModelForge")
        self._scroll_to_end()
        self.worker = StreamWorker(
            self.api, model, self.messages, self.session_id, provider_id, self._selected_model_id
        )
        self.worker.delta.connect(self._on_delta)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._stream_finished)
        self.worker.start()

    def _send_structured_turn(self, text: str, model: str) -> None:
        provider_id = self._provider_id()
        payload = self._turn_payload(text, model, provider_id)
        attachment_summary = "\n".join(
            f"- {item.get('display_name', item.get('id'))}" for item in self.attachments
        )
        user_text = text or "（仅附件）"
        self._append_msg("user", f"{user_text}\n{attachment_summary}" if attachment_summary else user_text)
        self.msg_input.clear()
        self._stream_active = True
        self._set_composer_enabled()
        self._append_notice("正在预检并提交结构化消息…")
        self._pending_turn_payload = payload
        self._run_api(
            lambda: self.api.chat_preflight(payload),
            self._structured_turn_preflight_done,
            self._structured_turn_failed,
            request_key="chat-turn-preflight",
        )

    def _structured_turn_preflight_done(self, payload: dict) -> None:
        if not isinstance(payload, dict) or not payload.get("ok"):
            blockers = payload.get("blockers") if isinstance(payload, dict) else None
            detail = "\n".join(
                f"- {item.get('code', 'BLOCKED')}: {item.get('message', '')}" for item in blockers or [] if isinstance(item, dict)
            )
            self._append_notice("结构化消息未通过预检", detail or "当前模型或处理器不支持该输入。")
            self._pending_turn_payload = None
            self._stream_finished()
            return
        self._append_context_estimate(payload.get("context_estimate") if isinstance(payload, dict) else None)
        turn_payload = self._pending_turn_payload
        if not turn_payload:
            self._append_notice("结构化消息未发送", "预检结果已过期，请重新发送。")
            self._stream_finished()
            return
        self._run_api(
            lambda: self.api.create_chat_turn(turn_payload),
            self._structured_turn_done,
            self._structured_turn_failed,
            request_key="chat-turn-create",
        )

    def _append_context_estimate(self, estimate) -> None:
        if not isinstance(estimate, dict):
            return
        self._append_notice(
            "本轮上下文",
            "\n".join(
                [
                    f"文本字符：{estimate.get('text_characters', 0)}",
                    f"估算提交字符：{estimate.get('estimated_prompt_characters', 0)}",
                    f"附件：{estimate.get('attachments', 0)}",
                    f"已选范围：{estimate.get('selected_parts', 0)}",
                ]
            ),
        )

    def _turn_payload(self, text: str, model: str, provider_id) -> dict:
        parts: list[dict] = []
        if text:
            parts.append({"type": "text", "text": text})
        for item in self.attachments:
            mime = str(item.get("mime_type", ""))
            attachment_id = item.get("id")
            if mime.startswith("image/"):
                parts.append({"type": "image", "attachment_id": attachment_id, "detail": "auto"})
            elif mime.startswith("audio/"):
                parts.append({"type": "audio", "attachment_id": attachment_id, "processing": "asr"})
            elif mime.startswith("video/"):
                parts.append({"type": "video", "attachment_id": attachment_id, "processing": "frames_asr"})
            else:
                parts.append({"type": "file", "attachment_id": attachment_id, "processing": "extract_text"})
        if provider_id:
            target = {"kind": "remote", "model": model, "provider_id": provider_id}
        elif self._selected_model_id is not None:
            target = {"kind": "local", "model": model, "model_id": self._selected_model_id}
        else:
            target = {"kind": "legacy", "model": model}
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "target": target,
            "mode": self._chat_mode(),
            "message": {"parts": parts},
            "requested_outputs": [{"type": "text"}, {"type": "artifact", "format": "txt"}],
            "context": {"excluded_message_ids": [], "use_memory": False},
            "idempotency_key": f"desktop-{uuid.uuid4().hex}",
        }

    def _structured_turn_done(self, payload: dict) -> None:
        turn = payload.get("turn", {}) if isinstance(payload, dict) else {}
        turn_id = turn.get("id")
        if isinstance(turn_id, str):
            self._active_turn_id = turn_id
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        assistant_count = 0
        for message in messages:
            if message.get("role") == "assistant":
                content = str(message.get("content", ""))
                self._append_msg("assistant", content)
                self.messages.append({"role": "assistant", "content": content})
                assistant_count += 1
        if turn.get("status") == "SUCCEEDED":
            self._append_notice("已完成", f"Turn: {turn.get('id')}")
        elif turn_id:
            self._append_notice("已提交", f"Turn: {turn_id} · {turn.get('status', 'RUNNING')}")
            self._start_structured_turn_polling(turn_id)
            self.clear_attachments()
            return
        elif assistant_count == 0:
            self._append_notice("已提交", "结构化消息已提交，稍后可从会话快照恢复。")
        self.clear_attachments()
        self._pending_turn_payload = None
        self._stream_finished()
        if self.session_id:
            self._run_api(
                lambda: self.api.list_session_artifacts(self.session_id),
                self._show_session_artifacts,
                lambda _error: None,
                request_key="session-artifacts",
            )

    def _structured_turn_snapshot(self, payload: dict) -> None:
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        for message in messages:
            if message.get("role") == "assistant":
                content = str(message.get("content", ""))
                if not any(existing.get("role") == "assistant" and existing.get("content") == content for existing in self.messages):
                    self._append_msg("assistant", content)
                    self.messages.append({"role": "assistant", "content": content})
        turn = payload.get("turn", {}) if isinstance(payload, dict) else {}
        status = turn.get("status")
        self._append_notice("轮次状态", f"Turn: {turn.get('id')} · {status}")
        self._pending_turn_payload = None
        if status not in {"QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"}:
            self._turn_poll_timer.stop()
            self._stream_finished()

    def _start_structured_turn_polling(self, turn_id: str) -> None:
        self._active_turn_id = turn_id
        self._structured_turn_last_sequence = 0
        self._structured_turn_poll_inflight = False
        self._seen_structured_message_ids.clear()
        self._turn_poll_timer.start()
        self._poll_structured_turn_events()

    def _poll_structured_turn_events(self) -> None:
        turn_id = self._active_turn_id
        if not turn_id or self._structured_turn_poll_inflight:
            return
        self._structured_turn_poll_inflight = True
        after_sequence = self._structured_turn_last_sequence
        self._run_api(
            lambda tid=turn_id, seq=after_sequence: self.api.chat_turn_events(tid, seq),
            self._structured_turn_events_done,
            self._structured_turn_events_failed,
            request_key="chat-turn-events",
        )

    def _structured_turn_events_done(self, payload: dict) -> None:
        self._structured_turn_poll_inflight = False
        terminal = False
        for event in payload.get("events", []) if isinstance(payload, dict) else []:
            if not isinstance(event, dict):
                continue
            try:
                self._structured_turn_last_sequence = max(self._structured_turn_last_sequence, int(event.get("sequence", 0)))
            except (TypeError, ValueError):
                pass
            event_type = event.get("type")
            event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "message.completed":
                self._append_structured_assistant_message(event_payload)
            elif event_type == "artifact.created":
                artifact = event_payload.get("artifact") if isinstance(event_payload.get("artifact"), dict) else {}
                version = event_payload.get("version") if isinstance(event_payload.get("version"), dict) else {}
                name = artifact.get("name") or artifact.get("id") or "artifact"
                self._append_notice("已保存成果", f"{name} · version {version.get('version', artifact.get('current_version', '-'))}")
            elif event_type == "turn.finished":
                status = event_payload.get("status", "UNKNOWN")
                self._append_notice("轮次状态", f"Turn: {event.get('turn_id', self._active_turn_id)} · {status}")
                terminal = True
        if terminal:
            self._turn_poll_timer.stop()
            turn_id = self._active_turn_id
            if turn_id:
                self._run_api(
                    lambda tid=turn_id: self.api.get_chat_turn(tid),
                    self._structured_turn_snapshot,
                    self._structured_turn_failed,
                    request_key="chat-turn-snapshot",
                )

    def _structured_turn_events_failed(self, error) -> None:
        self._structured_turn_poll_inflight = False
        self._append_notice("轮次事件暂不可用", format_api_error(error))

    def _append_structured_assistant_message(self, payload: dict) -> None:
        message_id = payload.get("message_id")
        if isinstance(message_id, int):
            if message_id in self._seen_structured_message_ids:
                return
            self._seen_structured_message_ids.add(message_id)
        content = str(payload.get("content", ""))
        if not content:
            return
        if any(existing.get("role") == "assistant" and existing.get("content") == content for existing in self.messages):
            return
        self._append_msg("assistant", content)
        self.messages.append({"role": "assistant", "content": content})

    def _structured_turn_failed(self, error) -> None:
        self._turn_poll_timer.stop()
        self._append_notice("结构化消息未发送", format_api_error(error))
        self._pending_turn_payload = None
        self._stream_finished()

    def _show_session_artifacts(self, artifacts) -> None:
        self._render_session_artifacts(artifacts)
        if self.artifacts:
            latest = self.artifacts[0]
            self._append_notice("已保存成果", f"{latest.get('name')} · version {latest.get('current_version')}")

    def _show_kb_answer(self, result):
        answer = str(result.get("answer", ""))
        self._append_msg("assistant", answer)
        sources = result.get("sources", [])
        if sources:
            lines = [f"来源：{source.get('source', '-')}（相关度 {source.get('score', 0)}）" for source in sources]
            self._append_notice("参考来源", "\n".join(lines))
        self.messages.append({"role": "assistant", "content": answer})
        self._stream_finished()

    def _show_kb_failure(self, error):
        self._append_notice("无法回答", format_api_error(error))
        self._stream_finished()

    def _on_delta(self, chunk):
        cursor = self.display.textCursor()
        cursor.movePosition(_QTEXT_CURSOR_END)
        self.display.setTextCursor(cursor)
        self.display.insertPlainText(chunk)
        self._scroll_to_end()

    def _on_done(self, full):
        self.display.appendPlainText("\n")
        self.messages.append({"role": "assistant", "content": full})
        if self.session_id:
            self._run_api(
                lambda: self.api.auto_title(self.session_id),
                lambda _result: self.session_refresher() if self.session_refresher else None,
                lambda _error: None,
                request_key="auto-title",
            )

    def _on_failed(self, error):
        self._append_notice("无法响应", format_api_error(error))

    def _stream_finished(self) -> None:
        self._turn_poll_timer.stop()
        self._structured_turn_poll_inflight = False
        self._stream_active = False
        self._active_turn_id = None
        self._set_composer_enabled()

    def stop_stream(self, silent: bool = False) -> None:
        if self._active_turn_id:
            turn_id = self._active_turn_id
            self._turn_poll_timer.stop()
            self._run_api(
                lambda tid=turn_id: self.api.cancel_chat_turn(tid),
                lambda payload: self._append_notice("已请求取消", f"Turn: {payload.get('turn', {}).get('id', turn_id)}"),
                lambda error: self._append_notice("取消失败", format_api_error(error)),
                request_key="chat-turn-cancel",
            )
            if not silent:
                self._append_notice("已请求取消结构化轮次", f"Turn: {turn_id}")
            self._stream_active = False
            self._set_composer_enabled()
            return
        worker = self.worker
        if worker and worker.isRunning():
            worker.requestInterruption()
            if not silent:
                self._append_notice("已请求停止生成", "连接关闭后将停止接收输出。")
        self._stream_active = False
        self._set_composer_enabled()

    def shutdown_stream(self) -> None:
        self.stop_stream(silent=True)
        worker = self.worker
        self.worker = None
        if worker and worker.isRunning():
            worker.wait(2500)
        self.shutdown_async_api()
