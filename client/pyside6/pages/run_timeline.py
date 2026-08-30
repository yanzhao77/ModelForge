"""RunTimeline: live agent run event stream rendered as a timeline (spec 50 / 51).

Shows ONLY real events from the backend (spec 51 forbids fake thinking
labels). While the model is generating without reasoning events, the UI
shows "Generating...".
All markup colors resolve from the active theme palette so light and dark
modes stay readable; no hardcoded hex colors are emitted.
"""
import json

from components.api_worker import AsyncApiMixin, safe_api_error_text
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from theme.tokens import FONT_MONO, LIGHT


class EventStreamWorker(QThread):
    """Consumes the agent run SSE stream in a background thread."""

    event_received = Signal(dict)
    failed = Signal(str)
    finished_run = Signal(str)

    def __init__(self, api, run_id, after_sequence=0):
        super().__init__()
        self.api = api
        self.run_id = run_id
        self.after_sequence = after_sequence

    def run(self):
        try:
            for event in self.api.stream_agent_run(self.run_id, after_sequence=self.after_sequence):
                self.event_received.emit(event)
                if event.get("event_type") in ("run.completed", "run.failed", "run.cancelled", "run.timeout"):
                    self.finished_run.emit(event.get("event_type", ""))
                    return
        except Exception as e:
            self.failed.emit(safe_api_error_text(e))


def _timeline_palette(widget: QWidget) -> dict:
    """Resolve the active application palette for theme-aware markup."""
    window = widget.window()
    manager = getattr(window, "theme_manager", None)
    if manager is not None:
        try:
            return manager.palette()
        except Exception:
            pass
    return LIGHT


class ToolCallCard(QFrame):
    """One tool call card: name, arguments, result (spec 50).

    The timeline renders cards as theme-aware HTML inside its QTextBrowser,
    so ``str(card)`` intentionally returns markup instead of an object repr.
    """

    def __init__(self, tool_name: str, arguments: dict, output: str = "", palette: dict | None = None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._palette = palette or LIGHT
        self._tool_name = tool_name
        self._arguments = arguments or {}
        self._output = output or ""

    def to_html(self) -> str:
        p = self._palette
        html = f"<b style='color:{p['text']}'>{self._tool_name}</b>"
        if self._arguments:
            html += (
                f"<br><span style='color:{p['muted']}'>参数: "
                f"{json.dumps(self._arguments, ensure_ascii=False)}</span>"
            )
        if self._output:
            html += f"<br><span style='color:{p['success']}'>结果: {self._output[:300]}</span>"
        return html

    def __str__(self) -> str:
        return self.to_html()


class RunTimeline(QWidget, AsyncApiMixin):
    """Renders the event stream of one run as a timeline (spec 26 / 50)."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.run_id = None
        self.worker = None
        self._approval_pending = False
        self.approve_btn = None
        self.reject_btn = None
        self._init_ui()
    def _init_ui(self):
        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setStyleSheet(f"font-family: {FONT_MONO};")
        lay.addWidget(self.view, 1)
        controls = QHBoxLayout()
        self.approve_btn = QPushButton("批准")
        self.approve_btn.setVisible(False)
        self.approve_btn.clicked.connect(self.approve)
        controls.addWidget(self.approve_btn)
        self.reject_btn = QPushButton("拒绝")
        self.reject_btn.setVisible(False)
        self.reject_btn.clicked.connect(self.reject)
        controls.addWidget(self.reject_btn)
        controls.addStretch()
        lay.addLayout(controls)

    def watch(self, run_id: str, after_sequence: int = 0):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.quit()
        self.run_id = run_id
        self.view.clear()
        self.view.append(f"<b>Run #{run_id[:8]}</b>")
        self.approve_btn.setVisible(False)
        self.reject_btn.setVisible(False)
        self.worker = EventStreamWorker(self.api, run_id, after_sequence)
        self.worker.event_received.connect(self._on_event)
        self.worker.failed.connect(lambda e: self.view.append(f"<span style='color:{_timeline_palette(self)['danger']}'>[错误] {e}</span>"))
        self.worker.finished_run.connect(lambda _: self.view.append(f"<b style='color:{_timeline_palette(self)['success']}'>✔ 运行结束</b>"))
        self.worker.start()

    def _on_event(self, event: dict):
        p = _timeline_palette(self)
        etype = event.get("event_type", "")
        ts = (event.get("timestamp") or "")[11:19]
        payload = event.get("payload") or {}
        if etype == "run.started":
            self.view.append(f"<span style='color:{p['text']}'>▶ {ts} 运行开始</span>")
        elif etype == "run.created":
            self.view.append(f"<span style='color:{p['muted']}'>· {ts} 运行已创建</span>")
        elif etype == "model.request.started":
            # spec 51: no fake thinking labels - show Generating on real LLM work
            self.view.append(f"<span style='color:{p['text']}'>▸ {ts} LLM Generating...</span>")
        elif etype == "model.request.completed":
            usage = payload.get("usage") or {}
            self.view.append(f"<span style='color:{p['muted']}'>◂ {ts} LLM 完成（tokens={usage.get('total_tokens', 0)}）</span>")
        elif etype == "tool.call.started":
            self.view.append(f"<span style='color:{p['warning']}'>▸ {ts} 工具 {payload.get('tool', '?')} 执行中</span>")
        elif etype == "tool.call.completed":
            self.view.append(f"<span style='color:{p['success']}'>   ✔ {ts} 工具结果（{payload.get('duration', 0)}s）</span>")
            self._append_tool_card(payload)
        elif etype == "tool.call.failed":
            self.view.append(f"<span style='color:{p['danger']}'>   ✘ {ts} 工具失败: {payload.get('error', '')}</span>")
        elif etype == "human.approval.required":
            self.view.append(f"<span style='color:{p['warning']}'>? {ts} 需要人工批准: {payload.get('tool', '?')}</span>")
            self.approve_btn.setVisible(True)
            self.reject_btn.setVisible(True)
        elif etype == "human.approval.granted":
            self.view.append(f"<span style='color:{p['success']}'>✔ {ts} 已批准</span>")
            self.approve_btn.setVisible(False)
            self.reject_btn.setVisible(False)
        elif etype == "human.approval.denied":
            self.view.append(f"<span style='color:{p['danger']}'>✘ {ts} 已拒绝</span>")
            self.approve_btn.setVisible(False)
            self.reject_btn.setVisible(False)
        elif etype == "agent.response":
            self.view.append(f"<span style='color:{p['accent']}'>{ts} {payload.get('content', '')[:200]}</span>")
        elif etype == "run.completed":
            self.view.append(f"<span style='color:{p['success']}'>■ {ts} 已完成（{payload.get('duration', 0)}s）</span>")
        elif etype in ("run.failed", "run.timeout"):
            self.view.append(f"<span style='color:{p['danger']}'>■ {ts} {etype} - {payload.get('error', '')}</span>")
        elif etype == "run.cancelled":
            self.view.append(f"<span style='color:{p['muted']}'>■ {ts} 已取消</span>")
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_tool_card(self, payload: dict):
        card = ToolCallCard(
            payload.get("tool", "?"),
            payload.get("arguments") or {},
            payload.get("output", ""),
            palette=_timeline_palette(self),
        )
        self.view.append("")
        self.view.append(str(card))

    def approve(self):
        self._submit_approval(True)

    def reject(self):
        self._submit_approval(False)

    def _submit_approval(self, approved: bool):
        if not self.run_id or self._approval_pending:
            return
        run_id = self.run_id
        self._approval_pending = True
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        action = "批准" if approved else "拒绝"
        self.view.append(f"<span style='color:{_timeline_palette(self)['accent']}'>[正在{action}] Run #{run_id[:8]}</span>")
        operation = self.api.approve_agent_run if approved else self.api.reject_agent_run
        self._run_api(
            lambda: operation(run_id),
            lambda _result: self._approval_finished(run_id, action),
            lambda error: self._approval_failed(run_id, action, error),
        )

    def _approval_finished(self, run_id: str, action: str):
        self._approval_pending = False
        if run_id != self.run_id:
            return
        self.view.append(f"<span style='color:{_timeline_palette(self)['success']}'>[已{action}] 等待服务事件确认</span>")
        self.approve_btn.setVisible(False)
        self.reject_btn.setVisible(False)

    def _approval_failed(self, run_id: str, action: str, error: str):
        self._approval_pending = False
        if run_id != self.run_id:
            return
        self.view.append(f"<span style='color:{_timeline_palette(self)['danger']}'>[{action}失败] {format_api_error(error)}</span>")
        self.approve_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)

    def shutdown_stream(self) -> None:
        """Join an active agent-run event stream before destruction."""
        worker = self.worker
        self.worker = None
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.wait(2500)
        self.shutdown_async_api()
