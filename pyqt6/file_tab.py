import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import QTreeView, QTabWidget, QSplitter, QApplication, QMainWindow


class FileTab(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 创建左侧面板
        left_pane = QTabWidget()
        file_tab = QSplitter(Qt.Orientation.Vertical)
        self.tree_view = QTreeView()
        file_tab.addWidget(self.tree_view)
        left_pane.addTab(file_tab, '文件栏')

        # 设置模型
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)

        # 添加一些示例数据
        root_item = self.model.invisibleRootItem()
        for i in range(5):
            item = QStandardItem(f'Item {i}')
            root_item.appendRow(item)

        # 连接 selectionChanged 信号
        self.tree_view.selectionModel().selectionChanged.connect(self.on_selection_changed)

    def on_selection_changed(self, selected, deselected):
        # 获取当前选中的索引
        indexes = self.tree_view.selectionModel().selectedIndexes()
        if indexes:
            for index in indexes:
                print(f"Selected: {index.data()}")
        else:
            print("No item selected")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Tab Example")
        self.setGeometry(100, 100, 800, 600)

        # 创建并设置 FileTab
        self.file_tab = FileTab()
        self.setCentralWidget(self.file_tab)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())