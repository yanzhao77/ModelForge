import os
import sys

from PyQt6.QtCore import Qt, QTimer, QModelIndex, pyqtSlot
from PyQt6.QtGui import QAction, QStandardItemModel, QStandardItem, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QSplitter, QTreeView, QTabWidget, QToolBar, \
    QProgressBar, QHBoxLayout, QFileDialog, QMenuBar

from common.const.common_const import common_const
from pyqt6.menu.edit_menu import edit_menu
from pyqt6.menu.help_menu import help_menu
from pyqt6.menu.interface_menu import interface_menu
from pyqt6.menu.model_menu import model_menu
from pyqt6.menu.plugins_menu import plugins_menu
from pyqt6.text_area import text_area


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(common_const.project_name)
        # 最近文件
        self.recent_models = {}
        self.select_models_path = ""
        self.models_parameters = {}
        # 设置窗口最小大小
        self.setMinimumSize(800, 500)
        self.setWindowIcon(QIcon(common_const.icon_dir))  # 你可以替换为你的应用图标
        # Main container widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        self.tree_custom_role = Qt.ItemDataRole.UserRole + 1  # 定义一个自定义的角色 从tree上获取数据

        # Main layout
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        menu_bar = QMenuBar()
        # Menu Bar
        model_bar = model_menu(menu_bar, self)
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
        left_pane.addTab(file_tab, '列表栏')
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
        self.tree_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
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
            self.load_model_for_treeview(folder_path)

            self.select_models_path = folder_path
            self.setting_model_default_parameters(folder_path)

    def setting_model_default_parameters(self, folder_path):
        self.models_parameters[folder_path] = {}
        self.models_parameters[folder_path][common_const.max_new_tokens] = 500
        self.models_parameters[folder_path][common_const.do_sample] = True
        self.models_parameters[folder_path][common_const.temperature] = 0.9
        self.models_parameters[folder_path][common_const.top_k] = 50
        self.models_parameters[folder_path][common_const.input_max_length] = 2048
        self.models_parameters[folder_path][common_const.parameters_editable] = True

    def load_model_for_treeview(self, folder_path):
        # 创建 QFileSystemModel 并设置根路径
        root_item = QStandardItem(os.path.basename(folder_path))
        root_item.setFlags(root_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 禁止编辑
        root_item.setData(folder_path, self.tree_custom_role)
        self.tree_view.model().appendRow(root_item)
        # 展开所有项
        self.tree_view.expandAll()

    def load_interface_for_treeview(self, interface_parameters_dict):
        # 创建 QFileSystemModel 并设置根路径
        root_item = QStandardItem(interface_parameters_dict[common_const.interface_name])
        root_item.setFlags(root_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 禁止编辑
        root_item.setData(interface_parameters_dict, self.tree_custom_role)
        self.tree_view.model().appendRow(root_item)
        # 展开所有项
        self.tree_view.expandAll()

    def on_double_click(self, index: QModelIndex):
        # 获取双击项的路径
        item = self.model.itemFromIndex(index)
        data = item.data(self.tree_custom_role)

        if isinstance(data, dict):  # interface
            self.loading_interface(data)
        elif isinstance(data, str):  # model
            path = data
            if not path or not os.path.isdir(path):
                return
            self.loading_model(path, self.models_parameters[path])

    def on_selection_changed(self, selected, deselected):
        # 获取当前选中的索引
        indexes = self.tree_view.selectionModel().selectedIndexes()
        if indexes:
            for index in indexes:
                folder_path = self.model.itemFromIndex(index).data(self.tree_custom_role)
                if isinstance(folder_path, str):
                    self.select_models_path = folder_path
                    if folder_path and not self.models_parameters[folder_path]:
                        self.setting_model_default_parameters(folder_path)
                # print(f"Selected: {index.data()} - Folder Path: {folder_path}")

    def loading_model(self, path, models_parameters):
        self.text_area.loading_model(path, models_parameters)
        self.models_parameters[path][common_const.parameters_editable] = False

    def loading_interface(self, models_parameters):
        self.text_area.loading_interface(models_parameters)

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
        folder_path = common_const.default_model_path
        self.load_model(folder_path)
        self.interface_bar.load_default_interface()
