from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QMenu

from pyqt6 import MainWindow


class plugins_menu(QMenuBar):
    def __init__(self, menu_Bar=QMenuBar, mainWindow=MainWindow):
        super().__init__(menu_Bar)
        self.mainWindow = mainWindow
        plugins_menu = menu_Bar.addMenu('插件')

        insert_plugin = QAction("添加", self)
        plugins_menu.addAction(insert_plugin)

        load_plugin = QAction("加载插件", self)
        plugins_menu.addAction(load_plugin)

        plugins_management = QAction("插件管理", self)
        plugins_menu.addAction(plugins_management)



        # 连接动作到槽函数
        insert_plugin.triggered.connect(self.insert_plugin)
        load_plugin.triggered.connect(self.load_plugin)

        plugins_management.triggered.connect(self.plugins_management)



    @pyqtSlot()
    def insert_plugin(self):
        pass

    @pyqtSlot()
    def load_plugin(self):
        pass

    @pyqtSlot()
    def plugins_management(self):
        pass

    def clear_interface_list(self):
        self.mainWindow.clear_ui()

    def update_plugin_list(self):
        pass

    @pyqtSlot()
    def refresh_plugins(self):
        pass
