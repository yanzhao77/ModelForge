import sys

import markdown
from PyQt6.QtCore import Qt, QThreadPool, pyqtSlot
from PyQt6.QtGui import QTextCursor, QFont, QTextCharFormat, QColor
from PyQt6.QtWidgets import QSplitter, QTextEdit, QLineEdit, QVBoxLayout, QApplication, QMainWindow, \
    QWidget

from common.baseCustom.ui_service import CustomStdin, CustomStdout, ui_model_run, ui_model_lunch


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
        # 设置字体
        # font = QFont("SimSun", 12)  # 设置字体类型  设置字体大小
        self.font = QFont("Microsoft YaHei", 10)
        self.input_line_edit.setFont(self.font)
        self.input_line_edit.setMaximumHeight(32)

        self.display_text_area.setFont(self.font)
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
    def loading(self, folder_path, models_parameters):
        self.display_text_area.clear()
        model_run = ui_model_lunch(folder_path,models_parameters, self)
        self.thread_pool.start(model_run)

    @pyqtSlot()
    def print(self, text):
        if text.strip() == "":
            return
        self.display_text_area.append("")
        html_content = markdown.markdown(text)
        self.display_text_area.moveCursor(QTextCursor.MoveOperation.End)
        self.display_text_area.insertHtml(html_content)
        # self.display_text_area.append(text)

    @pyqtSlot()
    def append_you(self, text):
        """追加带有 '你: ' 样式的文本"""
        self._append_styled_text("user:  ", 11, True, Qt.GlobalColor.blue, text)

    @pyqtSlot()
    def append_model(self, text):
        """追加带有 '模型: ' 样式的文本"""
        self._append_styled_text("model:  ", 11, True, Qt.GlobalColor.blue, text)

    def _append_styled_text(self, prefix, size, bold, color, text):
        self.display_text_area.append("")
        """内部方法，用于追加带有样式的文本"""
        cursor = self.display_text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)

        # 应用前缀样式
        format_prefix = QTextCharFormat()
        format_prefix.setFontPointSize(size)
        if bold:
            format_prefix.setFontWeight(QFont.Weight.Bold)
        else:
            format_prefix.setFontWeight(QFont.Weight.Normal)
        format_prefix.setForeground(QColor(color))
        cursor.insertText(prefix, format_prefix)
        # 应用普通文本样式
        format_text = QTextCharFormat()
        format_text.setFontPointSize(self.font.pointSize())
        format_text.setFontWeight(QFont.Weight.Normal)
        format_text.setForeground(QColor(Qt.GlobalColor.black))
        cursor.insertText(text, format_text)

    def input(self, text):
        self.input_line_edit.setText(text)

    def get_input_text(self):
        return self.input_line_edit.text()

    def clear_input(self):
        self.input_line_edit.clear()

    def clear(self):
        self.input_line_edit.clear()
        self.display_text_area.clear()

    @pyqtSlot()
    def submit(self):
        if self.input_line_edit.text().strip() == "":
            return
            # 显示进度条并初始化进度
        self.progress_bar.setVisible(True)
        self.message.append(self.get_input_text())
        # self.print("你: " + self.get_input_text())
        self.append_you(self.get_input_text())
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
