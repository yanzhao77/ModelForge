"""Dataset page with non-blocking API operations."""
import json

from api_client.client import ModelForgeClient
from components.api_worker import AsyncApiMixin
from components.example_library import open_examples
from components.mf.primitives import MFSection, MFStatusBadge
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DatasetPage(QWidget, AsyncApiMixin):
    """Dataset management without blocking the Qt event loop on HTTP I/O."""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._init_async_api()
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(MFSection("数据工作区", "数据集"))
        header.addStretch(1)
        self.registry_status = MFStatusBadge("Syncing datasets", "warning")
        header.addWidget(self.registry_status)
        lay.addLayout(header)
        top = QHBoxLayout()
        self.name_input = QTextEdit()
        self.name_input.setFixedHeight(30)
        self.name_input.setPlaceholderText("数据集名称（可选）")
        top.addWidget(self.name_input, 1)
        upload_btn = QPushButton("添加数据集")
        upload_btn.clicked.connect(self.upload)
        top.addWidget(upload_btn)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        examples = QPushButton("示例")
        examples.clicked.connect(lambda: open_examples("datasets", self))
        top.addWidget(examples)
        lay.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "格式", "行数", "大小", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        ops = QHBoxLayout()
        for label, handler in (("PREVIEW", self.preview), ("Training preflight", self.validate), ("Delete selected", self.delete_selected)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            ops.addWidget(button)
        ops.addStretch()
        lay.addLayout(ops)

        self.hint = QLabel("支持格式: jsonl / csv / json / txt（训练前建议先做“训练预检”）")
        lay.addWidget(self.hint)

    def refresh(self):
        self.hint.setText("正在加载数据集...")
        self._run_api(self.api.list_datasets, self._render_datasets, self._show_load_error)

    def _render_datasets(self, datasets):
        self.table.setRowCount(len(datasets))
        for row, dataset in enumerate(datasets):
            for col, key in enumerate(["id", "name", "format", "row_count", "file_size", "status"]):
                text = str(dataset.get(key, ""))
                if key == "file_size" and dataset.get("file_size"):
                    text = f"{dataset['file_size'] / 1024:.1f} KB"
                self.table.setItem(row, col, QTableWidgetItem(text))
            self.table.item(row, 0).setData(Qt.UserRole, dataset.get("id"))
        self.hint.setText(f"已加载 {len(datasets)} 个数据集")
        self.registry_status.set_state(f"{len(datasets)} datasets synced", "online")

    def _show_load_error(self, error):
        self.registry_status.set_state("Datasets unavailable", "error")
        self.hint.setText(f"加载失败: {error}")

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择数据集", "", "数据集 (*.jsonl *.csv *.json *.txt)")
        if not path:
            return
        name = self.name_input.toPlainText().strip() or None
        self.hint.setText("上传中...")
        self._run_api(lambda: self.api.upload_dataset(path, name), self._on_uploaded, lambda error: QMessageBox.warning(self, "上传失败", error))

    def _on_uploaded(self, result):
        if result.get("status") == "error":
            QMessageBox.warning(self, "解析失败", result.get("error", ""))
            return
        self.hint.setText(f"上传成功: {result.get('name')} ({result.get('row_count', 0)} 行)")
        self.refresh()

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def preview(self):
        dataset_id = self._selected_id()
        if dataset_id is not None:
            self._run_api(lambda: self.api.get_dataset(dataset_id), self._show_preview, lambda error: QMessageBox.warning(self, "失败", error))

    def _show_preview(self, dataset):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"预览: {dataset.get('name')}")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(json.dumps(dataset.get("sample", []), ensure_ascii=False, indent=2))
        layout.addWidget(edit)
        dialog.exec_()

    def validate(self):
        dataset_id = self._selected_id()
        if dataset_id is None:
            QMessageBox.warning(self, "提示", "请先选择一个数据集")
            return
        self._run_api(lambda: self.api.validate_dataset(dataset_id), self._show_validation, lambda error: QMessageBox.warning(self, "预检失败", error))

    def _show_validation(self, result):
        if result.get("ok"):
            QMessageBox.information(self, "预检通过", f"可用于训练: {result.get('row_count')} 行\n列: {result.get('columns')}")
        else:
            QMessageBox.warning(self, "预检未通过", result.get("reason", "未知原因"))

    def delete_selected(self):
        dataset_id = self._selected_id()
        if dataset_id is None:
            return
        if QMessageBox.question(self, "确认", "确定删除该数据集？") == QMessageBox.Yes:
            self._run_api(lambda: self.api.delete_dataset(dataset_id), lambda _: self.refresh(), lambda error: QMessageBox.warning(self, "失败", error))
