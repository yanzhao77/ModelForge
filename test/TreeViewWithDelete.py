import sys
from PyQt6.QtWidgets import QApplication, QTreeView, QVBoxLayout, QWidget
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem
from PyQt6.QtCore import Qt

class TreeViewWithDelete(QWidget):
    def __init__(self):
        super().__init__()

        # 创建一个 QTreeView 控件
        self.tree_view = QTreeView(self)

        # 创建一个 QStandardItemModel 模型
        self.model = QStandardItemModel()

        # 设置模型
        self.tree_view.setModel(self.model)

        # 添加根节点
        root_node = QStandardItem("Root Node")
        root_node.setIcon(QIcon("path/to/icon1.png"))  # 设置根节点的图标
        self.model.appendRow(root_node)

        # 添加子节点
        child1 = QStandardItem("Child 1")
        child1.setIcon(QIcon("path/to/icon2.png"))  # 设置子节点的图标
        root_node.appendRow(child1)

        child2 = QStandardItem("Child 2")
        child2.setIcon(QIcon("path/to/icon3.png"))  # 设置子节点的图标
        root_node.appendRow(child2)

        # 设置布局
        layout = QVBoxLayout()
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

        # 设置窗口标题和大小
        self.setWindowTitle("QTreeView with Delete Function")

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TreeViewWithDelete()
    window.show()
    sys.exit(app.exec())