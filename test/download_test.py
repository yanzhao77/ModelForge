import logging
import os
import sys
import traceback
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QThreadPool, Qt, QTimer, Signal, QObject, QRunnable
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QMessageBox, QAbstractItemView, QProgressBar,
                             QHeaderView, QLabel, QSizePolicy)
from huggingface_hub import model_info, snapshot_download, HfApi

from common.const.common_const import common_const

# ---------------------------
# 日志配置
# ---------------------------
log_dir = os.path.join(os.path.dirname(common_const.default_model_path), 'log')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, 'hf_downloader.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)


# ---------------------------
# 配置模块
# ---------------------------
class AppConfig:
    HF_ENDPOINT = "https://hf-mirror.com"
    PAGE_SIZE = 50
    DOWNLOAD_DIR = Path(common_const.default_model_path).expanduser()
    MAX_RETRIES = 3
    CACHE_EXPIRE = 3600  # 1小时缓存
    MAX_CONCURRENT = 4  # 最大并发下载数

    @classmethod
    def setup(cls):
        """初始化应用配置"""
        cls.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["HF_ENDPOINT"] = cls.HF_ENDPOINT


# ---------------------------
# 自定义 tqdm 类
# ---------------------------
class CustomTqdm:
    """
    自定义进度类，用于替换 snapshot_download 中的 tqdm_class。
    必须提供 set_lock() 和 get_lock() 类方法，供 tqdm.contrib.concurrent 使用。
    """
    _lock = threading.Lock()

    @classmethod
    def set_lock(cls, lock):
        cls._lock = lock

    @classmethod
    def get_lock(cls):
        return cls._lock

    def __init__(self, total=0, parent=None, **kwargs):
        """
        初始化时接收 total 和 parent 参数。
        parent 用于更新 GUI 进度，通常为 DownloadWorker 实例。
        """
        self.total = total
        self.parent = parent
        self._last_progress = 0

    def update(self, n=1):
        self._last_progress += n
        if self.total > 0:
            percent = int((self._last_progress / self.total) * 100)
        else:
            percent = 100
        # 如果设置了 parent，则通过 parent 发射信号更新进度，否则写日志
        if self.parent is not None:
            self.parent.signals.progress.emit(percent, f"下载中 {percent}%")
        else:
            logging.info(f"下载进度: {percent}% ({n / 1024:.1f}KB/s)")


# 为确保 set_lock 属性存在（有时某些环境可能找不到类方法），可以显式绑定：
CustomTqdm.set_lock = CustomTqdm.set_lock
CustomTqdm.get_lock = CustomTqdm.get_lock


# ---------------------------
# 工具模块
# ---------------------------
class ModelUtils:
    @staticmethod
    def process_model(model) -> Dict[str, Any]:
        """处理单个模型数据"""
        return {
            'id': model.id,
            'name': model.modelId,
            'library': model.library_name or "N/A",
            'pipeline': model.pipeline_tag or "N/A",
            'downloads': getattr(model, "downloads", 0),
            'likes': getattr(model, "likes", 0),
            'url': f"{AppConfig.HF_ENDPOINT}/{model.modelId}",
            'last_modified': getattr(model, "lastModified", "")
        }

    @classmethod
    def sanitize_repo_id(cls, repo_id: str) -> str:
        """清理仓库ID格式"""
        return repo_id.replace(AppConfig.HF_ENDPOINT, "").strip("/")


# ---------------------------
# 线程管理模块
# ---------------------------
class WorkerSignals(QObject):
    """
    定义工作线程信号类，用于在线程中传递结果、错误、进度和完成信号。
    """
    finished = Signal()
    error = Signal(str)
    progress = Signal(int, str)
    result = Signal(object)


class BaseWorker(QRunnable):
    """
    只继承自QRunnable的基础工作类，通过内部的WorkerSignals对象传递信号。
    """

    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self._stop_flag = False
        self.retry_count = 0

    def cancel(self):
        """取消任务"""
        self._stop_flag = True

    def _check_stop_flag(self) -> bool:
        """检查是否请求取消任务"""
        if self._stop_flag:
            self.signals.finished.emit()
            return True
        return False

    def run(self):
        raise NotImplementedError("Subclasses must implement this method.")


class ModelLoaderWorker(BaseWorker):
    """
    模型加载工作线程，通过 huggingface_hub 接口加载模型列表。
    """

    def __init__(self, api, query: str = "", page: int = 1, page_size: int = 50):
        super().__init__()
        self.api = api
        self.query = query
        self.page = page
        self.page_size = page_size

    def run(self):
        try:
            models = self.api.list_models(
                search=self.query,
                limit=self.page_size,
            )
            if self._check_stop_flag():
                return
            processed = [self._process_model(m) for m in models]
            self.signals.result.emit(processed)
            self.signals.finished.emit()
        except Exception as e:
            if self.retry_count < 3:
                self.retry_count += 1
                self.signals.progress.emit(0, f"重试中 ({self.retry_count}/3)...")
                QTimer.singleShot(2000, self.run)
            else:
                err_msg = f"加载失败: {str(e)}\n{traceback.format_exc()}"
                self.signals.error.emit(err_msg)

    def _process_model(self, model) -> dict:
        return {
            'id': model.id,
            'name': model.modelId,
            'library': getattr(model, "library_name", "N/A") or "N/A",
            'pipeline': getattr(model, "pipeline_tag", "N/A") or "N/A",
            'downloads': getattr(model, "downloads", 0),
            'likes': getattr(model, "likes", 0),
            'url': f"{self.api.endpoint}/{model.modelId}",
            'last_modified': getattr(model, "lastModified", "")
        }


class DownloadWorker(BaseWorker):
    """
    模型下载工作线程，负责下载指定模型。
    """

    def __init__(self, repo_id: str, save_path, sanitize_func=ModelUtils.sanitize_repo_id):
        super().__init__()
        self.repo_id = sanitize_func(repo_id)
        self.save_path = save_path / self.repo_id
        self.total_size = 0
        self._downloaded_size = 0

    def run(self):
        try:
            if self._check_stop_flag():
                return
            # 获取模型信息以确定总大小
            info = model_info(self.repo_id)
            self.total_size = sum(s.size if s.size is not None else 0 for s in info.siblings)
            # 开始下载，传入自定义的 CustomTqdm 类
            snapshot_download(
                repo_id=self.repo_id,
                local_dir=self.save_path,
                force_download=True,
                max_workers=4,
                tqdm_class=CustomTqdm
            )
            self.signals.finished.emit()
        except Exception as e:
            err_msg = f"下载失败: {str(e)}\n{traceback.format_exc()}"
            self.signals.error.emit(err_msg)

    def _check_local_cache(self) -> bool:
        if not self.save_path.exists():
            return False
        return any(self.save_path.iterdir())


# ---------------------------
# 主界面模块
# ---------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._init_config()
        self._init_ui()
        self._init_state()
        self.load_initial_data()

    def _init_config(self):
        AppConfig.setup()
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(AppConfig.MAX_CONCURRENT)
        self.api = HfApi()

    def _init_state(self):
        self.current_page = 1
        self.current_search = None
        self.has_more = True
        self.active_workers = set()

    def _init_ui(self):
        self.setWindowTitle("HF-Mirror 增强版")
        self.resize(1200, 800)
        layout = QVBoxLayout()

        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit(placeholderText="搜索模型...")
        self.search_bar.returnPressed.connect(self.trigger_search)
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.trigger_search)

        self.table = self._create_model_table()
        self.table.verticalScrollBar().valueChanged.connect(self._check_scroll)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()

        self.download_btn = QPushButton("下载选中项")
        self.download_btn.clicked.connect(self.start_download)

        self.status = QLabel("就绪 | 已加载0个模型")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.search_btn)

        control_layout = QHBoxLayout()
        control_layout.addWidget(self.download_btn)

        layout.addLayout(search_layout)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        layout.addLayout(control_layout)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def _create_model_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["ID", "模型名称", "框架", "任务类型", "下载量"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setSortingEnabled(True)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return table

    def load_initial_data(self):
        self._load_page(1)

    def _load_page(self, page: int):
        if not self.has_more:
            return
        worker = ModelLoaderWorker(api=self.api, query=self.current_search, page=page)
        worker.signals.result.connect(self._update_model_table)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self._set_loading(False))
        self._track_worker(worker)
        self.thread_pool.start(worker)
        self._set_loading(True, f"正在加载第 {page} 页...")

    def _update_model_table(self, models: List[dict]):
        current_row = self.table.rowCount()
        self.table.setRowCount(current_row + len(models))
        for idx, model in enumerate(models):
            row = current_row + idx
            self._update_table_row(row, model)
        self.table.resizeColumnsToContents()
        self.has_more = (len(models) == AppConfig.PAGE_SIZE)
        self.status.setText(f"已加载 {self.table.rowCount()} 个模型 | 页数 {self.current_page}")

    def _update_table_row(self, row: int, model: dict):
        columns = [
            model['id'],
            model['name'],
            model['library'],
            model['pipeline'],
            str(model['downloads']),
        ]
        for col, value in enumerate(columns):
            item = QTableWidgetItem(value)
            item.setData(Qt.ItemDataRole.UserRole, model)
            self.table.setItem(row, col, item)

    def _check_scroll(self, value: int):
        if value == self.table.verticalScrollBar().maximum():
            if self.has_more:
                self.current_page += 1
                self._load_page(self.current_page)

    def trigger_search(self):
        query = self.search_bar.text().strip()
        if query == self.current_search:
            return
        self.current_search = query
        self.current_page = 1
        self.table.setRowCount(0)
        self._load_page(1)

    def start_download(self):
        selected = self.table.selectedItems()
        if not selected:
            self._show_error("请先选择要下载的模型")
            return
        repo_id = selected[0].text()
        worker = DownloadWorker(repo_id=repo_id, save_path=AppConfig.DOWNLOAD_DIR)
        worker.signals.progress.connect(self._update_progress)
        worker.signals.finished.connect(lambda: self._on_download_finish(repo_id))
        worker.signals.error.connect(self._show_error)
        self._track_worker(worker)
        self.thread_pool.start(worker)
        self.progress.show()
        self.download_btn.setEnabled(False)

    def _update_progress(self, percent: int, message: str):
        self.progress.setValue(percent)
        self.status.setText(message)

    def _on_download_finish(self, repo_id: str):
        self.progress.hide()
        self.download_btn.setEnabled(True)
        QMessageBox.information(
            self,
            "下载完成",
            f"{repo_id} 已下载到：\n{AppConfig.DOWNLOAD_DIR / repo_id}"
        )

    def cancel_all_downloads(self):
        for worker in self.active_workers.copy():
            if isinstance(worker, DownloadWorker):
                worker.cancel()
        self.status.setText("已取消所有下载任务")

    def _track_worker(self, worker: BaseWorker):
        self.active_workers.add(worker)
        worker.signals.finished.connect(lambda: self.active_workers.discard(worker))

    def _set_loading(self, loading: bool, message: Optional[str] = None):
        self.search_btn.setEnabled(not loading)
        if message:
            self.status.setText(message)

    def _show_error(self, message: str):
        QMessageBox.critical(self, "错误", message)
        self.status.setText(f"错误: {message}")
        logging.error(message)
