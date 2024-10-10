from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QMenu

from pyqt6 import MainWindow


class interface_menu(QMenuBar):
    def __init__(self, menu_Bar=QMenuBar, mainWindow=MainWindow):
        super().__init__(menu_Bar)
        self.mainWindow = mainWindow
        interface_menu = menu_Bar.addMenu('接口')

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

        self.interface_list_menu.aboutToShow.connect(self.recent_interface_list_menu)

    @pyqtSlot()
    def create_interface(self):
        pass

    @pyqtSlot()
    def open_interface(self):
        pass

    @pyqtSlot()
    def interface_management(self):
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
