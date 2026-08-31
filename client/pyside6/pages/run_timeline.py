from __future__ import annotations

import json

from components.api_worker import AsyncApiMixin, safe_api_error_text
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class EventStreamWorker(QThread):
    """Consumes the agent-run SSE stream outside the GUI event loop."""

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
            for event in self.api.stream_agent_run(
                self.run_id,
                after_sequence=self.after_sequence,
                cancel_event=self.interruption_requested,
            ):
                if self.isInterruptionRequested():
                    return
                self.event_received.emit(event)
                if event.get("event_type") in ("run.completed", "run.failed", "run.cancelled", "run.timeout"):
                    self.finished_run.emit(str(event.get("event_type", "")))
                    return
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(safe_api_error_text(exc))

    def interruption_requested(self) -> bool:
        return self.isInterruptionRequested()


class RunTimeline(QWidget, AsyncApiMixin):
    """Renders trusted labels and untrusted event data as plain-text timeline rows."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.run_id = None
        self.worker = None
        self._approval_pending = False
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setAccessibleName("Agent Run 事件时间线")
        self.view.setPlaceholderText("选择一个运行记录后，将在此显示事件。")
        lay.addWidget(self.view, 1)
        controls = QHBoxLayout()
        self.approve_btn = QPushButton("批准")
        self.approve_btn.setAccessibleName("批准当前待审工具调用")
        self.approve_btn.setVisible(False)
        self.approve_btn.clicked.connect(self.approve)
        controls.addWidget(self.approve_btn)
        self.reject_btn = QPushButton("拒绝")
        self.reject_btn.setAccessibleName("拒绝当前待审工具调用")
        self.reject_btn.setVisible(False)
        self.reject_btn.clicked.connect(self.reject)
        controls.addWidget(self.reject_btn)
        controls.addStretch()
        lay.addLayout(controls)

    def _append(self, line: str) -> None:
        self.view.appendPlainText(line)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def watch(self, run_id: str, after_sequence: int = 0):
        self.stop_stream()
        self.run_id = run_id
        self.view.clear()
        self._append(f"运行 #{run_id[:8]}")
        self.approve_btn.setVisible(False)
        self.reject_btn.setVisible(False)
        self.worker = EventStreamWorker(self.api, run_id, after_sequence)
        self.worker.event_received.connect(self._on_event)
        self.worker.failed.connect(lambda error: self._append(f"错误：{format_api_error(error)}"))
        self.worker.finished_run.connect(lambda _event: self._append("运行结束"))
        self.worker.start()

    def _on_event(self, event: dict):
        etype = str(event.get("event_type", ""))
        ts = str(event.get("timestamp") or "")[11:19] or "--:--:--"
        payload = event.get("payload") or {}
        if etype == "run.started":
            self._append(f"{ts} 运行已启动")
        elif etype == "run.created":
            self._append(f"{ts} 运行已创建")
        elif etype == "model.request.started":
            self._append(f"{ts} 正在生成回复")
        elif etype == "model.request.completed":
            usage = payload.get("usage") or {}
            self._append(f"{ts} 模型请求完成（令牌 {usage.get('total_tokens', 0)}）")
        elif etype == "tool.call.started":
            self._append(f"{ts} 工具调用开始：{payload.get('tool', '?')}")
        elif etype == "tool.call.completed":
            self._append(f"{ts} 工具调用完成（{payload.get('duration', 0)} 秒）")
            self._append_tool_summary(payload)
        elif etype == "tool.call.failed":
            self._append(f"{ts} 工具调用失败：{payload.get('error', '')}")
        elif etype == "human.approval.required":
            self._append(f"{ts} 等待人工批准：{payload.get('tool', '?')}")
            self.approve_btn.setVisible(True)
            self.reject_btn.setVisible(True)
        elif etype == "human.approval.granted":
            self._append(f"{ts} 已批准")
            self.approve_btn.setVisible(False)
            self.reject_btn.setVisible(False)
        elif etype == "human.approval.denied":
            self._append(f"{ts} 已拒绝")
            self.approve_btn.setVisible(False)
            self.reject_btn.setVisible(False)
        elif etype == "agent.response":
            self._append(f"{ts} Agent 回复：{str(payload.get('content', ''))[:200]}")
        elif etype == "run.completed":
            self._append(f"{ts} 运行完成（{payload.get('duration', 0)} 秒）")
        elif etype in ("run.failed", "run.timeout"):
            self._append(f"{ts} 运行失败：{payload.get('error', '')}")
        elif etype == "run.cancelled":
            self._append(f"{ts} 运行已取消")

    def _append_tool_summary(self, payload: dict):
        tool_name = str(payload.get("tool", "?"))
        arguments = json.dumps(payload.get("arguments") or {}, ensure_ascii=False)
        output = str(payload.get("output", ""))[:300]
        self._append(f"  工具：{tool_name}")
        if arguments != "{}":
            self._append(f"  参数：{arguments}")
        if output:
            self._append(f"  结果：{output}")

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
        self._append(f"正在{action}运行 #{run_id[:8]}")
        operation = self.api.approve_agent_run if approved else self.api.reject_agent_run
        self._run_api(
            lambda: operation(run_id, confirm=True),
            lambda _result: self._approval_finished(run_id, action),
            lambda error: self._approval_failed(run_id, action, error),
            request_key="run-approval",
        )

    def _approval_finished(self, run_id: str, action: str):
        self._approval_pending = False
        if run_id != self.run_id:
            return
        self._append(f"已{action}，等待服务事件确认。")
        self.approve_btn.setVisible(False)
        self.reject_btn.setVisible(False)

    def _approval_failed(self, run_id: str, action: str, error: str):
        self._approval_pending = False
        if run_id != self.run_id:
            return
        self._append(f"{action}失败：{format_api_error(error)}")
        self.approve_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)

    def stop_stream(self):
        worker = self.worker
        self.worker = None
        if worker and worker.isRunning():
            worker.requestInterruption()
        return worker

    def shutdown_stream(self) -> None:
        worker = self.stop_stream()
        if worker and worker.isRunning():
            worker.wait(2500)
        self.shutdown_async_api()
