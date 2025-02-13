import os

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QMenu, QDialog, QMessageBox

from common.const.common_const import common_const, model_enum
from qt6 import MainWindow
from qt6.dialog.model_open_dialog import model_open_dialog
from qt6.dialog.model_parameters_dialog import model_parameters_dialog


class model_menu(QMenuBar):
    def __init__(self, menu_Bar=QMenuBar, mainWindow=MainWindow):
        super().__init__(menu_Bar)
        self.mainWindow = mainWindow
        model_menu = menu_Bar.addMenu('模型')
        self.models_parameters = mainWindow.models_parameters
        create_file = QAction("重置列表", self)
        model_menu.addAction(create_file)

        open_file = QAction("打开模型", self)
        model_menu.addAction(open_file)
        self.recent_models_menu = QMenu("最近模型", self)
        model_menu.addMenu(self.recent_models_menu)
        model_menu.addSeparator()
        model_menu.addAction('刷新')
        model_menu.addSeparator()
        # script_menu = QMenu('自动化脚本', self)
        # script_menu.addAction(QAction('脚本执行', self))
        # script_menu.addAction(QAction('录制脚本', self))
        # file_menu.addMenu(script_menu)

        model_menu.addSeparator()
        clear_file = QAction("清空", self)
        model_menu.addAction(clear_file)

        model_menu.addSeparator()
        model_parameters = QAction("模型参数", self)
        model_menu.addAction(model_parameters)

        model_menu.addSeparator()
        restart_file = QAction("重启", self)
        model_menu.addAction(restart_file)

        model_menu.addSeparator()
        exit_file = QAction("退出", self)
        model_menu.addAction(exit_file)

        # 连接动作到槽函数
        create_file.triggered.connect(self.create_file)
        exit_file.triggered.connect(self.exit_file)
        restart_file.triggered.connect(self.restart_file)
        model_parameters.triggered.connect(self.model_parameters_setting)
        clear_file.triggered.connect(self.clear_file)
        open_file.triggered.connect(self.open_model)
        self.recent_models_menu.aboutToShow.connect(self.recent_model_list)

    @pyqtSlot()
    def create_file(self):
        self.mainWindow.tree_clear()
        self.mainWindow.tree_view.load_default_model_for_treeview()

    @pyqtSlot()
    def open_model(self):
        dialog = model_open_dialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.model_name and dialog.model_path:
                self.setting_model_default_parameters(dialog.model_name, dialog.model_path)
                self.mainWindow.tree_view.load_model(dialog.model_name, dialog.model_path)

    def clear_file(self):
        self.mainWindow.clear_ui()

    @pyqtSlot()
    def exit_file(self):
        self.mainWindow.exit_ui()

    @pyqtSlot()
    def restart_file(self):
        self.mainWindow.restart()

    @pyqtSlot()
    def recent_model_list(self):
        # 清空现有的子菜单
        self.recent_models_menu.clear()
        # 如果没有最近文件，显示提示信息
        if not self.mainWindow.recent_models:
            no_recent_files_action = QAction("无最近模型", self)
            no_recent_files_action.setEnabled(False)
            self.recent_models_menu.addAction(no_recent_files_action)
            return

        # 添加最近文件到子菜单
        for file in self.mainWindow.recent_models:
            recent_file_action = QAction(file, self)
            recent_file_action.triggered.connect(lambda checked, f=file: self.mainWindow.tree_view.load_model(f,
                                                                                                              self.models_parameters[
                                                                                                                  f][
                                                                                                                  common_const.model_path]))
            self.recent_models_menu.addAction(recent_file_action)

    def model_parameters_setting(self):
        if not self.mainWindow.select_model_name:
            QMessageBox.warning(self, "提示", "请先选择模型")
            return

        parameters = self.models_parameters.get(self.mainWindow.select_model_name)
        if parameters is None:
            return
        dialog = model_parameters_dialog(
            self,
            max_new_tokens=parameters[common_const.max_tokens],
            do_sample=parameters[common_const.do_sample],
            temperature=parameters[common_const.temperature],
            top_k=parameters[common_const.top_k],
            input_max_length=parameters[common_const.input_max_length],
            editable=parameters[common_const.parameters_editable]
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            parameters = dialog.get_parameters()
            self.models_parameters[self.mainWindow.tree_view_pane].update(parameters)

    def load_default_model(self):
        model_name = common_const.default_model_name
        return self.setting_model_default_parameters(model_name, common_const.default_model_path + model_name)

    def setting_model_default_parameters(self, model_name, folder_path):
        self.models_parameters[model_name] = {}

        self.models_parameters[model_name][common_const.model_name] = model_name
        self.models_parameters[model_name][common_const.model_path] = folder_path
        self.models_parameters[model_name][common_const.model_type] = model_enum.model

        self.models_parameters[model_name][common_const.max_tokens] = 500
        self.models_parameters[model_name][common_const.do_sample] = True
        self.models_parameters[model_name][common_const.temperature] = 0.9
        self.models_parameters[model_name][common_const.top_k] = 50
        self.models_parameters[model_name][common_const.input_max_length] = 2048
        self.models_parameters[model_name][common_const.parameters_editable] = True
        self.models_parameters[model_name][common_const.interface_message_dict] = []
        return self.models_parameters[model_name]
