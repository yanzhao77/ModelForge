from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QTableWidget,
                             QTableWidgetItem, QHBoxLayout, QMessageBox, QHeaderView)

from common.const.common_const import common_const
from pyqt6.dialog.interface_show_dialog import interface_show_dialog


class InterfaceManagerDialog(QDialog):
    def __init__(self, parent=None, interfaces=None):
        super().__init__(parent)
        self.setWindowTitle("接口管理")

        # 初始化接口列表
        self.interfaces = interfaces if interfaces else {}

        # 布局
        layout = QVBoxLayout()

        # 创建表格并设置列头
        self.table = QTableWidget()
        self.table.setColumnCount(5)

        # 添加现有接口到表格
        self.populate_table()

        # 按钮布局
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("添加接口")
        self.edit_button = QPushButton("编辑接口")
        self.delete_button = QPushButton("删除接口")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)

        # 连接按钮信号
        self.add_button.clicked.connect(self.add_interface)
        self.edit_button.clicked.connect(self.edit_interface)
        self.delete_button.clicked.connect(self.delete_interface)

        # 将表格和按钮添加到布局中
        layout.addWidget(self.table)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def populate_table(self):
        """填充表格数据"""
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setHorizontalHeaderLabels(["接口名称", "接口类型", "模型名称", "API Key", "Base URL"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 设置为不可编辑
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)  # 允许选择整行
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # 单选
        self.table.setRowCount(len(self.interfaces))
        for row, interface in enumerate(self.interfaces.values()):
            self.table.setItem(row, 0, QTableWidgetItem(interface[common_const.interface_name]))
            self.table.setItem(row, 1, QTableWidgetItem(interface[common_const.interface_type]))
            self.table.setItem(row, 2, QTableWidgetItem(interface[common_const.interface_model_name]))
            self.table.setItem(row, 3, QTableWidgetItem(interface[common_const.interface_api_key]))
            self.table.setItem(row, 4, QTableWidgetItem(interface[common_const.interface_base_url]))

    def add_interface(self):
        """添加新接口"""
        dialog = interface_show_dialog(self, flag=False)  # 创建对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 获取接口数据
            interface_parameters_dict = dialog.get_data()
            self.interfaces[interface_parameters_dict[common_const.interface_name]] = interface_parameters_dict
            self.populate_table()

    def edit_interface(self):
        """编辑选中的接口"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            self.table.item(selected_row, 0).text()
            interface_parameters_dict = self.interfaces[self.table.item(selected_row, 0).text()]

            dialog = interface_show_dialog(self, flag=False, title="编辑接口",
                                           interface_parameters=interface_parameters_dict)  # 创建对话框
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # 获取接口数据
                updated_interface = dialog.get_data()
                self.interfaces[updated_interface[common_const.interface_name]] = updated_interface
                self.populate_table()

    def delete_interface(self):
        """删除选中的接口"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            reply = QMessageBox.question(self, '确认', '你确定要删除选中的接口吗？',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                del self.interfaces[self.table.item(selected_row, 0).text()]
                self.table.removeRow(selected_row)
