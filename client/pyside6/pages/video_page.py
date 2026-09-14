"""Desktop video generation workflow."""
from __future__ import annotations

import uuid

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFSection, MFStatusBadge
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class VideoPage(QWidget, AsyncApiMixin):
    """Text-to-video page backed by the /v1/videos API."""

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._current_job: dict | None = None
        self._video_bytes: bytes | None = None
        self._busy = False
        self._init_ui()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_job)
        self.refresh_models()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(MFSection("视频生成", "CogVideoX / Local Video"))
        header.addStretch(1)
        self.state = MFStatusBadge("未提交", "warning")
        header.addWidget(self.state)
        self.refresh_btn = QPushButton("刷新模型")
        self.refresh_btn.clicked.connect(self.refresh_models)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        controls = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(280)
        controls.addWidget(QLabel("模型"))
        controls.addWidget(self.model_combo, 1)
        self.steps = QSpinBox()
        self.steps.setRange(1, 50)
        self.steps.setValue(30)
        controls.addWidget(QLabel("步数"))
        controls.addWidget(self.steps)
        self.seed_enabled = QCheckBox("固定种子")
        controls.addWidget(self.seed_enabled)
        self.seed = QSpinBox()
        self.seed.setRange(-2_147_483_648, 2_147_483_647)
        self.seed.setValue(42)
        controls.addWidget(self.seed)
        layout.addLayout(controls)

        profile = QLabel("Profile: 6s · 8 FPS · 720x480 · 49 frames")
        profile.setProperty("role", "muted")
        layout.addWidget(profile)

        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("输入视频提示词。提示词不会显示在任务中心或公开视频响应中。")
        self.prompt.setMinimumHeight(140)
        layout.addWidget(self.prompt)

        actions = QHBoxLayout()
        self.generate_btn = QPushButton("生成")
        self.generate_btn.clicked.connect(self.generate)
        actions.addWidget(self.generate_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        actions.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("保存 MP4")
        self.save_btn.clicked.connect(self.save_video)
        self.save_btn.setEnabled(False)
        actions.addWidget(self.save_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status = QLabel("正在读取视频模型…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("作业状态会显示在这里。")
        layout.addWidget(self.output, 1)

    def _set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.refresh_btn.setEnabled(not busy)
        self.generate_btn.setEnabled(not busy and self.model_combo.count() > 0)

    def refresh_models(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在同步视频模型…")
        self._run_api(self.api.list_openai_models, self._models_loaded, self._operation_failed, request_key="video.models")

    def _models_loaded(self, models: list[dict]) -> None:
        self._set_busy(False)
        self.model_combo.clear()
        unavailable = 0
        for model in models:
            meta = model.get("modelforge") or {}
            if "video_generation" not in meta.get("capabilities", []):
                continue
            if meta.get("readiness") != "ready":
                unavailable += 1
                continue
            label = f"{model.get('id')} · {meta.get('readiness', 'unknown')}"
            self.model_combo.addItem(label, model.get("id"))
        self.status.setText(f"已同步 {self.model_combo.count()} 个可用视频模型；{unavailable} 个尚未就绪。")
        self.generate_btn.setEnabled(self.model_combo.count() > 0)
        self.state.set_state("模型已同步", "online" if self.model_combo.count() else "warning")

    def generate(self) -> None:
        model = self.model_combo.currentData()
        prompt = self.prompt.toPlainText().strip()
        if not model:
            QMessageBox.information(self, "视频生成", "没有可用的视频模型。")
            return
        if not prompt:
            QMessageBox.information(self, "视频生成", "请输入提示词。")
            return
        self._video_bytes = None
        self.save_btn.setEnabled(False)
        self._set_busy(True)
        self.status.setText("正在提交视频任务…")
        seed = self.seed.value() if self.seed_enabled.isChecked() else None
        key = uuid.uuid4().hex
        self._run_api(
            lambda: self.api.create_video(
                model=model,
                prompt=prompt,
                seconds=6,
                fps=8,
                size="720x480",
                num_inference_steps=self.steps.value(),
                seed=seed,
                idempotency_key=key,
            ),
            self._submitted,
            self._operation_failed,
            request_key="video.submit",
        )

    def _submitted(self, job: dict) -> None:
        self._current_job = job
        self._set_busy(False)
        self.cancel_btn.setEnabled(job.get("status") in {"queued", "processing"})
        self._render_job(job)
        self._poll.start(1000)

    def _poll_job(self) -> None:
        if not self._current_job:
            self._poll.stop()
            return
        video_id = self._current_job.get("id")
        self._run_api(lambda: self.api.get_video(video_id), self._job_updated, self._operation_failed, request_key="video.poll")

    def _job_updated(self, job: dict) -> None:
        self._current_job = job
        self._render_job(job)
        status = job.get("status")
        self.cancel_btn.setEnabled(status in {"queued", "processing"})
        if status in {"completed", "failed", "cancelled"}:
            self._poll.stop()
        if status == "completed":
            self._run_api(lambda: self.api.download_video_content(job["id"]), self._video_loaded, self._operation_failed, request_key="video.content")

    def _render_job(self, job: dict) -> None:
        status = str(job.get("status") or "unknown")
        progress = job.get("progress", 0)
        self.status.setText(f"{job.get('id')} · {status} · {progress}% · {job.get('phase', '')}")
        badge_state = "online" if status == "completed" else "error" if status in {"failed", "cancelled"} else "warning"
        self.state.set_state(status.upper(), badge_state)
        self.output.setPlainText(str(job))

    def _video_loaded(self, content: bytes) -> None:
        self._video_bytes = content
        self.save_btn.setEnabled(bool(content))
        self.status.setText("视频已完成并可保存。")

    def cancel(self) -> None:
        if not self._current_job:
            return
        video_id = self._current_job.get("id")
        self.cancel_btn.setEnabled(False)
        self._run_api(lambda: self.api.cancel_video(video_id), self._job_updated, self._operation_failed, request_key="video.cancel")

    def save_video(self) -> None:
        if not self._video_bytes or not self._current_job:
            return
        path, _filter = QFileDialog.getSaveFileName(self, "保存视频", f"{self._current_job.get('id')}.mp4", "MP4 Video (*.mp4)")
        if not path:
            return
        with open(path, "wb") as handle:
            handle.write(self._video_bytes)
        self.status.setText(f"已保存：{path}")

    def _operation_failed(self, error: str) -> None:
        self._set_busy(False)
        self.status.setText(f"视频操作失败：{error}")
        self.state.set_state("失败", "error")

    def closeEvent(self, event) -> None:
        self._poll.stop()
        self.shutdown_async_api()
        super().closeEvent(event)
