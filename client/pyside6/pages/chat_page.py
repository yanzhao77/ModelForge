from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFPageHeader, MFStatusBadge
from i18n.ui_localizer import current, format_api_error, format_text, localize_tree, text as localize_text
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(88)
        self.setMaximumHeight(200)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:  # compatibility with existing example callbacks
        self.setPlainText(value)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


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
        self.session_refresher = None
        self._stream_active = False
        self._init_ui()
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
        action_row.addStretch(1)
        controls.addLayout(model_row)
        controls.addLayout(action_row)
        layout.addLayout(controls)
        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setAccessibleName("对话记录")
        self.display.setPlaceholderText("对话内容将显示在这里。")
        layout.addWidget(self.display, 1)
        composer = QHBoxLayout()
        self.msg_input = ComposerInput()
        self.msg_input.setAccessibleName("消息内容")
        self.msg_input.setPlaceholderText("向 ModelForge 发送消息…")
        self.msg_input.submitted.connect(self.send_message)
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

    def _set_composer_enabled(self) -> None:
        self.send_btn.setEnabled(self._chat_ready() and not self._stream_active)
        self.msg_input.setEnabled(not self._stream_active)
        self.stop_btn.setEnabled(self._stream_active)

    def set_session(self, session_id):
        self.stop_stream(silent=True)
        self.session_id = session_id
        self.display.clear()
        self.messages = []
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
        for message in messages:
            self._append_msg(message["role"], str(message["content"]))
            self.messages.append({"role": message["role"], "content": message["content"]})

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
        if not text:
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
        self._stream_active = False
        self._set_composer_enabled()

    def stop_stream(self, silent: bool = False) -> None:
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
