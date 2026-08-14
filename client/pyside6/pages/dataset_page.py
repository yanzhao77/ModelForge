"""数据集管理页面：上传 / 列表 / 预览 / 校验 / 删除。"""
import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QDialog, QTextEdit,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt

from api_client.client import ModelForgeClient


class DatasetPage(QWidget):
    """数据集管理（与训练页面联动：训练表单从此页数据中选择）。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("数据集名称:"));
        self.name_input = QLineEdit();
        self.name_input.setPlaceholderText("可选，默认取文件名");
        top.addWidget(self.name_input, 1);
        upload_btn = QPushButton("上传数据集...");
        upload_btn.clicked.connect(self.upload);
        top.addWidget(upload_btn);
        refresh_btn = QPushButton("刷新");
        refresh_btn.clicked.connect(self.refresh);
        top.addWidget(refresh_btn);
        lay.addLayout(top)

        self.table = QTableWidget();
        self.table.setColumnCount(6);
        self.table.setHorizontalHeaderLabels(["ID", "名称", "格式", "行数", "大小", "状态"]);
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch);
        lay.addWidget(self.table, 1)

        ops = QHBoxLayout()
        preview_btn = QPushButton("预览");
        preview_btn.clicked.connect(self.preview);
        ops.addWidget(preview_btn);
        validate_btn = QPushButton("训练预检");
        validate_btn.clicked.connect(self.validate);
        ops.addWidget(validate_btn);
        delete_btn = QPushButton("删除选中");
        delete_btn.clicked.connect(self.delete_selected);
        ops.addWidget(delete_btn);
        ops.addStretch();
        lay.addLayout(ops)

        self.hint = QLabel("支持格式: jsonl / csv / json / txt（训练前建议先做"训练预检"）");
        lay.addWidget(self.hint)

    def refresh(self):
        try:
            datasets = self.api.list_datasets();
        except Exception as e:
            self.hint.setText(f"加载失败: {e}");
            return;
        self.table.setRowCount(len(datasets));
        for row, d in enumerate(datasets):
            for col, key in enumerate(["id", "name", "format", "row_count", "file_size", "status"]):
                text = str(d.get(key, ""));
                if key == "file_size" and d.get("file_size"):
                    text = f"{d['file_size'] / 1024:.1f} KB";
                self.table.setItem(row, col, QTableWidgetItem(text));
            self.table.item(row, 0).setData(Qt.UserRole, d.get("id"))

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据集", "", "数据集 (*.jsonl *.csv *.json *.txt)");
        if not path: return;
        name = self.name_input.text().strip() or None;
        self.hint.setText("上传中...");
        try:
            result = self.api.upload_dataset(path, name);
            if result.get("status") == "error":
                QMessageBox.warning(self, "解析失败", result.get("error", ""));
            else:
                self.hint.setText(
                    f"上传成功: {result.get('name')} ({result.get('row_count', 0)} 行)");
            self.refresh();
        except Exception as e:
            QMessageBox.warning(self, "上传失败", str(e))

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows();
        if not rows: return None;
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole)

    def preview(self):
        ds_id = self._selected_id();
        if ds_id is None: return;
        try:
            d = self.api.get_dataset(ds_id);
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e));
            return;
        text = json.dumps(d.get("sample", []), ensure_ascii=False, indent=2);
        dlg = QDialog(self);
        dlg.setWindowTitle(f"预览: {d.get('name')}");
        dlg.resize(520, 360);
        lay = QVBoxLayout(dlg);
        edit = QTextEdit();
        edit.setReadOnly(True);
        edit.setPlainText(text);
        lay.addWidget(edit);
        dlg.exec_()

    def validate(self):
        ds_id = self._selected_id();
        if ds_id is None:
            QMessageBox.warning(self, "提示", "请先选择一个数据集");
            return;
        try:
            result = self.api.validate_dataset(ds_id);
        except Exception as e:
            QMessageBox.warning(self, "预检失败", str(e));
            return;
        if result.get("ok"):
            QMessageBox.information(
                self, "预检通过", f"可用于训练: {result.get('row_count')} 行\n列: {result.get('columns')}");
        else:
            QMessageBox.warning(self, "预检未通过", result.get("reason", "未知原因"))

    def delete_selected(self):
        ds_id = self._selected_id();
        if ds_id is None: return;
        if QMessageBox.question(self, "确认", "确定删除该数据集？") == QMessageBox.Yes:
            try:
                self.api.delete_dataset(ds_id);
                self.refresh();
            except Exception as e:
                QMessageBox.warning(self, "失败", str(e))