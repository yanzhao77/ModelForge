from PySide6.QtWidgets import QApplication, QMainWindow, QTextEdit, \
    QTextBrowser, QVBoxLayout, QMenuBar, QMenu, QHBoxLayout, QWidget, QFileDialog
from PySide6.QtGui import QIcon, QAction


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        self.main_window = QMainWindow()
        self.main_window.resize(1000, 600)
        self.main_window.setWindowTitle("markdown编辑器")
        # self.action = QAction(MainWindow)
        # self.action.setObjectName(u"action")

        self.file_path = ""

        self.menu_bar = QMenuBar(self.main_window)

        self.menu = QMenu(self.menu_bar)
        self.menu_bar.addMenu(self.menu)
        self.menu.setTitle("功能列表")

        self.open_file = QAction(QIcon(), "打开文件", self.menu_bar)
        self.open_file.triggered.connect(self.open_file_func)
        self.menu.addAction(self.open_file)

        self.save_file = QAction(QIcon(), "保存文件", self.menu_bar)
        self.menu.addAction(self.save_file)
        self.save_file.triggered.connect(self.file_saved_func)

        self.save_as_file = QAction(QIcon(), "另存文件", self.menu_bar)
        self.menu.addAction(self.save_as_file)

        self.huitui = QAction(QIcon('img/houtui.jpg'), "&回退", self.menu_bar)
        self.huitui.setObjectName("回退")
        self.huitui.setShortcut("Ctrl+h")
        self.huitui.setStatusTip("操作文档回退")

        self.menu_bar.addAction(self.huitui)

        self.qianjin = QAction(QIcon('img/qianjin.jpg'), "&前进", self.menu_bar)
        self.qianjin.setObjectName("qianjin")
        self.qianjin.setShortcut("Ctrl+q")
        self.qianjin.setStatusTip("操作文档前进")

        self.menu_bar.addAction(self.qianjin)

        self.about = QAction(QIcon(''), "&关于", self.menu_bar)
        self.about.setObjectName("关于")
        self.about.setStatusTip("关于")
        self.menu_bar.addAction(self.about)

        self.layout = QHBoxLayout(self.main_window)
        self.layout.setMenuBar(self.menu_bar)

        self.content_layout = QHBoxLayout()
        self.markdown_context = QTextEdit(self.main_window)
        self.markdown_browser = QTextBrowser(self.main_window)
        self.content_layout.addWidget(self.markdown_context)
        self.content_layout.addWidget(self.markdown_browser)

        self.huitui.triggered.connect(self.markdown_context.redo)
        self.qianjin.triggered.connect(self.markdown_context.undo)
        self.markdown_context.textChanged.connect(self.file_changed_func)

        self.layout.addLayout(self.content_layout)

        # self.main_window.setLayout(self.layout)
        # self.main_window.setCentralWidget(self.layout)

        widget = QWidget()
        widget.setLayout(self.layout)
        self.main_window.setCentralWidget(widget)

        # self.main_window.setLayout(self.layout)

    def open_file_func(self):
        self.file_path, _ = QFileDialog.getOpenFileName(self.main_window, "选择要编辑的md文件", "", "图片类型 (*.md)")
        with open(self.file_path, "r") as f:
            content = f.read()
            self.markdown_context.setText(content)
            self.markdown_browser.setMarkdown(content)

    def file_changed_func(self):
        self.markdown_browser.setMarkdown(self.markdown_context.toPlainText())

    def file_saved_func(self):
        new_file_path, _ = QFileDialog.getSaveFileName(self.main_window, "保存md文件")
        print(new_file_path)
        with open(new_file_path, "w") as f:
            f.write(self.markdown_context.toPlainText())

    def houtui_func(self):
        pass


if __name__ == "__main__":
    app = QApplication()
    win = MainWindow()
    win.main_window.show()
    app.exec()
