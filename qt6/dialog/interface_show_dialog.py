from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QApplication, QHBoxLayout, QHeaderView, QFormLayout
)
from common.const.common_const import common_const, model_enum


class AddMessageDialog(QDialog):
    def __init__(self, parent=None, name="", value=""):
        super().__init__(parent)
        self.setWindowTitle("编辑消息")

        layout = QVBoxLayout()

        # Role 输入框
        self.name_label = QLabel("Role:")
        self.name_edit = QLineEdit(name)
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)

        # Content 输入框
        self.value_label = QLabel("Content:")
        self.value_edit = QLineEdit(value)
        layout.addWidget(self.value_label)
        layout.addWidget(self.value_edit)

        # 保存和取消按钮
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # 连接按钮信号
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def get_data(self):
        name = self.name_edit.text().strip()
        value = self.value_edit.text().strip()
        return {
            "name": name,
            "value": value
        }

    def accept(self):
        data = self.get_data()
        if not data["name"] or not data["value"]:
            # 如果 name 或 value 为空，则不提交保存
            return
        super().accept()


class interface_show_dialog(QDialog):
    def __init__(self, parent=None, flag=False, title="添加接口", interface_name="", interface_parameters=None):
        super().__init__(parent)
        self.flag = flag
        self.setWindowTitle(title)
        self.interface_name = interface_name
        # 布局
        layout = QVBoxLayout()

        # 接口名称输入框
        self.interface_name_label = QLabel("接口名称:")
        self.interface_name_edit = QLineEdit()
        layout.addWidget(self.interface_name_label)
        layout.addWidget(self.interface_name_edit)

        # 接口类型下拉选择框
        self.interface_type_label = QLabel("接口类型:")
        self.interface_type_combo = QComboBox()
        for interface_type_dict_item in common_const.interface_type_dict:
            self.interface_type_combo.addItem(interface_type_dict_item)
        layout.addWidget(self.interface_type_label)
        layout.addWidget(self.interface_type_combo)

        # 动态参数布局
        self.dynamic_params_layout = QFormLayout()

        # 模型名称输入框
        model_name_label = QLabel("模型名称:")
        self.model_name_edit = QLineEdit()
        if self.flag:
            self.model_name_edit.setReadOnly(True)  # 设置为只读
            self.model_name_edit.setStyleSheet("background-color: lightgray;")  # 设置背景颜色为灰色

        self.dynamic_params_layout.addRow(model_name_label, self.model_name_edit)

        # API Key 输入框
        api_key_label = QLabel("API Key:")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)  # 设置为密码模式
        self.api_key_edit.setReadOnly(False)  # 可以编辑
        self.api_key_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # 禁用右键菜单

        self.dynamic_params_layout.addRow(api_key_label, self.api_key_edit)

        # Base URL 输入框
        base_url_label = QLabel("Base URL:")
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setReadOnly(False)  # 可以编辑
        self.base_url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # 禁用右键菜单

        self.dynamic_params_layout.addRow(base_url_label, self.base_url_edit)

        layout.addLayout(self.dynamic_params_layout)

        interface_temperature_label = QLabel("Temperature:")
        self.interface_temperature_edit = QLineEdit()
        layout.addWidget(interface_temperature_label)
        layout.addWidget(self.interface_temperature_edit)

        interface_top_p_label = QLabel("Top-p:")
        self.interface_top_p_edit = QLineEdit()
        layout.addWidget(interface_top_p_label)
        layout.addWidget(self.interface_top_p_edit)

        interface_n_label = QLabel("N:")
        self.interface_n_edit = QLineEdit()
        layout.addWidget(interface_n_label)
        layout.addWidget(self.interface_n_edit)

        interface_max_tokens_label = QLabel("Max Tokens:")
        self.interface_max_tokens_edit = QLineEdit()
        layout.addWidget(interface_max_tokens_label)
        layout.addWidget(self.interface_max_tokens_edit)

        interface_presence_penalty_label = QLabel("Presence Penalty:")
        self.interface_presence_penalty_edit = QLineEdit()
        layout.addWidget(interface_presence_penalty_label)
        layout.addWidget(self.interface_presence_penalty_edit)

        interface_frequency_penalty_label = QLabel("Frequency Penalty:")
        self.interface_frequency_penalty_edit = QLineEdit()
        layout.addWidget(interface_frequency_penalty_label)
        layout.addWidget(self.interface_frequency_penalty_edit)

        interface_timeout_label = QLabel("Timeout (s):")
        self.interface_timeout_edit = QLineEdit()
        layout.addWidget(interface_timeout_label)
        layout.addWidget(self.interface_timeout_edit)

        self.model_name_edit.setPlaceholderText("Qwen2.5-0.5B")
        self.api_key_edit.setPlaceholderText("KjHgFtDzXvNmLpQwRcEa:VbNfTrDxJmZqLkPnGhWc")
        self.base_url_edit.setPlaceholderText("https://spark-api-open.xf-yun.com/v1")
        # self.model_name_edit.setPlaceholderText("deepseek-chat")
        # self.api_key_edit.setPlaceholderText("sk-d0072ee63cc14e82be849eb5f92d8c63")
        # self.base_url_edit.setPlaceholderText("https://api.deepseek.com")

        self.interface_temperature_edit.setPlaceholderText(str(1.0))
        self.interface_top_p_edit.setPlaceholderText(str(1.0))
        self.interface_n_edit.setPlaceholderText(str(1))
        self.interface_max_tokens_edit.setPlaceholderText(str(60))
        self.interface_presence_penalty_edit.setPlaceholderText(str(0.0))
        self.interface_frequency_penalty_edit.setPlaceholderText(str(0.0))
        self.interface_timeout_edit.setPlaceholderText(str(4096))

        # 消息信息标签和按钮
        message_layout = QHBoxLayout()
        self.message_label = QLabel("消息信息:")
        message_layout.addWidget(self.message_label)
        message_layout.addStretch()  # 将按钮推到右侧

        # 添加和删除按钮
        self.add_button = QPushButton("Add")
        self.delete_button = QPushButton("Delete")
        self.add_button.setMaximumWidth(70)  # 调整按钮宽度
        self.delete_button.setMaximumWidth(70)  # 调整按钮宽度
        message_layout.addWidget(self.add_button)
        message_layout.addWidget(self.delete_button)

        layout.addLayout(message_layout)

        # 消息信息表格
        self.message_table = QTableWidget(2, 2)  # 预先设置两行
        self.message_table.setHorizontalHeaderLabels(["role", "content"])
        self.message_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.message_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 设置为不可编辑
        self.message_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)  # 允许选择整行
        self.message_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # 单选

        # 预设两个消息条目
        self.message_table.setItem(0, 0, QTableWidgetItem("user"))
        self.message_table.setItem(0, 1, QTableWidgetItem("你是谁"))
        self.message_table.setItem(1, 0, QTableWidgetItem("assistant"))
        self.message_table.setItem(1, 1, QTableWidgetItem("我是你的助手"))

        layout.addWidget(self.message_table)

        # 保存和取消按钮
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # 连接按钮信号
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.add_button.clicked.connect(self.add_message)
        self.delete_button.clicked.connect(self.delete_selected_row)

        # 连接表格的双击事件
        self.message_table.itemDoubleClicked.connect(self.edit_selected_row)

        # 连接表格的选择变化信号
        self.message_table.itemSelectionChanged.connect(self.copy_selected_row_to_clipboard)

        # 初始化 interface_parameters
        self.interface_parameters = {}
        if interface_parameters is not None and interface_parameters:  # 判断是否为非空字典
            self.interface_parameters = interface_parameters
            self.set_data()
            self.interface_name_edit.setEnabled(False)

    @pyqtSlot()
    def add_message(self):
        dialog = AddMessageDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self.add_message_pair(data)

    def message_table_clear(self):
        self.message_table.clearContents()
        self.message_table.setRowCount(0)

    @pyqtSlot()
    def add_message_pair(self, message):
        """
        添加单个消息到消息表中。

        :param message: 消息字典，包含 "role" 和 "content" 键
        """
        role = message["role"]
        content = message["content"]
        row_count = self.message_table.rowCount()
        self.message_table.insertRow(row_count)
        self.message_table.setItem(row_count, 0, QTableWidgetItem(role))
        self.message_table.setItem(row_count, 1, QTableWidgetItem(content))

    @pyqtSlot()
    def edit_selected_row(self, item):
        selected_items = self.message_table.selectedItems()
        if selected_items:
            role = selected_items[0].text()
            content = selected_items[1].text()
            dialog = AddMessageDialog(self, role, content)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                current_row = self.message_table.currentRow()
                self.message_table.setItem(current_row, 0, QTableWidgetItem(data["name"]))
                self.message_table.setItem(current_row, 1, QTableWidgetItem(data["value"]))

    @pyqtSlot()
    def delete_selected_row(self):
        selected_items = self.message_table.selectedItems()
        if selected_items:
            current_row = self.message_table.currentRow()
            self.message_table.removeRow(current_row)

    @pyqtSlot()
    def copy_selected_row_to_clipboard(self):
        selected_items = self.message_table.selectedItems()
        if selected_items:
            role = selected_items[0].text()
            content = selected_items[1].text()
            json_data = f'{{"role": "{role}", "content": "{content}"}}'
            clipboard = QApplication.clipboard()
            clipboard.setText(json_data, QClipboard.Mode.Clipboard)

    def get_data(self):
        interface_name = self.interface_name_edit.text() if self.interface_name_edit.text() else self.interface_name_edit.placeholderText()
        interface_type = self.interface_type_combo.currentText()
        model_name = self.model_name_edit.text() if self.model_name_edit.text() else self.model_name_edit.placeholderText()
        api_key = self.api_key_edit.text() if self.api_key_edit.text() else self.api_key_edit.placeholderText()
        base_url = self.base_url_edit.text() if self.base_url_edit.text() else self.base_url_edit.placeholderText()
        messages = []
        roles = set()  # 用于存储已经出现过的角色
        for row in range(self.message_table.rowCount()):
            role = self.message_table.item(row, 0).text()
            content = self.message_table.item(row, 1).text()
            if role not in roles:
                messages.append({"role": role, "content": content})
                roles.add(role)

        self.interface_parameters[common_const.model_name] = interface_name
        self.interface_parameters[common_const.interface_type] = interface_type
        self.interface_parameters[common_const.model_type_name] = model_name
        self.interface_parameters[common_const.interface_api_key] = api_key
        self.interface_parameters[common_const.interface_base_url] = base_url
        self.interface_parameters[common_const.interface_message_dict] = messages
        self.interface_parameters[common_const.model_type] = model_enum.interface

        interface_temperature = float(
            self.interface_temperature_edit.text() if self.interface_temperature_edit.text() else self.interface_temperature_edit.placeholderText())
        interface_top_p = float(
            self.interface_top_p_edit.text() if self.interface_top_p_edit.text() else self.interface_top_p_edit.placeholderText())
        interface_n = int(
            self.interface_n_edit.text() if self.interface_n_edit.text() else self.interface_n_edit.placeholderText())
        interface_max_tokens = int(
            self.interface_max_tokens_edit.text() if self.interface_max_tokens_edit.text() else self.interface_max_tokens_edit.placeholderText())
        interface_presence_penalty = float(
            self.interface_presence_penalty_edit.text() if self.interface_presence_penalty_edit.text() else self.interface_presence_penalty_edit.placeholderText())
        interface_frequency_penalty = float(
            self.interface_frequency_penalty_edit.text() if self.interface_frequency_penalty_edit.text() else self.interface_frequency_penalty_edit.placeholderText())
        interface_timeout = float(
            self.interface_timeout_edit.text() if self.interface_timeout_edit.text() else self.interface_timeout_edit.placeholderText())

        self.interface_parameters[common_const.temperature] = interface_temperature
        self.interface_parameters[common_const.top_p] = interface_top_p
        self.interface_parameters[common_const.top_n] = interface_n
        self.interface_parameters[common_const.max_tokens] = interface_max_tokens
        self.interface_parameters[common_const.presence_penalty] = interface_presence_penalty
        self.interface_parameters[common_const.frequency_penalty] = interface_frequency_penalty
        self.interface_parameters[common_const.timeout] = interface_timeout
        return self.interface_parameters

    def set_data(self):
        self.interface_name_edit.setText(self.interface_parameters[common_const.model_name])
        index = self.interface_type_combo.findText(self.interface_parameters[common_const.interface_type])
        if index >= 0:  # 确保找到的项存在
            self.interface_type_combo.setCurrentIndex(index)
        self.model_name_edit.setText(self.interface_parameters[common_const.model_type_name])
        self.api_key_edit.setText(self.interface_parameters[common_const.interface_api_key])
        self.base_url_edit.setText(self.interface_parameters[common_const.interface_base_url])

        self.interface_temperature_edit.setText(
            str(self.interface_parameters.get(common_const.temperature, 0)))
        self.interface_top_p_edit.setText(str(self.interface_parameters.get(common_const.top_p, 0)))
        self.interface_n_edit.setText(str(self.interface_parameters.get(common_const.top_n, 0)))
        self.interface_max_tokens_edit.setText(str(self.interface_parameters.get(common_const.max_tokens, 0)))
        self.interface_presence_penalty_edit.setText(
            str(self.interface_parameters.get(common_const.presence_penalty, 0)))
        self.interface_frequency_penalty_edit.setText(
            str(self.interface_parameters.get(common_const.frequency_penalty, 0)))
        self.interface_timeout_edit.setText(str(self.interface_parameters.get(common_const.timeout, 0)))

        self.message_table_clear()
        for item in self.interface_parameters[common_const.interface_message_dict]:
            self.add_message_pair(item)
