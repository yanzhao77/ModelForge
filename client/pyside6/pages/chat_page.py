"""Responsive chat page with background REST calls and dedicated SSE worker."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget


class StreamWorker(QThread):
    delta = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, api, model, messages, session_id):
        super().__init__()
        self.api = api
        self.model = model
        self.messages = messages
        self.session_id = session_id

    def run(self):
        full = ""
        try:
            for event in self.api.stream_chat(self.model, self.messages, self.session_id):
                kind = event.get("type")
                if kind == "delta":
                    content = event.get("data", "")
                    full += content
                    self.delta.emit(content)
                elif kind == "done":
                    self.done.emit(full)
                    return
                elif kind == "error":
                    self.failed.emit(event.get("data", "服务返回错误"))
                    return
            self.done.emit(full)
        except Exception as exc:
            self.failed.emit(str(exc))


class ChatPage(QWidget, AsyncApiMixin):
    """Streaming chat page whose REST operations never block Qt's event loop."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.session_id = None
        self.messages = []
        self.worker = None
        self.session_refresher = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("模型:"))
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("模型名（Ollama 模型 或 已注册模型名）")
        top.addWidget(self.model_input)
        self.load_btn = QPushButton("加载")
        self.load_btn.clicked.connect(self.load_model)
        top.addWidget(self.load_btn)
        self.kb_check = QCheckBox("知识库(RAG)")
        top.addWidget(self.kb_check)
        top.addStretch()
        layout.addLayout(top)

        self.display = QTextEdit()
        self.display.setReadOnly(True)
        self.display.setStyleSheet("background-color: #fafafa; border: 1px solid #ddd; padding: 8px;")
        layout.addWidget(self.display, 1)

        bottom = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("输入消息，Enter 发送...")
        self.msg_input.returnPressed.connect(self.send_message)
        bottom.addWidget(self.msg_input)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_message)
        bottom.addWidget(self.send_btn)
        layout.addLayout(bottom)

    def set_session(self, session_id):
        self.session_id = session_id
        self.display.clear()
        self.messages = []
        self.display.append("[正在加载会话消息…]")
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
            self.messages.append({"role": message["role"], "content": message["content"]})

    def _session_load_failed(self, error):
        self.display.append(f"[加载消息失败] {error}")

    def load_model(self):
        model = self.model_input.text().strip()
        if not model:
            QMessageBox.warning(self, "提示", "请输入模型名")
            return
        self.load_btn.setEnabled(False)
        self.display.append("<b style='color:#1565C0'>[系统]</b> 正在加载模型…<br>")
        self._run_api(lambda: self.api.runtime_start(model), lambda _result: self._model_loaded(model), self._model_load_failed)

    def _model_loaded(self, model):
        self.load_btn.setEnabled(True)
        self.display.append(f"<b style='color:#4CAF50'>[系统]</b> 模型已加载: {model}<br>")

    def _model_load_failed(self, error):
        self.load_btn.setEnabled(True)
        QMessageBox.warning(self, "加载失败", error)

    def _append_msg(self, role, content):
        color = "#2196F3" if role == "user" else "#4CAF50"
        name = "用户" if role == "user" else "助手"
        self.display.append(f"<div style='margin:6px 0'><b style='color:{color}'>{name}:</b> {content}</div>")

    def send_message(self):
        text = self.msg_input.text().strip()
        model = self.model_input.text().strip()
        if not text:
            return
        if not model:
            QMessageBox.warning(self, "提示", "请先填写模型名")
            return
        if self.worker and self.worker.isRunning():
            return
        self._append_msg("user", text)
        self.messages.append({"role": "user", "content": text})
        self.msg_input.clear()
        self.send_btn.setEnabled(False)
        if self.kb_check.isChecked():
            self._run_api(lambda: self.api.knowledge_answer(model, text, top_k=3), self._show_kb_answer, self._show_kb_failure)
            return
        self.display.append("<b style='color:#4CAF50'>助手:</b> ")
        self.display.moveCursor(self.display.textCursor().End)
        self.worker = StreamWorker(self.api, model, self.messages, self.session_id)
        self.worker.delta.connect(self._on_delta)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _show_kb_answer(self, result):
        answer = result.get("answer", "")
        self.display.append(f"<b style='color:#4CAF50'>助手:</b> {answer}<br>")
        for source in result.get("sources", []):
            self.display.append(f"<span style='color:#888'>[来源: {source.get('source')} @{source.get('score', 0)}]</span><br>")
        self.messages.append({"role": "assistant", "content": answer})
        self.send_btn.setEnabled(True)

    def _show_kb_failure(self, error):
        self.display.append(f"<b style='color:#FF5722'>[错误]</b> {error}<br>")
        self.send_btn.setEnabled(True)

    def _on_delta(self, chunk):
        cursor = self.display.textCursor()
        cursor.movePosition(cursor.End)
        self.display.setTextCursor(cursor)
        self.display.insertPlainText(chunk)
        scrollbar = self.display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_done(self, full):
        self.display.append("<br>")
        self.messages.append({"role": "assistant", "content": full})
        self.send_btn.setEnabled(True)
        if self.session_id:
            self._run_api(lambda: self.api.auto_title(self.session_id), lambda _result: self.session_refresher() if self.session_refresher else None, lambda _error: None)

    def _on_failed(self, error):
        self.display.append(f"<b style='color:#FF5722'>[错误]</b> {error}<br>")
        self.send_btn.setEnabled(True)
