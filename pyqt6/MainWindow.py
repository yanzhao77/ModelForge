import os
import sys

from PyQt6.QtCore import Qt, QTimer, QModelIndex, pyqtSlot
from PyQt6.QtGui import QAction, QStandardItemModel, QStandardItem, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QSplitter, QTreeView, QTabWidget, QToolBar, \
    QProgressBar, QHBoxLayout, QFileDialog, QMenuBar

from common.const.common_const import common_const
from pyqt6.file_tab import file_tab
from pyqt6.menu.edit_menu import edit_menu
from pyqt6.menu.file_menu import file_menu
from pyqt6.menu.help_menu import help_menu
from pyqt6.menu.interface_menu import interface_menu
from pyqt6.menu.plugins_menu import plugins_menu
from pyqt6.text_area import text_area


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(common_const.project_name.value)
        # 最近文件
        self.recent_models = {}
        # 设置窗口最小大小
        self.setMinimumSize(800, 500)
        self.setWindowIcon(QIcon(common_const.icon_dir.value))  # 你可以替换为你的应用图标
        # Main container widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # Main layout
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        menu_bar = QMenuBar()
        # Menu Bar
        file_bar = file_menu(menu_bar, self)
        interface_bar = interface_menu(menu_bar, self)
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
        # load_training.triggered.connect(self.start_task)
        stop_Model.triggered.connect(self.stop_model)

        # Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter)

        # Left pane
        left_pane = QTabWidget()
        file_tab = QSplitter(Qt.Orientation.Vertical)
        self.tree_view = QTreeView()
        file_tab.addWidget(self.tree_view)
        left_pane.addTab(file_tab, '文件栏')
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)

        main_splitter.addWidget(left_pane)

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
        self.progress_bar.setVisible(False)  # 初始隐藏进度条
        self.progress_bar.setTextVisible(False)
        progress_layout.addStretch()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch()

        # 连接双击事件
        self.tree_view.doubleClicked.connect(self.on_double_click)
        self.text_area.progress_bar = self.progress_bar

        # 加载默认模型
        self.load_default_model()

    def load_model_ui(self):
        folder_path = self.open_dir_dialog()
        self.load_model(folder_path)

    def open_dir_dialog(self):
        # 打开文件夹对话框选择文件夹
        folder_dialog = QFileDialog()
        return folder_dialog.getExistingDirectory(self, "Open Directory", "", QFileDialog.Option.ShowDirsOnly)

    def load_model(self, folder_path):
        if folder_path:
            # 获取文件夹的名字
            folder_name = os.path.basename(folder_path)
            self.print(f"Selected folder: {folder_name}")
            self.recent_models[folder_name] = folder_path

            # 显示进度条并初始化进度
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            # 启动定时器来模拟文件夹加载进度
            self.timer = QTimer()
            self.timer.timeout.connect(lambda: self.update_load_progress(folder_path))
            self.timer.start(10)  # 每100毫秒更新一次

    def update_load_progress(self, folder_path):
        value = self.progress_bar.value()
        if value < 10:
            self.progress_bar.setValue(value + 1)
        else:
            self.timer.stop()
            self.progress_bar.setVisible(False)  # 隐藏进度条
            # 文件夹加载完成后的处理
            self.load_folder_contents(folder_path)

    def load_folder_contents(self, folder_path):
        # 创建 QFileSystemModel 并设置根路径
        root_item = QStandardItem(os.path.basename(folder_path))
        root_item.setFlags(root_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 禁止编辑
        root_item.setAccessibleText(folder_path)
        self.tree_view.model().appendRow(root_item)
        # 展开所有项
        self.tree_view.expandAll()

    def on_double_click(self, index: QModelIndex):
        # 获取双击项的路径
        item = self.model.itemFromIndex(index)
        path = item.accessibleText()
        if not path or not os.path.isdir(path):
            return

        # 启动定时器来模拟文件夹内容打印进度
        self.print_loading(path)

    def print_loading(self, path):
        self.text_area.print_loading(path)

    @pyqtSlot()
    def write(self, text):
        # sys.stdout = sys.__stdout__
        self.text_area.print(text)

    @pyqtSlot()
    def print(self, text):
        # sys.stdout = sys.__stdout__
        self.write(text)

    @pyqtSlot()
    def input(self, text):
        self.text_area.input(text)

    def stop_model(self):
        self.text_area.stop_model()

    @pyqtSlot()
    def tree_clear(self):
        self.model.clear()

    def clear_ui(self):
        self.tree_clear()
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.timer.stop()
        self.text_area.clear()

    def exit_ui(self):
        QApplication.instance().quit()

    def restart(self):
        # 重新启动应用程序
        os.execl(sys.executable, sys.executable, *sys.argv)

    def load_default_model(self):
        folder_path = common_const.default_model_path.value
        self.load_model(folder_path)
