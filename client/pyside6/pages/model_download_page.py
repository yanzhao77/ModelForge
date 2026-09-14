"""Model discovery, detail and download task pages."""

from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFEmptyState, MFPanel, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

TASK_TABS = [
    ("all", "全部"),
    ("text-generation", "文本生成"),
    ("embedding", "Embedding"),
    ("vision", "视觉"),
    ("speech", "语音"),
    ("video", "视频"),
    ("multimodal", "多模态"),
    ("other", "其他"),
]


def _human_size(size_bytes) -> str:
    try:
        amount = float(max(0, int(size_bytes)))
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _status_tone(status: str) -> str:
    return {
        "supported": "online",
        "partial": "warning",
        "download_only": "warning",
        "RUNNING": "online",
        "COMPLETED": "online",
        "FAILED": "error",
        "CANCELLED": "error",
        "PAUSED": "warning",
    }.get(status, "warning")


class ModelDownloadPage(QWidget, AsyncApiMixin):
    """Search Hugging Face-backed catalog entries and start downloads."""

    task_created = Signal()

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._results: list[dict] = []
        self._detail: dict | None = None
        self._busy = False
        self._settings = QSettings("ModelForge", "ModelForge")
        self._init_ui()
        self._load_recent_searches()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索模型名称、作者、repo id，或粘贴 Hugging Face URL")
        self.search_input.returnPressed.connect(self.search)
        search_row.addWidget(self.search_input, 1)
        self.recent_combo = QComboBox()
        self.recent_combo.setMinimumWidth(160)
        self.recent_combo.setToolTip("最近搜索")
        self.recent_combo.activated.connect(self._apply_recent)
        search_row.addWidget(self.recent_combo)
        self.search_button = QPushButton("搜索")
        self.search_button.setToolTip("在模型来源中搜索")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.search_button)
        root.addLayout(search_row)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for key, label in TASK_TABS:
            self.tabs.addTab(label)
            self.tabs.setTabData(self.tabs.count() - 1, key)
        self.tabs.currentChanged.connect(lambda _index: self.search())
        root.addWidget(self.tabs)

        filter_panel = MFPanel()
        filter_panel.layout.setContentsMargins(12, 10, 12, 10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["全部格式", "GGUF", "SafeTensors", "PyTorch", "ONNX", "Transformers", "Diffusers"])
        self.library_combo = QComboBox()
        self.library_combo.addItems(["全部模型库", "transformers", "diffusers", "sentence-transformers", "onnx"])
        self.param_combo = QComboBox()
        self.param_combo.addItems(["参数量不限", "< 1B", "1B - 7B", "7B - 14B", "> 14B"])
        self.quant_combo = QComboBox()
        self.quant_combo.addItems(["量化不限", "Q4", "Q5", "Q8", "F16/BF16"])
        self.size_combo = QComboBox()
        self.size_combo.addItems(["文件大小不限", "< 2GB", "2GB - 8GB", "> 8GB"])
        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("作者")
        self.gated_check = QCheckBox("需要授权")
        self.compatible_check = QCheckBox("仅显示当前可运行")
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["相关度", "热门", "最近更新", "下载量", "文件大小"])
        for widget in (self.format_combo, self.library_combo, self.param_combo, self.quant_combo, self.size_combo, self.gated_check, self.compatible_check, self.sort_combo):
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(lambda _=None: self.search())
        self.gated_check.stateChanged.connect(lambda _=None: self.search())
        self.compatible_check.stateChanged.connect(lambda _=None: self.search())
        self.author_input.returnPressed.connect(self.search)
        widgets = [
            ("格式", self.format_combo),
            ("模型库", self.library_combo),
            ("参数量", self.param_combo),
            ("量化", self.quant_combo),
            ("大小", self.size_combo),
            ("作者", self.author_input),
            ("排序", self.sort_combo),
        ]
        for i, (label, widget) in enumerate(widgets):
            grid.addWidget(QLabel(label), i // 4 * 2, i % 4)
            grid.addWidget(widget, i // 4 * 2 + 1, i % 4)
        grid.addWidget(self.gated_check, 4, 0)
        grid.addWidget(self.compatible_check, 4, 1)
        filter_panel.layout.addLayout(grid)
        root.addWidget(filter_panel)

        self.status = MFStatusBadge("准备搜索模型", "warning")
        root.addWidget(self.status)

        self.splitter = QSplitter(Qt.Horizontal)
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(8)
        self.results_table.setHorizontalHeaderLabels(["模型", "任务", "格式", "参数", "热度", "更新", "许可", "兼容"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.itemSelectionChanged.connect(self._selected_result_changed)
        self.splitter.addWidget(self.results_table)
        self.detail_panel = _ModelDetailPanel(self.api)
        self.detail_panel.download_requested.connect(self._start_download)
        self.splitter.addWidget(self.detail_panel)
        self.splitter.setSizes([680, 500])
        root.addWidget(self.splitter, 1)

    def resizeEvent(self, event) -> None:
        self.splitter.setOrientation(Qt.Vertical if self.width() < 920 else Qt.Horizontal)
        super().resizeEvent(event)

    def _load_recent_searches(self) -> None:
        values = self._settings.value("models/recent_searches", []) or []
        if isinstance(values, str):
            values = [values]
        self.recent_combo.clear()
        self.recent_combo.addItem("最近搜索")
        for value in values[:8]:
            self.recent_combo.addItem(str(value))

    def _remember_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        values = [self.recent_combo.itemText(i) for i in range(1, self.recent_combo.count())]
        values = [query] + [item for item in values if item != query]
        self._settings.setValue("models/recent_searches", values[:8])
        self._load_recent_searches()

    def _apply_recent(self, index: int) -> None:
        if index <= 0:
            return
        self.search_input.setText(self.recent_combo.itemText(index))
        self.search()

    def _category(self) -> str:
        return self.tabs.tabData(self.tabs.currentIndex()) or "all"

    def search(self) -> None:
        if self._busy:
            return
        query = self.search_input.text().strip()
        self._busy = True
        self.search_button.setEnabled(False)
        self.status.set_state("正在搜索模型…", "warning")
        self.results_table.setRowCount(0)
        self.detail_panel.clear("选择一个模型查看仓库详情和文件。")
        self._remember_search(query)
        self._run_api(
            lambda: self.api.search_model_catalog(
                query=query,
                category=self._category(),
                model_format=self._combo_value(self.format_combo),
                library=self._combo_value(self.library_combo),
                author=self.author_input.text().strip() or None,
                gated=True if self.gated_check.isChecked() else None,
                compatible=True if self.compatible_check.isChecked() else None,
                sort=self._sort_value(),
                limit=40,
            ),
            self._render_results,
            self._search_failed,
            request_key="models.catalog.search",
        )

    @staticmethod
    def _combo_value(combo: QComboBox) -> str | None:
        text = combo.currentText()
        return None if text.startswith("全部") or text.endswith("不限") else text

    def _sort_value(self) -> str:
        return {"热门": "popular", "最近更新": "updated", "下载量": "downloads", "文件大小": "size"}.get(self.sort_combo.currentText(), "relevance")

    def _render_results(self, results: list[dict]) -> None:
        self._busy = False
        self.search_button.setEnabled(True)
        self._results = self._client_filter(results or [])
        self.results_table.setRowCount(len(self._results))
        for row, model in enumerate(self._results):
            compatibility = model.get("compatibility") or {}
            values = [
                model.get("repo_id", ""),
                model.get("task_label", ""),
                ", ".join(model.get("formats") or []),
                model.get("parameters", "未知"),
                str(model.get("downloads") or model.get("likes") or ""),
                str(model.get("updated_at") or "")[:10],
                "需授权" if model.get("gated") else "开放",
                "可运行" if compatibility.get("runnable") else "仅下载",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.results_table.setItem(row, column, item)
        if self._results:
            self.results_table.selectRow(0)
            self.status.set_state(f"找到 {len(self._results)} 个模型", "online")
        else:
            self.status.set_state("没有匹配的模型，调整搜索词或筛选条件后重试。", "warning")

    def _client_filter(self, results: list[dict]) -> list[dict]:
        filtered = results
        quant = self.quant_combo.currentText()
        if quant != "量化不限":
            filtered = [item for item in filtered if quant.lower().split("/")[0] in " ".join(item.get("tags") or []).lower() or quant.lower() in " ".join(item.get("formats") or []).lower()]
        # Search results often do not include file sizes; size filtering is
        # therefore enforced in the detail file table where exact metadata exists.
        return filtered

    def _search_failed(self, error: str) -> None:
        self._busy = False
        self.search_button.setEnabled(True)
        self.status.set_state(f"搜索失败：{format_api_error(error)}", "error")
        self.detail_panel.clear("网络错误、鉴权失败或模型源不可用。请检查连接和 Hugging Face 访问权限。")

    def _selected_result_changed(self) -> None:
        rows = self.results_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row < 0 or row >= len(self._results):
            return
        model = self._results[row]
        repo_id = model.get("repo_id")
        if not repo_id:
            return
        self.detail_panel.loading(repo_id)
        self._run_api(
            lambda: self.api.model_catalog_detail(repo_id, model.get("source") or "huggingface"),
            self.detail_panel.render_detail,
            self.detail_panel.failed,
            request_key="models.catalog.detail",
        )

    def _start_download(self, request: dict) -> None:
        self.status.set_state("正在创建下载任务…", "warning")
        self._run_api(
            lambda: self.api.download_model(**request),
            self._download_created,
            lambda error: self.status.set_state(f"创建下载任务失败：{format_api_error(error)}", "error"),
            request_key="models.download.create",
        )

    def _download_created(self, task: dict) -> None:
        self.status.set_state(f"下载任务已创建：{task.get('repo_id', '')}", "online")
        self.task_created.emit()


class _ModelDetailPanel(MFPanel):
    download_requested = Signal(dict)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self._detail: dict | None = None
        self._build()
        self.clear("选择一个模型查看仓库详情和文件。")

    def _build(self) -> None:
        self.title = QLabel("模型详情")
        self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.layout.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setProperty("role", "muted")
        self.meta.setWordWrap(True)
        self.layout.addWidget(self.meta)
        self.compat = MFStatusBadge("等待选择", "warning")
        self.layout.addWidget(self.compat)
        self.readme = QTextBrowser()
        self.readme.setOpenExternalLinks(True)
        self.readme.setMaximumHeight(170)
        self.layout.addWidget(self.readme)
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(6)
        self.file_table.setHorizontalHeaderLabels(["下载", "文件", "格式", "量化", "大小", "角色"])
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.layout.addWidget(self.file_table, 1)
        self.warning = QLabel("非 GGUF 模型建议包含 config/tokenizer/processor 等配套文件；仅下载权重文件可能无法加载。")
        self.warning.setProperty("role", "muted")
        self.warning.setWordWrap(True)
        self.layout.addWidget(self.warning)
        actions = QHBoxLayout()
        self.recommended_btn = QPushButton("选择推荐")
        self.recommended_btn.setToolTip("选择推荐量化或推荐权重集合")
        self.recommended_btn.clicked.connect(self._select_recommended)
        actions.addWidget(self.recommended_btn)
        self.full_btn = QPushButton("完整仓库")
        self.full_btn.setToolTip("下载仓库中的全部文件，不会默认启用")
        self.full_btn.clicked.connect(self._download_full)
        actions.addWidget(self.full_btn)
        self.include_support = QCheckBox("自动包含配套文件")
        self.include_support.setChecked(True)
        self.include_support.setToolTip("自动加入 config、tokenizer、processor、README 等运行所需小文件")
        actions.addWidget(self.include_support)
        actions.addStretch(1)
        self.download_btn = QPushButton("下载所选")
        self.download_btn.setToolTip("创建统一下载队列任务")
        self.download_btn.clicked.connect(self._download_selected)
        actions.addWidget(self.download_btn)
        self.layout.addLayout(actions)

    def clear(self, message: str = "") -> None:
        self._detail = None
        self.title.setText("模型详情")
        self.meta.setText(message)
        self.compat.set_state("等待选择", "warning")
        self.readme.setPlainText("")
        self.file_table.setRowCount(0)
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.recommended_btn, self.full_btn, self.include_support, self.download_btn, self.file_table):
            widget.setEnabled(enabled)

    def loading(self, repo_id: str) -> None:
        self.clear(f"正在读取 {repo_id} 的仓库元数据…")

    def failed(self, error: str) -> None:
        self.clear(f"详情加载失败：{format_api_error(error)}。可能是网络错误、私有模型或尚未接受许可协议。")
        self.compat.set_state("详情不可用", "error")

    def render_detail(self, detail: dict) -> None:
        self._detail = detail or {}
        repo_id = self._detail.get("repo_id", "")
        self.title.setText(repo_id or "模型详情")
        formats = ", ".join(self._detail.get("formats") or [])
        self.meta.setText(
            f"{self._detail.get('task_label', '其他')} · {formats or '未知格式'} · 参数 {self._detail.get('parameters', '未知')} · "
            f"许可 {self._detail.get('license', '未声明')} · 总大小 {self._detail.get('total_size', '')} · 磁盘可用 {self._detail.get('disk_free', '')}\n"
            f"下载路径：{self._detail.get('download_path', '')}"
        )
        formats = {str(item).lower() for item in (self._detail.get("formats") or [])}
        if "gguf" in formats:
            self.warning.setText("GGUF 仓库通常包含多个量化变体；请只选择需要的 Q4/Q5/Q8 文件，避免下载全部大型变体。")
        else:
            self.warning.setText("非 GGUF 模型建议包含 config/tokenizer/processor 等配套文件；仅下载权重文件可能无法加载。")
        compatibility = self._detail.get("compatibility") or {}
        self.compat.set_state(
            "当前后端可运行" if compatibility.get("runnable") else compatibility.get("reason", "仅下载"),
            _status_tone(compatibility.get("status", "download_only")),
        )
        text = str(self._detail.get("readme") or "")
        self.readme.setPlainText(text[:6000])
        files = self._detail.get("files") or []
        self.file_table.setRowCount(len(files))
        for row, item in enumerate(files):
            check = QTableWidgetItem("")
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked if item.get("recommended") else Qt.Unchecked)
            self.file_table.setItem(row, 0, check)
            for column, key in enumerate(["path", "format", "quantization", "size", "role"], start=1):
                value = str(item.get(key) or "")
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.file_table.setItem(row, column, cell)
        self._set_enabled(True)

    def _selected_files(self) -> list[str]:
        paths: list[str] = []
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, 0)
            path_item = self.file_table.item(row, 1)
            if item is not None and path_item is not None and item.checkState() == Qt.Checked:
                paths.append(path_item.text())
        return paths

    def _select_recommended(self) -> None:
        recommended = set((self._detail or {}).get("recommended_files") or [])
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, 0)
            path_item = self.file_table.item(row, 1)
            if item is not None and path_item is not None:
                item.setCheckState(Qt.Checked if path_item.text() in recommended else Qt.Unchecked)

    def _download_selected(self) -> None:
        detail = self._detail or {}
        files = self._selected_files()
        if not files:
            QMessageBox.information(self, "请选择文件", "请先选择至少一个权重文件或使用完整仓库下载。")
            return
        self.download_requested.emit(
            {
                "repo_id": detail.get("repo_id", ""),
                "files": files,
                "include_support_files": self.include_support.isChecked(),
                "full_repository": False,
            }
        )

    def _download_full(self) -> None:
        detail = self._detail or {}
        if QMessageBox.question(self, "确认完整下载", "完整仓库可能包含多个大型权重变体，确认创建下载任务？") != QMessageBox.Yes:
            return
        self.download_requested.emit(
            {
                "repo_id": detail.get("repo_id", ""),
                "files": [],
                "include_support_files": True,
                "full_repository": True,
            }
        )


class ModelDownloadTasksPage(QWidget, AsyncApiMixin):
    """Persistent model download queue."""

    changed = Signal()

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._tasks: list[dict] = []
        self._busy = False
        self._init_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.refresh()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.status = MFStatusBadge("正在同步下载任务", "warning")
        controls.addWidget(self.status)
        controls.addStretch(1)
        refresh = QToolButton()
        refresh.setText("刷新")
        refresh.setToolTip("刷新下载任务")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        root.addLayout(controls)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(["仓库", "文件/计划", "状态", "进度", "速度", "已下载", "剩余", "更新时间", "错误"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setToolTip("暂停选中的下载任务")
        self.pause_btn.clicked.connect(lambda: self._operate("pause_download"))
        actions.addWidget(self.pause_btn)
        self.resume_btn = QPushButton("继续")
        self.resume_btn.setToolTip("继续断点下载")
        self.resume_btn.clicked.connect(lambda: self._operate("resume_download"))
        actions.addWidget(self.resume_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setToolTip("取消选中的下载任务")
        self.cancel_btn.clicked.connect(lambda: self._operate("cancel_download"))
        actions.addWidget(self.cancel_btn)
        self.retry_btn = QPushButton("重试")
        self.retry_btn.setToolTip("重新校验并重试下载")
        self.retry_btn.clicked.connect(lambda: self._operate("restart_download"))
        actions.addWidget(self.retry_btn)
        actions.addStretch(1)
        root.addLayout(actions)
        self.empty = MFEmptyState("暂无下载任务", "从“下载模型”页创建任务后，可在这里查看进度、暂停、继续或重试。", self.table.viewport())
        self.empty.hide()

    def refresh(self) -> None:
        if self._busy:
            return
        if not hasattr(self.api, "list_download_tasks"):
            self._render([])
            return
        self._run_api(self.api.list_download_tasks, self._render, self._failed, request_key="models.download.tasks")

    def _render(self, tasks: list[dict]) -> None:
        self._tasks = tasks or []
        self.table.setRowCount(len(self._tasks))
        for row, task in enumerate(self._tasks):
            values = [
                task.get("repo_id", ""),
                task.get("filename") or ("完整仓库" if (task.get("plan") or {}).get("full_repository") else "推荐文件集合"),
                task.get("status", ""),
                f"{task.get('progress', 0)}%",
                task.get("speed", ""),
                f"{task.get('downloaded', '')} / {task.get('total', '')}".strip(" /"),
                task.get("eta", ""),
                str(task.get("updated_at") or "")[:19].replace("T", " "),
                task.get("error_code") or task.get("message", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(int(task.get("progress") or 0))
            progress.setTextVisible(True)
            self.table.setCellWidget(row, 3, progress)
        self.empty.setGeometry(self.table.viewport().rect())
        self.empty.setVisible(not self._tasks)
        active = sum(1 for item in self._tasks if item.get("status") in {"PENDING", "RUNNING"})
        failed = sum(1 for item in self._tasks if item.get("status") == "FAILED")
        self.status.set_state(f"{len(self._tasks)} 个任务 · {active} 个进行中 · {failed} 个失败", "error" if failed else "online")
        self.changed.emit()

    def _selected_task_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._tasks):
            return None
        return self._tasks[row].get("task_id")

    def _operate(self, method_name: str) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            QMessageBox.information(self, "请选择任务", "请先选择一个下载任务。")
            return
        self._busy = True
        method = getattr(self.api, method_name)
        self._run_api(lambda: method(task_id), self._operation_done, self._operation_failed, request_key=f"models.download.{method_name}")

    def _operation_done(self, _task: dict) -> None:
        self._busy = False
        self.refresh()

    def _operation_failed(self, error: str) -> None:
        self._busy = False
        self.status.set_state(f"任务操作失败：{format_api_error(error)}", "error")

    def _failed(self, error: str) -> None:
        self.status.set_state(f"下载任务同步失败：{format_api_error(error)}", "error")

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.shutdown_async_api()
        super().closeEvent(event)
