import os
import sys

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QSplitter, QToolBar, \
    QProgressBar, QHBoxLayout, QMenuBar

from common.const.common_const import common_const
from qt6.menu.edit_menu import edit_menu
from qt6.menu.help_menu import help_menu
from qt6.menu.interface_menu import interface_menu
from qt6.menu.model_menu import model_menu
from qt6.menu.plugins_menu import plugins_menu
from qt6.text_area import text_area
from qt6.tree_view.tree_view_pane import tree_view_pane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(common_const.project_name)
        # 最近文件
        self.recent_models = {}
        self.select_model_name = ""
        self.models_parameters = {}
        # 设置窗口最小大小
        self.setMinimumSize(800, 500)
        self.setWindowIcon(QIcon(common_const.icon_main_view))  # 你可以替换为你的应用图标
        # Main container widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # Main layout
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        menu_bar = QMenuBar()
        # Menu Bar
        self.model_bar = model_menu(menu_bar, self)
        self.interface_bar = interface_menu(menu_bar, self)
        plugin_bar = plugins_menu(menu_bar, self)
        edit_bar = edit_menu(menu_bar)
        help_bar = help_menu(menu_bar)
        self.setMenuBar(menu_bar)

        # Toolbar
        model_tool_bar = QToolBar()
        load_model = QAction('Load Model', self)
        model_tool_bar.addAction(load_model)
        load_training = QAction('Training Model', self)
        model_tool_bar.addAction(load_training)
        stop_Model = QAction('stop Model', self)
        model_tool_bar.addAction(stop_Model)
        # self.addToolBar(model_tool_bar)

        # 连接动作到槽函数
        load_model.triggered.connect(self.load_model_ui)
        stop_Model.triggered.connect(self.stop_model)

        # Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter)

        # Left pane
        self.tree_view = tree_view_pane(main_splitter, self)

        # Right pane
        self.text_area = text_area()
        main_splitter.addWidget(self.text_area)

        # 设置main_splitter的默认比例
        main_splitter.setSizes([150, 750])

        # 添加进度条到水平布局
        progress_layout = QHBoxLayout()
        main_layout.addLayout(progress_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)  # 设置进度条的高度
        self.progress_bar.hide()  # 初始隐藏进度条
        progress_layout.addStretch()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch()

        self.text_area.progress_bar = self.progress_bar
        self.tree_view.set_main_data()
        # 加载默认模型
        self.tree_view.load_default_model_for_treeview()

    def load_model_ui(self):
        self.model_bar.open_model()

    @pyqtSlot()
    def print(self, text):
        # sys.stdout = sys.__stdout__
        self.text_area.print(text)

    @pyqtSlot()
    def input(self, text):
        self.text_area.input(text)

    def stop_model(self):
        self.text_area.stop_model()

    @pyqtSlot()
    def tree_clear(self):
        self.tree_view.tree_clear()

    def clear_ui(self):
        self.tree_clear()
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.text_area.clear()

    def exit_ui(self):
        QApplication.instance().quit()

    def restart(self):
        # 重新启动应用程序
        os.execl(sys.executable, sys.executable, *sys.argv)
