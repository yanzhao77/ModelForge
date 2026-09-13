"""Model inventory and download dialogs with non-blocking API operations."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from i18n.ui_localizer import format_api_error
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
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
