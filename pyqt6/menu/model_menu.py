from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QMenu, QDialog

from common.const.common_const import common_const
from pyqt6 import MainWindow
from pyqt6.dialog.model_parameters_dialog import model_parameters_dialog


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
        open_file.triggered.connect(self.open_file)
        self.recent_models_menu.aboutToShow.connect(self.recent_model_list)

    @pyqtSlot()
    def create_file(self):
        self.mainWindow.tree_clear()
        self.mainWindow.load_default_model()

    @pyqtSlot()
    def open_file(self):
        folder_path = self.mainWindow.open_dir_dialog()
        if folder_path:
            self.clear_file()
            self.mainWindow.load_model(folder_path)

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
            recent_file_action.triggered.connect(lambda checked, f=file: self.mainWindow.load_model(f))
            self.recent_models_menu.addAction(recent_file_action)

    def model_parameters_setting(self):
        parameters = self.models_parameters[self.mainWindow.select_models_path]
        dialog = model_parameters_dialog(
            self,
            max_new_tokens=parameters[common_const.max_new_tokens],
            do_sample=parameters[common_const.do_sample],
            temperature=parameters[common_const.temperature],
            top_k=parameters[common_const.top_k],
            input_max_length=parameters[common_const.input_max_length],
            editable=parameters[common_const.parameters_editable]
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            parameters = dialog.get_parameters()
            self.models_parameters[self.mainWindow.select_models_path].update(parameters)
