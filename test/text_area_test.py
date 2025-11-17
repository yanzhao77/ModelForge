import sys

import markdown
from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QSplitter, QLineEdit, QVBoxLayout, QApplication, QMainWindow, QWidget, QTextBrowser

from common.baseCustom.Custom import CustomStdin, CustomStdout

class text_area(QWidget):
    def __init__(self):
        super().__init__()

        # 初始化线程池及其他变量
        self.thread_pool = QThreadPool()
        self.model = None
        self.message = []
        # 用于累计所有 Markdown 文本的变量
        self.all_markdown = "这是一个只显示的文本区域。"

        layout = QVBoxLayout()
        self.setLayout(layout)

        # 创建只显示文本的 QTextBrowser，并设置初始 Markdown 内容
        self.display_text_area = QTextBrowser()
        self.display_text_area.setMarkdown(self.all_markdown)
        self.progress_bar = None

        # 创建单行输入区域（允许输入）
        self.input_line_edit = QLineEdit()
        self.input_line_edit.setPlaceholderText("请输入...")
        self.font = QFont("Microsoft YaHei", 10)
        self.input_line_edit.setFont(self.font)
        self.input_line_edit.setMaximumHeight(32)
        self.display_text_area.setFont(self.font)

        # 创建垂直分割器，将 QTextBrowser 和 QLineEdit 分开放置
        right_pane = QSplitter(Qt.Orientation.Vertical)
        right_pane.addWidget(self.display_text_area)
        right_pane.addWidget(self.input_line_edit)
        right_pane.setSizes([350, 50])
        layout.addWidget(right_pane)

        # 当回车时调用 submit 方法
        self.input_line_edit.returnPressed.connect(self.submit)

        # 重定向标准输入输出（如果有需要）
        sys.stdin = CustomStdin(self.input_line_edit)
        sys.stdout = CustomStdout(self.display_text_area)

    @Slot()
    def append_you(self, text):
        """追加用户输入的文本，使用 Markdown 格式（加粗显示 'user:'）"""
        self.all_markdown += f"\n\n**user:** {text}"
        self.display_text_area.setMarkdown(self.all_markdown)

    # @Slot()
    # def append_model(self, text):
    #     """追加模型输出的文本"""
    #     self.all_markdown += f"\n\n**model:** {text}"
    #     self.append_markdown(self.all_markdown)

    def append_markdown(self, text):
        # 先将 Markdown 转换为 HTML
        html = markdown.markdown(text)
        # 追加 HTML 到 QTextBrowser 中
        self.all_markdown += "\n" + html
        self.display_text_area.setHtml(self.all_markdown)

    def input(self, text):
        self.input_line_edit.setText(text)

    def get_input_text(self):
        return self.input_line_edit.text()

    def clear_input(self):
        self.input_line_edit.clear()

    def clear(self):
        self.input_line_edit.clear()
        self.display_text_area.clear()
        self.all_markdown = ""

    @Slot()
    def submit(self):
        input_text = self.get_input_text()
        if input_text.strip() == "":
            return
        self.message.append(input_text)
        self.append_you(input_text)
        self.input_line_edit.clear()

    def stop_model(self):
        pass

if __name__ == '__main__':
    app = QApplication(sys.argv)
    widget = text_area()
    window = QMainWindow()
    window.setMinimumSize(800, 500)
    window.setCentralWidget(widget)
    window.show()
    sys.exit(app.exec())
