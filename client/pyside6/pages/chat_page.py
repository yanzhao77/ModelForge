from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QThread, Signal
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


class StreamWorker(QThread):
    """Reads a chat stream outside the GUI event loop."""

    delta = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, api, model, messages, session_id, provider_id=None):
        super().__init__()
        self.api, self.model, self.messages = api, model, messages
        self.session_id, self.provider_id = session_id, provider_id

    def run(self):
        full = ""
        try:
            for event in self.api.stream_chat(
                self.model, self.messages, self.session_id, self.provider_id,
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


class ChatPage(QWidget, AsyncApiMixin):
    """Streaming conversation workspace with safe, plain-text message rendering."""

    def __init__(self, api, readiness_store=None, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api, self.session_id, self.messages, self.worker = api, None, [], None
        self.readiness_store = readiness_store
        self._model_ready = False
        self.session_refresher = None
        self._stream_active = False
        self._init_ui()
        self._run_api(
            self.api.list_remote_providers,
            self._render_remote_providers,
            lambda _error: None,
            request_key="providers",
        )
        if self.readiness_store:
            self.readiness_store.changed.connect(self._render_readiness)
            self.readiness_store.failed.connect(
                lambda _error: self._render_readiness({"level": "SERVICE_UNAVAILABLE"})
            )
            self.readiness_store.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(MFSection("对话", "聊天"))
        header.addStretch(1)
        self.chat_status = MFStatusBadge("未选择模型", "warning")
        header.addWidget(self.chat_status)
        layout.addLayout(header)
        model_row = QHBoxLayout()
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("选择本地模型，或已配置的远程模型")
        self.model_input.setAccessibleName("模型名称")
        model_row.addWidget(self.model_input, 1)
        self.provider_select = QComboBox()
        self.provider_select.setAccessibleName("模型服务")
        self.provider_select.addItem("本地运行时", None)
        self.provider_select.currentIndexChanged.connect(self._provider_changed)
        model_row.addWidget(self.provider_select)
        self.load_btn = QPushButton("使用模型")
        self.load_btn.setAccessibleName("使用所选模型")
        self.load_btn.clicked.connect(self.load_model)
        model_row.addWidget(self.load_btn)
        self.kb_check = QCheckBox("使用知识库")
        self.kb_check.setAccessibleName("使用知识库回答")
        model_row.addWidget(self.kb_check)
        layout.addLayout(model_row)
        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setAccessibleName("对话记录")
        self.display.setPlaceholderText("对话内容将显示在这里。")
        layout.addWidget(self.display, 1)
        composer = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setAccessibleName("消息内容")
        self.msg_input.setPlaceholderText("向 ModelForge 发送消息…")
        self.msg_input.returnPressed.connect(self.send_message)
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

    def _append_notice(self, title: str, detail: str = "") -> None:
        self.display.appendPlainText(title)
        if detail:
            self.display.appendPlainText(detail)
        self.display.appendPlainText("")
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        self.display.verticalScrollBar().setValue(self.display.verticalScrollBar().maximum())

    def _render_remote_providers(self, providers):
        selected = self._provider_id()
        self.provider_select.blockSignals(True)
        self.provider_select.clear()
        self.provider_select.addItem("本地运行时", None)
        for provider in providers:
            if provider.get("verification_status") != "success":
                continue
            self.provider_select.addItem(
                f"{provider['name']} · {provider['default_model']}", provider
            )
            if provider["id"] == selected:
                self.provider_select.setCurrentIndex(self.provider_select.count() - 1)
        self.provider_select.blockSignals(False)

    def _provider(self):
        value = self.provider_select.currentData()
        return value if isinstance(value, dict) else None

    def _provider_id(self):
        provider = self._provider()
        return provider.get("id") if provider else None

    def _provider_changed(self, _index):
        provider = self._provider()
        if provider:
            self.model_input.setText(provider["default_model"])
            self.load_btn.setText("使用远程服务")
            self.chat_status.set_state(f"远程模型已就绪：{provider['name']}", "online")
        else:
            self.load_btn.setText("使用模型")
            self.chat_status.set_state("未选择模型", "warning")
        self._set_composer_enabled()

    def _render_readiness(self, snapshot: dict) -> None:
        self._model_ready = snapshot.get("level") == "READY"
        target = snapshot.get("default_target")
        if target and not self.model_input.text().strip():
            self.model_input.setText(target.get("model_name") or "")
            provider_id = target.get("provider_id")
            if provider_id is not None:
                for index in range(self.provider_select.count()):
                    provider = self.provider_select.itemData(index)
                    if isinstance(provider, dict) and provider.get("id") == provider_id:
                        self.provider_select.setCurrentIndex(index)
                        break
        self._set_composer_enabled()
        if self._provider() is None:
            self.chat_status.set_state(
                "模型已就绪" if self._model_ready else "请先配置可用模型",
                "online" if self._model_ready else "warning",
            )

    def _chat_ready(self) -> bool:
        return self._model_ready or self._provider() is not None

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
        self.load_btn.setEnabled(False)
        self._append_notice("正在准备本地模型…")
        self._run_api(
            lambda: self.api.runtime_start(model),
            lambda _result: self._model_loaded(model),
            self._model_load_failed,
            request_key="model-start",
        )

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
                lambda: self.api.knowledge_answer(model, text, top_k=3),
                self._show_kb_answer,
                self._show_kb_failure,
                request_key="knowledge-answer",
            )
            return
        self.display.appendPlainText("ModelForge")
        self._scroll_to_end()
        self.worker = StreamWorker(self.api, model, self.messages, self.session_id, provider_id)
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
        cursor.movePosition(QTextCursor.End)
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
