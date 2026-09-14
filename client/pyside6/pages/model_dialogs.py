"""Model inventory and download dialogs with non-blocking API operations."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from i18n.ui_localizer import current, format_api_error, localize_tree, text
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ModelCenterDialog(QDialog, AsyncApiMixin):
    def __init__(self, api, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._busy = False
        self.setWindowTitle("模型中心")
        self.resize(640, 460)
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.scan_path = QLineEdit()
        self.scan_path.setPlaceholderText("扫描路径（留空使用默认模型目录）")
        row.addWidget(self.scan_path)
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.clicked.connect(self.scan)
        row.addWidget(self.scan_btn)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        layout.addLayout(row)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "提供方", "大小", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        self.install_btn = QPushButton("登记模型…")
        self.install_btn.clicked.connect(self.install)
        controls.addWidget(self.install_btn)
        self.remove_btn = QPushButton("删除选中")
        self.remove_btn.clicked.connect(self.remove)
        controls.addWidget(self.remove_btn)
        controls.addStretch()
        layout.addLayout(controls)
        self.status = QLabel("正在加载模型…")
        layout.addWidget(self.status)

    def _set_busy(self, busy):
        self._busy = busy
        for button in (self.scan_btn, self.refresh_btn, self.install_btn, self.remove_btn):
            button.setEnabled(not busy)

    def refresh(self):
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在同步模型库存…")
        self._run_api(self.api.list_models, self._render_models, lambda error: self._failed("同步模型库存", error))

    def _render_models(self, models):
        self._set_busy(False)
        self.table.setRowCount(len(models))
        for row, model in enumerate(models):
            for column, key in enumerate(["id", "name", "provider", "size", "status"]):
                self.table.setItem(row, column, QTableWidgetItem(str(model.get(key, ""))))
            self.table.item(row, 0).setData(Qt.UserRole, model.get("id"))
        self.status.setText(f"模型库存已更新 · {len(models)} 项。")

    def scan(self):
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在扫描本地模型…")
        self._run_api(lambda: self.api.scan_models(self.scan_path.text().strip() or None), self._scanned, lambda error: self._failed("扫描模型", error))

    def _scanned(self, models):
        self._set_busy(False)
        self.status.setText(f"扫描完成 · 发现 {len(models)} 个模型。")
        self.refresh()

    def install(self):
        name, ok1 = QInputDialog.getText(self, "登记模型", "模型名称:")
        if not ok1 or not name.strip():
            return
        path, ok2 = QInputDialog.getText(self, "登记模型", "模型路径:")
        if not ok2 or not path.strip():
            return
        self._set_busy(True)
        self.status.setText("正在登记模型…")
        self._run_api(lambda: self.api.install_model(name.strip(), "local", path.strip()), lambda _result: self._installed(name.strip()), lambda error: self._failed("登记模型", error))

    def _installed(self, name):
        self._set_busy(False)
        self.status.setText(f"已登记模型：{name}。")
        self.refresh()

    def remove(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选择模型记录。")
            return
        model_id = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        if QMessageBox.question(self, "确认", "删除该模型记录？") != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.status.setText("正在删除模型记录…")
        self._run_api(lambda: self.api.remove_model(model_id), lambda _result: self._removed(), lambda error: self._failed("删除模型记录", error))

    def _removed(self):
        self._set_busy(False)
        self.status.setText("模型记录已删除。")
        self.refresh()

    def _failed(self, action, error):
        self._set_busy(False)
        self.status.setText(f"{action}失败：{format_api_error(error)}")
        QMessageBox.warning(self, action, format_api_error(error))


class DownloadDialog(QDialog, AsyncApiMixin):
    def __init__(self, api, parent=None, task_id: str | None = None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._task_id = task_id
        self._busy = False
        self._polling = False
        self.setWindowTitle("GGUF 模型下载器")
        self.resize(720, 520)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._init_ui()
        self._update_task_controls()
        if self._task_id:
            self._timer.start(1000)
            self._poll()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.author_combo = QComboBox()
        self.author_combo.addItem("所有作者", None)
        for author in ["TheBloke", "lmstudio-community", "QuantFactory", "bartowski", "mradermacher"]:
            self.author_combo.addItem(author, author)
        row.addWidget(QLabel("作者:"))
        row.addWidget(self.author_combo)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 GGUF 模型...")
        self.search_input.returnPressed.connect(self.search)
        row.addWidget(self.search_input, 1)
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.search)
        row.addWidget(self.search_btn)
        layout.addLayout(row)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["模型", "作者", "下载量", "ID"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.status = QLabel("就绪")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("下载进度：%p%")
        layout.addWidget(self.progress)
        self.download_btn = QPushButton("下载选中模型")
        self.download_btn.clicked.connect(self.download)
        layout.addWidget(self.download_btn)
        task_controls = QHBoxLayout()
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.pause_download)
        task_controls.addWidget(self.pause_btn)
        self.resume_btn = QPushButton("继续")
        self.resume_btn.clicked.connect(self.resume_download)
        task_controls.addWidget(self.resume_btn)
        self.restart_btn = QPushButton("重新开始")
        self.restart_btn.clicked.connect(self.restart_download)
        task_controls.addWidget(self.restart_btn)
        task_controls.addStretch()
        layout.addLayout(task_controls)

    def _set_busy(self, busy):
        self._busy = busy
        self.search_btn.setEnabled(not busy)
        self.download_btn.setEnabled(not busy)
        self._update_task_controls()

    def _update_task_controls(self, status: str | None = None):
        has_task = bool(self._task_id)
        active = status in {"PENDING", "RUNNING"} if status else has_task
        paused = status == "PAUSED"
        terminal = status in {"COMPLETED", "FAILED", "CANCELLED"}
        self.pause_btn.setEnabled(has_task and active and not self._busy)
        self.resume_btn.setEnabled(has_task and paused and not self._busy)
        self.restart_btn.setEnabled(has_task and not self._busy and (active or paused or terminal))

    def search(self):
        if self._busy:
            return
        query = self.search_input.text().strip()
        author = self.author_combo.currentData()
        self._set_busy(True)
        self.status.setText("正在搜索 GGUF 模型…")
        self._run_api(lambda: self.api.search_models(query, author, 20), self._render_results, lambda error: self._failed("搜索模型", error))

    def _render_results(self, results):
        self._set_busy(False)
        self.table.setRowCount(len(results))
        for row, model in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(str(model.get("id", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(str(model.get("author", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(model.get("downloads", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(str(model.get("id", ""))))
        self.status.setText(f"找到 {len(results)} 个模型。")

    def download(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return
        if self._busy:
            return
        repo_id = self.table.item(rows[0].row(), 3).text()
        self._set_busy(True)
        self.status.setText(f"正在创建下载任务：{repo_id}…")
        self._run_api(lambda: self.api.download_model(repo_id), lambda task: self._download_started(repo_id, task), lambda error: self._failed("创建下载任务", error))

    def _download_started(self, repo_id, task):
        self._set_busy(False)
        self._task_id = task["task_id"]
        self.status.setText(f"已开始下载：{repo_id}")
        self.progress.setValue(int(task.get("progress") or 0))
        self._update_task_controls(task.get("status"))
        self._timer.start(1000)

    def pause_download(self):
        if not self._task_id or self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在暂停下载…")
        self._run_api(lambda: self.api.pause_download(self._task_id), self._apply_download_status, lambda error: self._failed("暂停下载", error))

    def resume_download(self):
        if not self._task_id or self._busy:
            return
        self._set_busy(True)
        self.status.setText("正在继续下载…")
        self._run_api(lambda: self.api.resume_download(self._task_id), self._apply_download_status, lambda error: self._failed("继续下载", error))

    def restart_download(self):
        if not self._task_id or self._busy:
            return
        if QMessageBox.question(self, "确认", "重新开始会重新校验已下载文件，只重新下载损坏或未完成的部分，继续吗？") != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.status.setText("正在重新开始下载…")
        self._run_api(lambda: self.api.restart_download(self._task_id), self._restart_started, lambda error: self._failed("重新开始下载", error))

    def _restart_started(self, task):
        self._set_busy(False)
        self._task_id = task["task_id"]
        self.progress.setValue(int(task.get("progress") or 0))
        self.status.setText(f"已重新开始：{task.get('repo_id', '')}")
        self._update_task_controls(task.get("status"))
        self._timer.start(1000)

    def _poll(self):
        if not self._task_id:
            self._timer.stop()
            return
        if self._polling:
            return
        self._polling = True
        self._run_api(lambda: self.api.download_status(self._task_id), self._apply_download_status, self._poll_failed)

    def _apply_download_status(self, task):
        self._polling = False
        self._set_busy(False)
        status = task.get("status", "")
        self.progress.setValue(int(task.get("progress") or 0))
        self.status.setText(f"{task['repo_id']} - {status} - {task.get('message', '')}")
        self._update_task_controls(status)
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            self._timer.stop()
            if status == "COMPLETED":
                QMessageBox.information(self, "完成", "下载完成，可在底部栏右键打开本地文件夹。")
            else:
                QMessageBox.warning(self, "失败", task.get("error_code", "下载任务未完成"))

    def _poll_failed(self, error):
        self._polling = False
        self.status.setText(f"下载状态同步失败：{format_api_error(error)}")

    def _failed(self, action, error):
        self._set_busy(False)
        self.status.setText(f"{action}失败：{format_api_error(error)}")
        QMessageBox.warning(self, action, format_api_error(error))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class LocalModelImportDialog(QDialog, AsyncApiMixin):
    """Detect, register and optionally load an already-downloaded local model."""

    CAPABILITIES = (
        ("CHAT", "文本对话"),
        ("INFERENCE", "文本生成"),
        ("VISION", "多模态理解"),
        ("EMBEDDING", "Embedding"),
        ("RERANKER", "Reranker"),
        ("IMAGE", "图像生成"),
        ("ASR", "语音识别"),
        ("TTS", "语音合成"),
        ("VIDEO", "视频生成"),
        ("LORA", "LoRA/Adapter"),
    )

    def __init__(self, api, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._detection: dict | None = None
        self._busy = False
        self.result_payload: dict | None = None
        self.setWindowTitle("加载本地模型")
        self.resize(760, 620)
        self._init_ui()
        translator = current()
        if translator is not None:
            self.setWindowTitle(text("加载本地模型", translator.locale))
            localize_tree(self, translator)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("选择模型目录或文件，也可直接粘贴本机路径")
        path_row.addWidget(self.path_input, 1)
        dir_btn = QPushButton("目录…")
        dir_btn.clicked.connect(self._browse_dir)
        file_btn = QPushButton("文件…")
        file_btn.clicked.connect(self._browse_file)
        self.detect_btn = QPushButton("检测模型")
        self.detect_btn.clicked.connect(self.detect)
        path_row.addWidget(dir_btn)
        path_row.addWidget(file_btn)
        path_row.addWidget(self.detect_btn)
        layout.addLayout(path_row)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("模型名称（默认使用目录或文件名）")
        layout.addWidget(self.name_input)

        caps_panel = QWidget()
        caps_layout = QHBoxLayout(caps_panel)
        caps_layout.setContentsMargins(0, 0, 0, 0)
        self.cap_checks: dict[str, QCheckBox] = {}
        for value, label in self.CAPABILITIES:
            check = QCheckBox(label)
            check.setProperty("capability", value)
            self.cap_checks[value] = check
            caps_layout.addWidget(check)
        caps_layout.addStretch(1)
        layout.addWidget(caps_panel)

        runtime_row = QHBoxLayout()
        runtime_row.addWidget(QLabel("推理后端:"))
        self.runtime_combo = QComboBox()
        self.runtime_combo.addItem("自动选择", None)
        runtime_row.addWidget(self.runtime_combo, 1)
        self.register_only = QCheckBox("仅登记，不加载到运行时")
        self.register_only.setChecked(True)
        runtime_row.addWidget(self.register_only)
        layout.addLayout(runtime_row)

        params = QHBoxLayout()
        self.context_input = QLineEdit()
        self.context_input.setPlaceholderText("上下文长度（适用时）")
        self.gpu_layers_input = QLineEdit()
        self.gpu_layers_input.setPlaceholderText("GPU 层数（GGUF）")
        self.threads_input = QLineEdit()
        self.threads_input.setPlaceholderText("线程数（GGUF）")
        params.addWidget(self.context_input)
        params.addWidget(self.gpu_layers_input)
        params.addWidget(self.threads_input)
        layout.addLayout(params)

        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("检测结果、依据和不确定项会显示在这里。")
        layout.addWidget(self.summary, 1)

        controls = QHBoxLayout()
        self.register_btn = QPushButton("登记")
        self.register_btn.clicked.connect(self.register)
        self.register_btn.setEnabled(False)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        controls.addStretch(1)
        controls.addWidget(self.register_btn)
        controls.addWidget(close_btn)
        layout.addLayout(controls)
        self.status = QLabel("默认引用原始文件，不复制、移动、修改或删除模型。")
        self.status.setProperty("role", "muted")
        layout.addWidget(self.status)

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择模型目录")
        if path:
            self.path_input.setText(path)

    def _browse_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择模型文件",
            "",
            "Model files (*.gguf *.ggml *.safetensors *.bin *.pt *.pth);;All files (*)",
        )
        if path:
            self.path_input.setText(path)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.detect_btn.setEnabled(not busy)
        self.register_btn.setEnabled(not busy and self._detection is not None)

    def detect(self):
        if self._busy:
            return
        path = self.path_input.text().strip()
        if not path:
            QMessageBox.information(self, "提示", "请先选择模型目录或文件。")
            return
        self._set_busy(True)
        self.status.setText("正在离线检测模型…")
        self._run_api(lambda: self.api.detect_local_model(path), self._detected, lambda error: self._failed("检测模型", error), request_key="local-model.detect")

    def _detected(self, detection: dict):
        self._detection = detection
        self._set_busy(False)
        self.name_input.setText(str(detection.get("name") or ""))
        caps = {str(item).upper() for item in detection.get("capabilities") or []}
        for key, check in self.cap_checks.items():
            check.setChecked(key in caps)
        self.runtime_combo.clear()
        self.runtime_combo.addItem("自动选择", None)
        for runtime in detection.get("runtime_options") or []:
            label = runtime.get("label") or runtime.get("id")
            if runtime.get("available") is False:
                label = f"{label}（缺少依赖）"
            self.runtime_combo.addItem(str(label), runtime.get("id"))
        self._render_summary(detection)
        if detection.get("runnable"):
            self.status.setText("检测完成：可登记；取消“仅登记”后会立即加载到运行时。")
        else:
            self.status.setText("检测完成：可登记，但当前不可运行或需要补齐依赖/文件。")

    def _render_summary(self, detection: dict):
        lines = [
            f"路径：{detection.get('real_path') or detection.get('path')}",
            f"格式：{detection.get('format') or '未知'}",
            f"架构：{detection.get('architecture') or '未知'}",
            f"类型：{detection.get('model_type') or '未知'}",
            f"能力：{', '.join(detection.get('capabilities') or []) or '未确定'}",
            f"可运行：{'是' if detection.get('runnable') else '否'}",
        ]
        for title, key in (("依据", "evidence"), ("缺失文件", "missing_files"), ("不确定项", "uncertain"), ("警告", "warnings"), ("不可用原因", "unavailable_reasons")):
            values = detection.get(key) or []
            if values:
                lines.append(f"\n{title}：")
                lines.extend(f"- {item}" for item in values)
        self.summary.setPlainText("\n".join(lines))

    def register(self):
        if self._busy or self._detection is None:
            return
        selected_caps = [key for key, check in self.cap_checks.items() if check.isChecked()]
        path = self.path_input.text().strip()
        self._set_busy(True)
        self.status.setText("正在登记本地模型…")
        self._run_api(
            lambda: self.api.register_local_model(
                path,
                name=self.name_input.text().strip() or None,
                capabilities=selected_caps,
                preferred_runtime=self.runtime_combo.currentData(),
                load=not self.register_only.isChecked(),
                context_length=_int_or_none(self.context_input.text()),
                gpu_layers=_int_or_none(self.gpu_layers_input.text()),
                threads=_int_or_none(self.threads_input.text()),
            ),
            self._registered,
            lambda error: self._failed("登记模型", error),
            request_key="local-model.register",
        )

    def _registered(self, payload: dict):
        self._set_busy(False)
        self.result_payload = payload
        loaded = payload.get("loaded")
        if isinstance(loaded, dict) and loaded.get("ok") is False:
            self.status.setText(f"模型已登记，但加载失败：{loaded.get('error')}")
            QMessageBox.warning(self, "加载失败", str(loaded.get("message") or loaded.get("error")))
            self.accept()
            return
        self.status.setText("模型已登记。" if self.register_only.isChecked() else "模型已登记并加载。")
        self.accept()

    def _failed(self, action: str, error: str):
        self._set_busy(False)
        self.status.setText(f"{action}失败：{format_api_error(error)}")
        QMessageBox.warning(self, action, format_api_error(error))

    def closeEvent(self, event):
        self.shutdown_async_api()
        super().closeEvent(event)


def _int_or_none(text: str):
    text = str(text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None
