"""
GGUF 模型下载对话框
专门用于下载和管理 GGUF 格式模型
"""
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional

from PySide6.QtCore import QThreadPool, Qt, Signal, QObject, QRunnable
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox,
    QAbstractItemView, QProgressBar, QHeaderView,
    QLabel, QSizePolicy, QDialog, QComboBox
)
from huggingface_hub import HfApi, snapshot_download, model_info

from common.const.common_const import common_const


class GGUFDownloadConfig:
    """GGUF 下载配置"""
    HF_ENDPOINT = "https://hf-mirror.com"
    DOWNLOAD_DIR = Path(common_const.default_model_path).expanduser()
    
    # 常见的 GGUF 模型仓库
    POPULAR_GGUF_REPOS = [
        "TheBloke",  # 最大的 GGUF 模型提供者
        "lmstudio-community",
        "QuantFactory",
        "bartowski",
        "mradermacher"
    ]
    
    # GGUF 量化类型
    QUANTIZATION_TYPES = [
        "Q2_K",
        "Q3_K_S", "Q3_K_M", "Q3_K_L",
        "Q4_0", "Q4_1", "Q4_K_S", "Q4_K_M",
        "Q5_0", "Q5_1", "Q5_K_S", "Q5_K_M",
        "Q6_K",
        "Q8_0"
    ]
    
    @classmethod
    def setup(cls):
        """初始化配置"""
        cls.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["HF_ENDPOINT"] = cls.HF_ENDPOINT


class WorkerSignals(QObject):
    """工作线程信号"""
    finished = Signal()
    error = Signal(str)
    progress = Signal(int, str)
    result = Signal(object)


class GGUFModelSearchWorker(QRunnable):
    """GGUF 模型搜索工作线程"""
    
    def __init__(self, api: HfApi, query: str = "", author: str = None):
        super().__init__()
        self.api = api
        self.query = query
        self.author = author
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            # 搜索 GGUF 模型
            search_query = f"{self.query} gguf" if self.query else "gguf"
            
            models = self.api.list_models(
                search=search_query,
                author=self.author,
                limit=100
            )
            
            # 过滤出包含 gguf 文件的模型
            gguf_models = []
            for model in models:
                try:
                    info = model_info(model.id)
                    # 检查是否有 .gguf 文件
                    has_gguf = any(
                        sibling.rfilename.lower().endswith('.gguf')
                        for sibling in info.siblings
                    )
                    if has_gguf:
                        # 获取 gguf 文件列表
                        gguf_files = [
                            sibling.rfilename
                            for sibling in info.siblings
                            if sibling.rfilename.lower().endswith('.gguf')
                        ]
                        
                        gguf_models.append({
                            'id': model.id,
                            'name': model.modelId,
                            'author': model.author if hasattr(model, 'author') else model.id.split('/')[0],
                            'downloads': getattr(model, 'downloads', 0),
                            'likes': getattr(model, 'likes', 0),
                            'gguf_files': gguf_files,
                            'gguf_count': len(gguf_files)
                        })
                except Exception as e:
                    logging.debug(f"跳过模型 {model.id}: {e}")
                    continue
            
            self.signals.result.emit(gguf_models)
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(f"搜索失败: {str(e)}")


class GGUFDownloadWorker(QRunnable):
    """GGUF 模型下载工作线程"""
    
    def __init__(self, repo_id: str, gguf_filename: str, save_path: Path):
        super().__init__()
        self.repo_id = repo_id
        self.gguf_filename = gguf_filename
        self.save_path = save_path
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            self.signals.progress.emit(0, "开始下载...")
            
            # 下载单个 gguf 文件
            local_dir = self.save_path / self.repo_id.replace('/', '_')
            local_dir.mkdir(parents=True, exist_ok=True)
            
            # 使用 snapshot_download 下载指定文件
            snapshot_download(
                repo_id=self.repo_id,
                allow_patterns=[self.gguf_filename],
                local_dir=local_dir,
                force_download=False
            )
            
            self.signals.progress.emit(100, "下载完成")
            self.signals.result.emit(str(local_dir))
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(f"下载失败: {str(e)}")


class GGUFDownloadDialog(QDialog):
    """GGUF 模型下载对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_config()
        self.init_ui()
        self.load_popular_models()
    
    def init_config(self):
        """初始化配置"""
        GGUFDownloadConfig.setup()
        self.thread_pool = QThreadPool.globalInstance()
        self.api = HfApi()
        self.current_model_files = []
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("GGUF 模型下载器")
        self.resize(1000, 700)
        
        layout = QVBoxLayout()
        
        # 搜索区域
        search_layout = QHBoxLayout()
        
        # 作者筛选
        self.author_combo = QComboBox()
        self.author_combo.addItem("所有作者", None)
        for author in GGUFDownloadConfig.POPULAR_GGUF_REPOS:
            self.author_combo.addItem(author, author)
        self.author_combo.currentIndexChanged.connect(self.on_author_changed)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("搜索 GGUF 模型...")
        self.search_bar.returnPressed.connect(self.trigger_search)
        
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.trigger_search)
        
        search_layout.addWidget(QLabel("作者:"))
        search_layout.addWidget(self.author_combo)
        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.search_btn)
        
        # 模型列表表格
        self.model_table = QTableWidget()
        self.model_table.setColumnCount(5)
        self.model_table.setHorizontalHeaderLabels(["模型ID", "作者", "GGUF文件数", "下载量", "点赞数"])
        self.model_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.model_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.model_table.itemSelectionChanged.connect(self.on_model_selected)
        
        # GGUF 文件列表
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(2)
        self.file_table.setHorizontalHeaderLabels(["GGUF 文件名", "量化类型"])
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        
        # 进度条
        self.progress = QProgressBar()
        self.progress.hide()
        
        # 下载按钮
        self.download_btn = QPushButton("下载选中的 GGUF 文件")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setEnabled(False)
        
        # 状态栏
        self.status = QLabel("就绪")
        self.status.setAlignment(Qt.AlignCenter)
        
        # 添加到布局
        layout.addLayout(search_layout)
        layout.addWidget(QLabel("GGUF 模型列表:"))
        layout.addWidget(self.model_table)
        layout.addWidget(QLabel("可用的 GGUF 文件:"))
        layout.addWidget(self.file_table)
        layout.addWidget(self.progress)
        layout.addWidget(self.download_btn)
        layout.addWidget(self.status)
        
        self.setLayout(layout)
    
    def load_popular_models(self):
        """加载热门 GGUF 模型"""
        self.status.setText("正在加载热门 GGUF 模型...")
        worker = GGUFModelSearchWorker(self.api, query="", author="TheBloke")
        worker.signals.result.connect(self.update_model_table)
        worker.signals.error.connect(self.show_error)
        worker.signals.finished.connect(lambda: self.status.setText("加载完成"))
        self.thread_pool.start(worker)
    
    def trigger_search(self):
        """触发搜索"""
        query = self.search_bar.text().strip()
        author = self.author_combo.currentData()
        
        self.status.setText(f"正在搜索: {query}...")
        self.model_table.setRowCount(0)
        
        worker = GGUFModelSearchWorker(self.api, query=query, author=author)
        worker.signals.result.connect(self.update_model_table)
        worker.signals.error.connect(self.show_error)
        worker.signals.finished.connect(lambda: self.status.setText("搜索完成"))
        self.thread_pool.start(worker)
    
    def on_author_changed(self):
        """作者筛选改变"""
        if self.search_bar.text().strip():
            self.trigger_search()
    
    def update_model_table(self, models: List[Dict]):
        """更新模型表格"""
        self.model_table.setRowCount(len(models))
        
        for row, model in enumerate(models):
            self.model_table.setItem(row, 0, QTableWidgetItem(model['name']))
            self.model_table.setItem(row, 1, QTableWidgetItem(model['author']))
            self.model_table.setItem(row, 2, QTableWidgetItem(str(model['gguf_count'])))
            self.model_table.setItem(row, 3, QTableWidgetItem(str(model['downloads'])))
            self.model_table.setItem(row, 4, QTableWidgetItem(str(model['likes'])))
            
            # 存储完整数据
            self.model_table.item(row, 0).setData(Qt.UserRole, model)
        
        self.status.setText(f"找到 {len(models)} 个 GGUF 模型")
    
    def on_model_selected(self):
        """模型被选中"""
        selected = self.model_table.selectedItems()
        if not selected:
            return
        
        model_data = selected[0].data(Qt.UserRole)
        self.current_model_files = model_data['gguf_files']
        self.current_repo_id = model_data['id']
        
        # 更新文件列表
        self.file_table.setRowCount(len(self.current_model_files))
        for row, filename in enumerate(self.current_model_files):
            self.file_table.setItem(row, 0, QTableWidgetItem(filename))
            
            # 识别量化类型
            quant_type = "未知"
            for qt in GGUFDownloadConfig.QUANTIZATION_TYPES:
                if qt in filename.upper():
                    quant_type = qt
                    break
            self.file_table.setItem(row, 1, QTableWidgetItem(quant_type))
        
        self.download_btn.setEnabled(True)
    
    def start_download(self):
        """开始下载"""
        selected_file = self.file_table.selectedItems()
        if not selected_file:
            QMessageBox.warning(self, "警告", "请先选择要下载的 GGUF 文件")
            return
        
        filename = selected_file[0].text()
        
        reply = QMessageBox.question(
            self,
            "确认下载",
            f"确定要下载以下文件吗？\n\n模型: {self.current_repo_id}\n文件: {filename}\n\n下载路径: {GGUFDownloadConfig.DOWNLOAD_DIR}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self.progress.show()
        self.download_btn.setEnabled(False)
        
        worker = GGUFDownloadWorker(
            repo_id=self.current_repo_id,
            gguf_filename=filename,
            save_path=GGUFDownloadConfig.DOWNLOAD_DIR
        )
        worker.signals.progress.connect(self.update_progress)
        worker.signals.result.connect(self.on_download_complete)
        worker.signals.error.connect(self.show_error)
        self.thread_pool.start(worker)
    
    def update_progress(self, percent: int, message: str):
        """更新进度"""
        self.progress.setValue(percent)
        self.status.setText(message)
    
    def on_download_complete(self, save_path: str):
        """下载完成"""
        self.progress.hide()
        self.download_btn.setEnabled(True)
        QMessageBox.information(
            self,
            "下载完成",
            f"GGUF 模型已下载到:\n{save_path}"
        )
    
    def show_error(self, error_msg: str):
        """显示错误"""
        self.progress.hide()
        self.download_btn.setEnabled(True)
        QMessageBox.critical(self, "错误", error_msg)
