import json

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QMenu, QDialog

from common.const.common_const import common_const, model_enum
from pyqt6.dialog.interface_manager_dialog import InterfaceManagerDialog
from pyqt6.dialog.interface_open_dialog import interface_open_dialog
from pyqt6.dialog.interface_show_dialog import interface_show_dialog


class interface_menu(QMenuBar):
    def __init__(self, menu_Bar, mainWindow):
        super().__init__(menu_Bar)
        self.mainWindow = mainWindow
        interface_menu = menu_Bar.addMenu('接口')
        self.interface_parameters = self.mainWindow.models_parameters
        create_interface = QAction("添加接口", self)
        interface_menu.addAction(create_interface)

        open_interface = QAction("打开接口", self)
        interface_menu.addAction(open_interface)

        interface_management = QAction("接口管理", self)
        interface_menu.addAction(interface_management)

        self.interface_list_menu = QMenu("最近列表", self)
        interface_menu.addMenu(self.interface_list_menu)
        interface_menu.addSeparator()

        # 连接动作到槽函数
        create_interface.triggered.connect(self.create_interface)
        open_interface.triggered.connect(self.open_interface)
        interface_management.triggered.connect(self.interface_management)

        # self.interface_list_menu.aboutToShow.connect(self.recent_interface_list_menu)

    @pyqtSlot()
    def create_interface(self):
        dialog = interface_show_dialog(self, flag=False)  # 创建对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 获取接口数据
            interface_parameters_dict = dialog.get_data()
            self.interface_parameters[
                interface_parameters_dict[common_const.model_name]] = interface_parameters_dict

    @pyqtSlot()
    def open_interface(self):
        dialog = interface_open_dialog(self, self.interface_parameters)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_interface = dialog.get_selected_interface()
            if selected_interface:
                self.load_interface(self.interface_parameters[selected_interface])

    def load_interface(self, interface_parameters_dict):
        self.mainWindow.tree_view.load_for_treeview(interface_parameters_dict)

        recent_file_action = QAction(interface_parameters_dict[common_const.model_name], self)
        self.interface_list_menu.addAction(recent_file_action)

    @pyqtSlot()
    def interface_management(self):
        dialog = InterfaceManagerDialog(self, interfaces=self.interface_parameters)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pass

    def clear_interface_list(self):
        self.mainWindow.clear_ui()

    def update_interface_list(self):
        pass

    @pyqtSlot()
    def refresh_interface(self):
        pass

    @pyqtSlot()
    def recent_interface_list_menu(self):
        # 清空现有的子菜单
        self.interface_list_menu.clear()

    def load_default_interface(self):
        default_interface_parameters = {}
        default_interface_parameters[common_const.model_name] = "Spark Lite"
        default_interface_parameters[common_const.model_type] = model_enum.interface
        default_interface_parameters[common_const.parameters_editable] = True
        default_interface_parameters[common_const.interface_type] = "OpenAI"
        default_interface_parameters[common_const.interface_model_name] = "general"
        default_interface_parameters[common_const.interface_role] = "user"
        default_interface_parameters[
            common_const.interface_api_key] = "lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll"  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
        default_interface_parameters[
            common_const.interface_base_url] = 'https://spark-api-open.xf-yun.com/v1'  # 填写DashScope SDK的base_url

        # 定义 JSON 格式的字符串
        a = f'{{"role": "user", "content": "你是谁"}}'
        b = f'{{"role": "assistant", "content": "我是你的助手"}}'

        # 将字符串解析为字典
        dict_a = json.loads(a)
        dict_b = json.loads(b)
        default_interface_parameters[common_const.interface_message_dict] = (dict_a, dict_b)
        self.interface_parameters[
            default_interface_parameters[common_const.model_name]] = default_interface_parameters
        return default_interface_parameters
