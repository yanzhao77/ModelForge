from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QMenu

from pyqt6 import MainWindow


class file_menu(QMenuBar):
    def __init__(self, menu_Bar=QMenuBar, mainWindow=MainWindow):
        super().__init__(menu_Bar)
        self.mainWindow = mainWindow
        file_menu = menu_Bar.addMenu('文件')

        create_file = QAction("新建", self)
        file_menu.addAction(create_file)

        open_file = QAction("打开模型", self)
        file_menu.addAction(open_file)
        self.recent_models_menu = QMenu("最近模型", self)
        file_menu.addMenu(self.recent_models_menu)
        file_menu.addSeparator()
        file_menu.addAction('刷新')
        file_menu.addSeparator()
        # script_menu = QMenu('自动化脚本', self)
        # script_menu.addAction(QAction('脚本执行', self))
        # script_menu.addAction(QAction('录制脚本', self))
        # file_menu.addMenu(script_menu)

        file_menu.addSeparator()
        clear_file = QAction("清空", self)
        file_menu.addAction(clear_file)

        file_menu.addSeparator()
        restart_file = QAction("重启", self)
        file_menu.addAction(restart_file)

        file_menu.addSeparator()
        exit_file = QAction("退出", self)
        file_menu.addAction(exit_file)

        # 连接动作到槽函数
        create_file.triggered.connect(self.create_file)
        exit_file.triggered.connect(self.exit_file)
        restart_file.triggered.connect(self.restart_file)
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
