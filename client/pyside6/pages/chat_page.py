"""Conversation-first chat with local and remote OpenAI-compatible model selection."""

from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error, format_text
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class StreamWorker(QThread):
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
                self.model, self.messages, self.session_id, self.provider_id
            ):
                if self.isInterruptionRequested():
                    return
                kind = event.get("type")
                if kind == "delta":
                    content = event.get("data", "")
                    full += content
                    self.delta.emit(content)
                elif kind == "done":
                    self.done.emit(full)
                    return
                elif kind == "error":
                    self.failed.emit(self._format_error(event.get("data")))
                    return
            self.done.emit(full)
        except Exception as exc:
            self.failed.emit(str(exc))

    @staticmethod
    def _format_error(data) -> str:
        if not isinstance(data, dict):
            return str(data or "模型服务返回错误。")
        code = data.get("code", "REMOTE_ERROR")
        message = data.get("message", "模型服务返回错误。")
        retry = "当前消息未自动重发，请确认后手动重试。" if data.get("retryable") else "请修复配置后再重试。"
        return f"[{code}] {message} {retry}"


class ChatPage(QWidget, AsyncApiMixin):
    """Streaming conversation workspace with a safe remote-provider selector."""

    def __init__(self, api, readiness_store=None, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api, self.session_id, self.messages, self.worker = api, None, [], None
        self.readiness_store = readiness_store
        self._model_ready = False
        self.session_refresher = None
        self._init_ui()
        self._run_api(
            self.api.list_remote_providers,
            self._render_remote_providers,
            lambda _error: None,
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
        model_row.addWidget(self.model_input, 1)
        self.provider_select = QComboBox()
        self.provider_select.addItem("本地运行时", None)
        self.provider_select.currentIndexChanged.connect(self._provider_changed)
        model_row.addWidget(self.provider_select)
        self.load_btn = QPushButton("使用模型")
        self.load_btn.clicked.connect(self.load_model)
        model_row.addWidget(self.load_btn)
        self.kb_check = QCheckBox("使用知识库")
        model_row.addWidget(self.kb_check)
        layout.addLayout(model_row)
        self.display = QTextEdit()
        self.display.setReadOnly(True)
        self.display.setPlaceholderText("对话内容将显示在这里。")
        layout.addWidget(self.display, 1)
        composer = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("向 ModelForge 发送消息…")
        self.msg_input.returnPressed.connect(self.send_message)
        composer.addWidget(self.msg_input, 1)
        examples = QPushButton("示例")
        examples.clicked.connect(
            lambda: open_examples(
                "chat", self, lambda example: self.msg_input.setText(example.template)
            )
        )
        composer.addWidget(examples)
        self.send_btn = QPushButton("发送")
        self.send_btn.setProperty("accent", True)
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setEnabled(False)
        composer.addWidget(self.send_btn)
        layout.addLayout(composer)

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
            self.chat_status.set_state(format_text("已选择 {name}", name=provider["name"]), "online")
        else:
            self.load_btn.setText("使用模型")
            self.chat_status.set_state("未选择模型", "warning")

    def _render_readiness(self, snapshot: dict) -> None:
        if not isinstance(snapshot, dict):
            return
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
        self.send_btn.setEnabled(self._model_ready)
        self.chat_status.set_state(
            "模型已就绪" if self._model_ready else "请先配置可用模型",
            "online" if self._model_ready else "warning",
        )

    def set_session(self, session_id):
        self.session_id = session_id
        self.display.clear()
        self.messages = []
        self.display.append("[Loading conversation…]")
        self._run_api(
            lambda: self.api.list_messages(session_id),
            lambda messages: self._render_session(session_id, messages),
            self._session_load_failed,
        )

    def _render_session(self, session_id, messages):
        if session_id != self.session_id:
            return
        self.display.clear()
        self.messages = []
        for message in messages:
            self._append_msg(message["role"], message["content"])
            self.messages.append(
                {"role": message["role"], "content": message["content"]}
            )

    def _session_load_failed(self, error):
        self.display.append(f"[会话加载未完成] {format_api_error(error)}")

    def load_model(self):
        if not self._model_ready:
            QMessageBox.information(self, "模型尚未就绪", "请先在模型工作区完成模型配置或远程服务验证。")
            return
        model = self.model_input.text().strip()
        if not model:
            QMessageBox.warning(
                self, "请选择模型", "请输入模型名称，或选择已配置的远程模型服务。"
            )
            return
        provider = self._provider()
        if provider:
            self.chat_status.set_state(f"{provider['name']} · {model}", "online")
            self.display.append(
                "<p><b>Remote provider ready</b><br>Messages will be sent through the selected OpenAI-compatible provider.</p>"
            )
            return
        self.load_btn.setEnabled(False)
        self.display.append("<p><b>Preparing local model…</b></p>")
        self._run_api(
            lambda: self.api.runtime_start(model),
            lambda _result: self._model_loaded(model),
            self._model_load_failed,
        )

    def _model_loaded(self, model):
        self.load_btn.setEnabled(True)
        self.chat_status.set_state(f"{model} ready", "online")
        self.display.append(
            "<p><b>Model ready</b><br>Start a conversation when you are ready.</p>"
        )

    def _model_load_failed(self, error):
        self.load_btn.setEnabled(True)
        QMessageBox.warning(self, "无法加载模型", format_api_error(error))

    def _append_msg(self, role, content):
        name = "你" if role == "user" else "ModelForge"
        self.display.append(f"<p><b>{name}</b><br>{content}</p>")

    def send_message(self):
        text, model = self.msg_input.text().strip(), self.model_input.text().strip()
        if not self._model_ready:
            QMessageBox.information(self, "模型尚未就绪", "请先在模型工作区配置并验证一个可用模型。")
            return
        if not text:
            return
        if not model:
            QMessageBox.warning(
                self, "请选择模型", "Enter a model name before sending a message."
            )
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
        self.send_btn.setEnabled(False)
        if self.kb_check.isChecked():
            self._run_api(
                lambda: self.api.knowledge_answer(model, text, top_k=3),
                self._show_kb_answer,
                self._show_kb_failure,
            )
            return
        self.display.append("<p><b>ModelForge</b><br>")
        self.display.moveCursor(QTextCursor.End)
        self.worker = StreamWorker(
            self.api, model, self.messages, self.session_id, provider_id
        )
        self.worker.delta.connect(self._on_delta)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _show_kb_answer(self, result):
        answer = result.get("answer", "")
        self.display.append(f"<b>ModelForge</b><br>{answer}<br>")
        for source in result.get("sources", []):
            self.display.append(
                f"<span>[Source: {source.get('source')} @ {source.get('score', 0)}]</span><br>"
            )
        self.messages.append({"role": "assistant", "content": answer})
        self.send_btn.setEnabled(True)

    def _show_kb_failure(self, error):
        self.display.append(f"<b>Unable to answer</b><br>{error}<br>")
        self.send_btn.setEnabled(True)

    def _on_delta(self, chunk):
        cursor = self.display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.display.setTextCursor(cursor)
        self.display.insertPlainText(chunk)
        self.display.verticalScrollBar().setValue(
            self.display.verticalScrollBar().maximum()
        )

    def _on_done(self, full):
        self.display.append("</p>")
        self.messages.append({"role": "assistant", "content": full})
        self.send_btn.setEnabled(True)
        if self.session_id:
            self._run_api(
                lambda: self.api.auto_title(self.session_id),
                lambda _result: (
                    self.session_refresher() if self.session_refresher else None
                ),
                lambda _error: None,
            )

    def _on_failed(self, error):
        self.display.append(f"<br><b>Unable to respond</b><br>{error}</p>")
        self.send_btn.setEnabled(True)

    def shutdown_stream(self) -> None:
        worker = self.worker
        self.worker = None
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.wait(2500)
        self.shutdown_async_api()
