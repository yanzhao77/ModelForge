import os

from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QIcon
from PyQt6.QtWidgets import QTabWidget, QSplitter, QTreeView

from common.const.common_const import common_const, model_enum


class tree_view_pane(QTabWidget):
    def __init__(self, main_splitter, main_ui):
        super().__init__()
        file_tab = QSplitter(Qt.Orientation.Vertical)
        self.tree_view = QTreeView()
        file_tab.addWidget(self.tree_view)
        self.addTab(file_tab, '列表栏')
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)
        main_splitter.addWidget(self)
        self.mainWindow = main_ui
        self.models_parameters = self.mainWindow.models_parameters
        # 定义一个自定义的角色 从tree上获取数据
        self.tree_custom_role = Qt.ItemDataRole.UserRole + 1

        # 连接双击事件
        self.tree_view.doubleClicked.connect(self.on_double_click)
        self.tree_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
        # 连接键盘事件
        self.tree_view.keyPressEvent = self.keyPressEvent

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected_item()

    def delete_selected_item(self):
        # 获取当前选中的索引
        indexes = self.tree_view.selectedIndexes()
        if indexes:
            index = indexes[0]
            parent = index.parent()
            if parent.isValid():
                # 删除子节点
                parent_item = self.model.itemFromIndex(parent)
                parent_item.removeRow(index.row())
            else:
                # 删除根节点
                self.model.removeRow(index.row())
    def set_main_data(self):
        self.model_bar = self.mainWindow.model_bar
        self.progress_bar = self.mainWindow.progress_bar
        self.text_area = self.mainWindow.text_area
        self.interface_bar = self.mainWindow.interface_bar

    def on_double_click(self, index: QModelIndex):
        # 获取双击项的路径
        item = self.model.itemFromIndex(index)
        data = item.data(self.tree_custom_role)
        self.select_item(data)
        if (self.text_area.get_model(data[common_const.model_name])
                and data[common_const.model_name] == self.text_area.model.model_name):
            return
        elif not self.text_area.get_model(data[common_const.model_name]):
            self.loading_model(data)
        else:
            self.text_area.select_model(self.mainWindow.select_model_name)

    def on_selection_changed(self, selected, deselected):
        # 获取当前选中的索引
        indexes = self.tree_view.selectionModel().selectedIndexes()
        if indexes:
            for index in indexes:
                model_dict = self.model.itemFromIndex(index).data(self.tree_custom_role)

                self.select_item(model_dict)
                if model_dict[common_const.model_type] == model_enum.model:
                    self.mainWindow.select_model_name = model_dict[common_const.model_name]
                    if not self.models_parameters[self.mainWindow.select_model_name]:
                        self.model_bar.setting_model_default_parameters(model_dict[common_const.model_path])

    def select_item(self, model_dict):
        self.mainWindow.select_model_name = model_dict[common_const.model_name]

    def load_for_treeview(self, parameters_dict):
        # 创建 QFileSystemModel 并设置根路径
        root_item = QStandardItem(parameters_dict[common_const.model_name])
        root_item.setFlags(root_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 禁止编辑
        root_item.setData(parameters_dict, self.tree_custom_role)
        if parameters_dict[common_const.model_type] == model_enum.interface:
            root_item.setIcon(QIcon(common_const.icon_clouds_view))  # 设置根节点的图标
        elif parameters_dict[common_const.model_type] == model_enum.model:
            root_item.setIcon(QIcon(common_const.icon_model_view))  # 设置根节点的图标

        self.model.appendRow(root_item)
        # 展开所有项
        self.tree_view.expandAll()

    def loading_model(self, models_parameters):
        self.mainWindow.select_model_name = models_parameters[common_const.model_name]
        if models_parameters[common_const.model_type] == model_enum.model:
            self.text_area.loading_model(models_parameters)
        elif models_parameters[common_const.model_type] == model_enum.interface:
            self.text_area.loading_interface(models_parameters)
        self.models_parameters[self.mainWindow.select_model_name][common_const.parameters_editable] = False

    def loading_interface(self, models_parameters):
        self.text_area.loading_interface(models_parameters)

    def tree_clear(self):
        self.model.clear()

    def load_default_model_for_treeview(self):
        # interface_dict = self.interface_bar.load_default_interface()
        # self.load_for_treeview(interface_dict)
        model = self.model_bar.load_default_model()
        self.load_for_treeview(model)

    def load_model(self, model_name, folder_path):
        if folder_path:
            # 获取文件夹的名字
            self.mainWindow.select_model_name = model_name
            self.text_area.print(f"Selected folder: {self.mainWindow.select_model_name}")
            self.mainWindow.recent_models[self.mainWindow.select_model_name] = folder_path
            # self.load_for_treeview(self.mainWindow.models_parameters[self.mainWindow.select_model_name])
            # 显示进度条并初始化进度
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            # 启动定时器来模拟文件夹加载进度
            timer = QTimer()
            timer.timeout.connect(lambda: self.update_load_progress(timer))
            timer.start(10)  # 每100毫秒更新一次

    def update_load_progress(self, timer):
        value = self.progress_bar.value()
        if value < 10:
            self.progress_bar.setValue(value + 1)
        else:
            timer.stop()
            self.progress_bar.setVisible(False)  # 隐藏进度条
            # 文件夹加载完成后的处理
            self.load_for_treeview(self.models_parameters[self.mainWindow.select_model_name])
