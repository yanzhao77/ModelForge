from PyQt6.QtCore import pyqtSlot, Qt
from PyQt6.QtGui import QAction, QStandardItemModel
from PyQt6.QtWidgets import QMenuBar, QTreeView, QTabWidget, QSplitter


class file_tab(QTabWidget):
    def __init__(self,qtab=QTabWidget):
        super().__init__(qtab)
        left_pane = QTabWidget()
        file_tab = QSplitter(Qt.Orientation.Vertical)
        self.tree_view = QTreeView()
        file_tab.addWidget(self.tree_view)
        left_pane.addTab(file_tab, '文件栏')
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)


    @pyqtSlot()
    def create_file(self):
        pass