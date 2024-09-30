import sys

from PyQt6.QtCore import Qt, QThreadPool, pyqtSlot
from PyQt6.QtWidgets import QSplitter, QTextEdit, QLineEdit, QTabWidget, QVBoxLayout, QApplication, QMainWindow, QWidget

from pyqt6.ui_service import CustomStdin, CustomStdout, ui_model_run, ui_model_lunch


class text_area(QWidget):
    def __init__(self):
        super().__init__()

        # 初始化线程池
        self.thread_pool = QThreadPool()
        self.model = None
        # 创建垂直布局
        self.message = []
        layout = QVBoxLayout()
        self.setLayout(layout)
        # 上面的文本区域 (只显示文本)
        self.display_text_area = QTextEdit()
        self.display_text_area.setReadOnly(True)
        self.display_text_area.setPlainText("这是一个只显示的文本区域。")
        self.progress_bar = None
        # 下面的单行输入区域(允许输入)
        self.input_line_edit = QLineEdit()
        self.input_line_edit.setPlaceholderText("请输入...")
        # 创建垂直分割器
        right_pane = QSplitter(Qt.Orientation.Vertical)
        right_pane.addWidget(self.display_text_area)
        right_pane.addWidget(self.input_line_edit)
        right_pane.setSizes([350, 50])  # 设置右侧上下文本区域的初始大小
        # 将分割器添加到布局中
        layout.addWidget(right_pane)
        self.input_line_edit.returnPressed.connect(self.submit)
        # 重定向标准输入
        sys.stdin = CustomStdin(self.input_line_edit)
        sys.stdout = CustomStdout(self.display_text_area)

    @pyqtSlot()
    def print_loading(self, folder_path):
        self.display_text_area.clear()
        model_run = ui_model_lunch(folder_path, self)
        self.thread_pool.start(model_run)

    @pyqtSlot()
    def write(self, text):
        if text.strip() == "":
            return
        self.display_text_area.append(text)

    def input(self, text):
        self.input_line_edit.setText(text)

    def get_input_text(self):
        return self.input_line_edit.text()

    def clear_input(self):
        self.input_line_edit.clear()

    @pyqtSlot()
    def submit(self):
        if self.input_line_edit.text().strip() == "":
            return
            # 显示进度条并初始化进度
        self.progress_bar.setVisible(True)
        self.message.append(self.get_input_text())
        self.write("你: " + self.get_input_text())
        model_lunch = ui_model_run(self.get_input_text(), self.model, self)
        self.thread_pool.start(model_lunch)
        self.clear_input()

    def stop_model(self):
        pass


if __name__ == '__main__':
    app = QApplication(sys.argv)
    text_area = text_area()
    window = QMainWindow()
    window.setMinimumSize(800, 500)

    window.setCentralWidget(text_area)
    window.show()
    sys.exit(app.exec())
