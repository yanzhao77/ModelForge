from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Slot

from common.const.common_const import common_const, model_enum


class interface_open_dialog(QDialog):
    def __init__(self, parent=None, interface_parameters=None):
        super().__init__(parent)
        self.setWindowTitle("打开接口")
        self.interface_dict = {}
        for item in interface_parameters.values():
            if item[common_const.model_type] == model_enum.interface:
                self.interface_dict[item[common_const.model_name]] = item[common_const.model_type_name]

        # 设置布局
        layout = QVBoxLayout()
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["接口名称", "Model 名称"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 设置为不可编辑
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)  # 允许选择整行
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # 单选
        # 填充表格
        self.populate_table()

        # 双击事件
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)

        layout.addWidget(self.table)
        self.setLayout(layout)

    def populate_table(self):
        self.table.setRowCount(len(self.interface_dict))
        for row, (interface_name, interface_model_name) in enumerate(self.interface_dict.items()):
            model_name_item = QTableWidgetItem(interface_model_name)
            interface_name_item = QTableWidgetItem(interface_name)

            self.table.setItem(row, 0, model_name_item)
            self.table.setItem(row, 1, interface_name_item)

    @Slot(QTableWidgetItem)
    def on_item_double_clicked(self):
        # selected_row = self.table.currentRow()
        # if selected_row >= 0:
        #     interface_name = self.table.item(selected_row, 1).text()
        self.accept()  # 关闭窗口

    def get_selected_interface(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            return self.table.item(selected_row, 1).text()
