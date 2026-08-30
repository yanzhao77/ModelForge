"""Training page with non-blocking API operations and guarded polling."""

from api_client.client import ModelForgeClient
from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error, format_text
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class TrainingPage(QWidget, AsyncApiMixin):
    """Training task UI that keeps all API calls out of the Qt GUI thread."""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._tasks = []
        self._current_task_id = None
        self._log_count = 0
        self._poll_in_flight = False
        self._init_async_api()
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)
        self.refresh_all()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("模型训练", "训练"))
        header.addStretch(1)
        self.training_status = MFStatusBadge("任务更新中", "online")
        header.addWidget(self.training_status)
        examples = QPushButton("示例")
        examples.clicked.connect(lambda: open_examples("training", self))
        header.addWidget(examples)
        layout.addLayout(header)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_config_panel())
        splitter.addWidget(self._build_task_panel())
        splitter.setSizes([420, 520])
        layout.addWidget(splitter, 1)

    def _build_config_panel(self):
        box = QGroupBox("训练配置")
        form = QFormLayout(box)
        self.base_model = QComboBox()
        self.base_model.setEditable(True)
        self.base_model.setPlaceholderText("从模型列表选择或输入 HF 模型名")
        self.method = QComboBox()
        self.method.addItem("lora", "lora")
        self.method.addItem("full", "full")
        self.dataset_combo = QComboBox()
        self.dataset_combo.setPlaceholderText("选择数据集（先在数据集页上传）")
        self.epochs = QLineEdit("3")
        self.lr = QLineEdit("2e-5")
        self.batch = QLineEdit("2")
        self.lora_r = QLineEdit("8")
        self.lora_alpha = QLineEdit("32")
        self.output_dir = QLineEdit("./outputs")
        for label, field in (("基础模型:", self.base_model), ("方法:", self.method), ("数据集:", self.dataset_combo), ("Epochs:", self.epochs), ("学习率:", self.lr), ("Batch Size:", self.batch), ("LoRA r:", self.lora_r), ("LoRA alpha:", self.lora_alpha), ("输出目录:", self.output_dir)):
            form.addRow(label, field)
        buttons = QHBoxLayout()
        template_button = QPushButton("加载模板")
        template_button.clicked.connect(self.load_template)
        buttons.addWidget(template_button)
        start_button = QPushButton("开始训练")
        start_button.clicked.connect(self.start)
        buttons.addWidget(start_button)
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.addWidget(box)
        layout.addLayout(buttons)
        layout.addStretch()
        return outer

    def _build_task_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(5)
        self.task_table.setHorizontalHeaderLabels(["任务", "模型", "方法", "状态", "进度"])
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.task_table.itemSelectionChanged.connect(self._on_task_selected)
        layout.addWidget(self.task_table, 1)
        detail = QGroupBox("运行详情")
        detail_layout = QVBoxLayout(detail)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        detail_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("未选择任务")
        detail_layout.addWidget(self.status_label)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        detail_layout.addWidget(self.log_view, 1)
        operations = QHBoxLayout()
        stop_button = QPushButton("停止运行")
        stop_button.clicked.connect(self.stop_task)
        operations.addWidget(stop_button)
        register_button = QPushButton("注册模型")
        register_button.clicked.connect(self.register_model)
        operations.addWidget(register_button)
        operations.addStretch()
        detail_layout.addLayout(operations)
        layout.addWidget(detail, 2)
        return widget

    def refresh_all(self):
        self._load_models()
        self._load_datasets()
        self._load_tasks()

    def _load_models(self):
        self._run_api(self.api.list_models, self._render_models, lambda _: self._render_models([]))

    def _render_models(self, models):
        current = self.base_model.currentText()
        self.base_model.clear()
        for model in models:
            self.base_model.addItem(model.get("name", ""))
        if current:
            self.base_model.setCurrentText(current)

    def _load_datasets(self):
        self._run_api(self.api.list_datasets, self._render_datasets, lambda _: self._render_datasets([]))

    def _render_datasets(self, datasets):
        current = self.dataset_combo.currentData()
        self.dataset_combo.clear()
        for dataset in datasets:
            self.dataset_combo.addItem(f"{dataset.get('name', '?')} ({dataset.get('row_count', 0)} 行)", dataset.get("id"))
        if current is not None:
            index = self.dataset_combo.findData(current)
            if index >= 0:
                self.dataset_combo.setCurrentIndex(index)

    def _load_tasks(self):
        self._run_api(self.api.train_tasks, self._render_tasks, lambda _: self._render_tasks([]))

    def _render_tasks(self, tasks):
        self._tasks = tasks
        self.task_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            for col, key in enumerate(["task_id", "base_model", "method", "status", "progress"]):
                text = f"{task.get('progress', 0):.0f}%" if key == "progress" else str(task.get(key, ""))
                self.task_table.setItem(row, col, QTableWidgetItem(text))
            self.task_table.item(row, 0).setData(Qt.UserRole, task.get("task_id"))
        self._show_status()

    def load_template(self):
        self._run_api(self.api.train_templates, self._apply_template, lambda _: None)

    def _apply_template(self, templates):
        config = templates.get(self.method.currentData(), {})
        self.epochs.setText(str(config.get("epochs", 3)))
        self.lr.setText(str(config.get("learning_rate", 2e-5)))
        self.batch.setText(str(config.get("batch_size", 2)))
        self.lora_r.setText(str(config.get("lora_r", 8)))
        self.lora_alpha.setText(str(config.get("lora_alpha", 32)))

    def start(self):
        dataset_id = self.dataset_combo.currentData()
        if dataset_id is None:
            QMessageBox.warning(self, format_text("提示"), format_text("请先在数据集页上传并选择一个数据集"))
            return
        try:
            config = {
                "dataset_id": dataset_id, "base_model": self.base_model.currentText().strip(),
                "method": self.method.currentData(), "epochs": int(self.epochs.text()),
                "learning_rate": float(self.lr.text()), "batch_size": int(self.batch.text()),
                "lora_r": int(self.lora_r.text()), "lora_alpha": int(self.lora_alpha.text()),
                "output_dir": self.output_dir.text().strip() or "./outputs",
            }
        except ValueError:
            QMessageBox.warning(self, format_text("配置错误"), format_text("训练配置无效。请检查轮次、学习率和批量大小。"))
            return
        if QMessageBox.question(self, format_text("确认启动训练"), format_text("训练将读取所选数据集并启动后台训练进程，是否继续？")) != QMessageBox.Yes:
            return
        self._run_api(lambda: self.api.train_start(config, confirm=True), self._on_started, lambda error: QMessageBox.warning(self, format_text("启动失败"), format_api_error(error)))

    def _on_started(self, result):
        QMessageBox.information(self, format_text("已启动"), format_text("训练任务已提交。任务标识：{task_id}", task_id=result.get("task_id", "-")))
        self._load_tasks()

    def _on_task_selected(self):
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            return
        self._current_task_id = self.task_table.item(rows[0].row(), 0).data(Qt.UserRole)
        self._log_count = 0
        self.log_view.clear()
        self._show_status()

    def _show_status(self):
        if not self._current_task_id:
            return
        for task in self._tasks:
            if task.get("task_id") == self._current_task_id:
                self.progress_bar.setValue(int(task.get("progress", 0) or 0))
                self.status_label.setText(format_text("训练状态：{status}｜轮次 {current_epoch}/{total_epochs}｜损失：{loss}", status=task.get("status", "-"), current_epoch=task.get("current_epoch", "-"), total_epochs=task.get("total_epochs", "-"), loss=task.get("loss") if task.get("loss") is not None else "-"))
                return

    def _poll(self):
        if not self._current_task_id or self._poll_in_flight:
            return
        self._poll_in_flight = True
        self._run_api(lambda: self.api.train_status(self._current_task_id), self._on_polled, self._on_poll_failure)

    def _on_poll_failure(self, _error):
        self._poll_in_flight = False

    def _on_polled(self, task):
        self._poll_in_flight = False
        for index, current in enumerate(self._tasks):
            if current.get("task_id") == self._current_task_id:
                self._tasks[index] = task
                break
        self._show_status()
        tail = task.get("log_tail", [])
        if len(tail) > self._log_count:
            for line in tail[self._log_count:]:
                self.log_view.append(line)
            self._log_count = len(tail)
        if task.get("status") in ("done", "error", "stopped"):
            self._timer.stop()
            if task.get("status") == "done":
                QMessageBox.information(self, format_text("训练完成"), format_text("可以点击“注册到模型列表”"))
        self._load_tasks()

    def stop_task(self):
        if self._current_task_id:
            if QMessageBox.question(self, format_text("确认停止训练"), format_text("确定请求停止当前训练任务？")) != QMessageBox.Yes:
                return
            self._run_api(lambda: self.api.train_stop(self._current_task_id, confirm=True), self._on_stopped, lambda error: QMessageBox.warning(self, format_text("停止失败"), format_api_error(error)))

    def _on_stopped(self, _result):
        QMessageBox.information(self, format_text("已请求停止"), format_text("已向训练进程发送停止请求。"))
        self._load_tasks()

    def register_model(self):
        if self._current_task_id:
            if QMessageBox.question(self, format_text("确认注册模型"), format_text("确定将当前训练产物注册到本地模型列表？")) != QMessageBox.Yes:
                return
            self._run_api(lambda: self.api.train_register_model(self._current_task_id, confirm=True), self._on_registered, lambda error: QMessageBox.warning(self, format_text("注册失败"), format_api_error(error)))

    def _on_registered(self, model):
        QMessageBox.information(self, format_text("已注册"), format_text("模型已注册：{name}", name=model.get("name", "-")))
        self._load_models()
