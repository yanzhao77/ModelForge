"""微调训练页面：配置表单（数据集联动）+ 任务列表 + 进度/日志 + 停止/注册模型。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QProgressBar, QTextEdit, QMessageBox, QHeaderView, QAbstractItemView, QSplitter,
)

from api_client.client import ModelForgeClient


class TrainingPage(QWidget):
    """微调训练：数据集联动 + 全参/LoRA 配置 + 任务进度与日志。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._tasks = []
        self._current_task_id = None
        self._log_count = 0
        self._init_ui()
        self._timer = QTimer(self);
        self._timer.timeout.connect(self._poll);
        self._timer.start(2000);
        self.refresh_all()

    def _init_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_config_panel());
        splitter.addWidget(self._build_task_panel());
        splitter.setSizes([420, 520]);
        lay = QVBoxLayout(self);
        lay.addWidget(splitter);
        self.setLayout(lay)

    def _build_config_panel(self) -> QWidget:
        box = QGroupBox("训练配置");
        form = QFormLayout(box)

        self.base_model = QComboBox();
        self.base_model.setEditable(True);
        self.base_model.setPlaceholderText("从模型列表选择或输入 HF 模型名");
        form.addRow("基础模型:", self.base_model);

        self.method = QComboBox();
        self.method.addItem("lora", "lora");
        self.method.addItem("full", "full");
        form.addRow("方法:", self.method);

        self.dataset_combo = QComboBox();
        self.dataset_combo.setPlaceholderText("选择数据集（先在数据集页上传）");
        form.addRow("数据集:", self.dataset_combo);

        self.epochs = QLineEdit("3");
        self.lr = QLineEdit("2e-5");
        self.batch = QLineEdit("2");
        self.lora_r = QLineEdit("8");
        self.lora_alpha = QLineEdit("32");
        self.output_dir = QLineEdit("./outputs");
        form.addRow("Epochs:", self.epochs);
        form.addRow("学习率:", self.lr);
        form.addRow("Batch Size:", self.batch);
        form.addRow("LoRA r:", self.lora_r);
        form.addRow("LoRA alpha:", self.lora_alpha);
        form.addRow("输出目录:", self.output_dir);

        btns = QHBoxLayout();
        tpl_btn = QPushButton("加载模板");
        tpl_btn.clicked.connect(self.load_template);
        btns.addWidget(tpl_btn);
        start_btn = QPushButton("开始训练");
        start_btn.clicked.connect(self.start);
        btns.addWidget(start_btn);
        box.setLayout(form);
        outer = QWidget();
        o = QVBoxLayout(outer);
        o.addWidget(box);
        o.addLayout(btns);
        o.addStretch();
        return outer

    def _build_task_panel(self) -> QWidget:
        w = QWidget();
        lay = QVBoxLayout(w)

        self.task_table = QTableWidget();
        self.task_table.setColumnCount(5);
        self.task_table.setHorizontalHeaderLabels(["任务", "模型", "方法", "状态", "进度"]);
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows);
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers);
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch);
        self.task_table.itemSelectionChanged.connect(self._on_task_selected);
        lay.addWidget(self.task_table, 1)

        detail = QGroupBox("任务详情");
        dl = QVBoxLayout(detail);
        self.progress_bar = QProgressBar();
        self.progress_bar.setRange(0, 100);
        dl.addWidget(self.progress_bar);
        self.status_label = QLabel("未选择任务");
        dl.addWidget(self.status_label);
        self.log_view = QTextEdit();
        self.log_view.setReadOnly(True);
        dl.addWidget(self.log_view, 1);
        ops = QHBoxLayout();
        stop_btn = QPushButton("停止");
        stop_btn.clicked.connect(self.stop_task);
        ops.addWidget(stop_btn);
        reg_btn = QPushButton("注册到模型列表");
        reg_btn.clicked.connect(self.register_model);
        ops.addWidget(reg_btn);
        ops.addStretch();
        dl.addLayout(ops);
        lay.addWidget(detail, 2);
        return w

    def refresh_all(self):
        self._load_models();
        self._load_datasets();
        self._load_tasks();

    def _load_models(self):
        try:
            models = self.api.list_models();
        except Exception:
            models = [];
        self.base_model.clear();
        for m in models:
            self.base_model.addItem(m.get("name", ""));

    def _load_datasets(self):
        current = self.dataset_combo.currentData();
        try:
            datasets = self.api.list_datasets();
        except Exception:
            datasets = [];
        self.dataset_combo.clear();
        for d in datasets:
            label = f"{d.get('name', '?')} ({d.get('row_count', 0)} 行)";
            self.dataset_combo.addItem(label, d.get("id"));
        if current is not None:
            idx = self.dataset_combo.findData(current);
            if idx >= 0: self.dataset_combo.setCurrentIndex(idx)

    def _load_tasks(self):
        try:
            self._tasks = self.api.train_tasks();
        except Exception:
            self._tasks = [];
        self.task_table.setRowCount(len(self._tasks));
        for row, t in enumerate(self._tasks):
            for col, key in enumerate(["task_id", "base_model", "method", "status", "progress"]):
                text = str(t.get(key, ""));
                if key == "progress": text = f"{t.get('progress', 0):.0f}%";
                self.task_table.setItem(row, col, QTableWidgetItem(text));
            self.task_table.item(row, 0).setData(Qt.UserRole, t.get("task_id"))

    def load_template(self):
        try:
            tpl = self.api.train_templates();
        except Exception:
            return;
        m = self.method.currentData();
        cfg = tpl.get(m, {});
        self.epochs.setText(str(cfg.get("epochs", 3)));
        self.lr.setText(str(cfg.get("learning_rate", 2e-5)));
        self.batch.setText(str(cfg.get("batch_size", 2)));
        self.lora_r.setText(str(cfg.get("lora_r", 8)));
        self.lora_alpha.setText(str(cfg.get("lora_alpha", 32)));

    def start(self):
        ds_id = self.dataset_combo.currentData();
        if ds_id is None:
            QMessageBox.warning(self, "提示", "请先在数据集页上传并选择一个数据集");
            return;
        try:
            config = {
                "dataset_id": ds_id,
                "base_model": self.base_model.currentText().strip(),
                "method": self.method.currentData(),
                "epochs": int(self.epochs.text()),
                "learning_rate": float(self.lr.text()),
                "batch_size": int(self.batch.text()),
                "lora_r": int(self.lora_r.text()),
                "lora_alpha": int(self.lora_alpha.text()),
                "output_dir": self.output_dir.text().strip() or "./outputs",
            };
            result = self.api.train_start(config);
            QMessageBox.information(self, "已启动", f"训练任务已启动: {result.get('task_id')}");
            self._load_tasks();
        except Exception as e:
            QMessageBox.warning(self, "启动失败", str(e))

    def _on_task_selected(self):
        rows = self.task_table.selectionModel().selectedRows();
        if not rows: return;
        self._current_task_id = self.task_table.item(rows[0].row(), 0).data(Qt.UserRole);
        self._log_count = 0;
        self.log_view.clear();
        self._show_status()

    def _show_status(self):
        if not self._current_task_id: return;
        for t in self._tasks:
            if t.get("task_id") == self._current_task_id:
                self.progress_bar.setValue(int(t.get("progress", 0) or 0));
                self.status_label.setText(
                    f"状态: {t.get('status')} | Epoch {t.get('current_epoch')}/{t.get('total_epochs')} | 
                    f"loss: {t.get('loss') if t.get('loss') is not None else '-'}"
                );
                return

    def _poll(self):
        if not self._current_task_id: return;
        try:
            t = self.api.train_status(self._current_task_id);
        except Exception:
            return;
        for i, task in enumerate(self._tasks):
            if task.get("task_id") == self._current_task_id:
                self._tasks[i] = t;
                break;
        self._show_status();
        # append new log lines
        tail = t.get("log_tail", []);
        if len(tail) > self._log_count:
            for line in tail[self._log_count:]:
                self.log_view.append(line);
            self._log_count = len(tail);
        # 任务结束/错误提示
        if t.get("status") in ("done", "error", "stopped"):
            self._timer.stop();
            if t.get("status") == "done":
                QMessageBox.information(self, "训练完成", "可以点击"注册到模型列表"");
        self._load_tasks()

    def stop_task(self):
        if not self._current_task_id: return;
        try:
            self.api.train_stop(self._current_task_id);
            QMessageBox.information(self, "已请求停止", "正在终止训练进程...");
            self._load_tasks();
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def register_model(self):
        if not self._current_task_id: return;
        try:
            model = self.api.train_register_model(self._current_task_id);
            QMessageBox.information(self, "已注册", f"模型已注册: {model.get('name')}");
            self._load_models();
        except Exception as e:
            QMessageBox.warning(self, "注册失败", str(e))