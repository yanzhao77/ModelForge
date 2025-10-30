import copy
import sys

import markdown
from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtGui import QTextCursor, QFont, QTextCharFormat, QColor
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget, QTextBrowser

from common.baseCustom.Custom import CustomStdin, CustomStdout
from common.baseCustom.ui_service import ui_model_run, ui_model_lunch
from gui.QTextArea import QTextArea
from gui.tree_view.radio_layout import RadioLayout


class text_area(QWidget):
    def __init__(self):
        super().__init__()

        # 初始化线程池
        self.thread_pool = QThreadPool()
        self.model = None
        self.model_dict = {}
        # 创建垂直布局
        self.message = {}
        layout = QVBoxLayout()
        self.setLayout(layout)
        # 上面的文本区域 (只显示文本)
        self.display_text_area = QTextBrowser()
        # self.display_text_area.setReadOnly(True)
        self.progress_bar = None
        # 下面的单行输入区域(允许输入)
        self.input_line_edit = QTextArea()
        self.input_line_edit.setPlaceholderText("请输入...")
        # 设置字体
        # font = QFont("SimSun", 12)  # 设置字体类型  设置字体大小
        self.font = QFont("Microsoft YaHei", 10)
        self.input_line_edit.setFont(self.font)
        self.input_line_edit.setMinimumHeight(20)

        self.display_text_area.setFont(self.font)
        # 创建垂直分割器
        right_pane = QSplitter(Qt.Orientation.Vertical)
        right_pane.addWidget(self.display_text_area)
        right_pane.addWidget(self.input_line_edit)
        right_pane.setSizes([350, 50])  # 设置右侧上下文本区域的初始大小

        self.radio_layout = RadioLayout(self)  # 创建一个新的水平布局用于单选按钮

        # 将分割器添加到布局中
        layout.addWidget(right_pane)
        layout.addWidget(self.radio_layout)  # 将底部布局添加到主布局中，使其位于最底部
        self.input_line_edit.submitTextSignal.connect(self.submit)
        # 重定向标准输入
        sys.stdout = CustomStdout(self)
        sys.stdin = CustomStdin(self.input_line_edit)
        # sys.stderr = CustomStdout(self)

    def set_model_name(self, model_name):
        self.model.model_name = model_name
        self.model_dict[model_name] = self.model

    def select_model(self, model_name):
        if self.model_dict and model_name in self.model_dict:
            self.model = self.model_dict[model_name]
        self.toggle_that_model_massage()

    def get_model(self, model_name):
        if self.model_dict and model_name in self.model_dict:
            return self.model_dict[model_name]

    @Slot()
    def loading_model(self, models_parameters):
        self.radio_layout.setVisible(True)
        self.clear_output()
        model_run = ui_model_lunch(models_parameters, self)
        self.thread_pool.start(model_run)

    @Slot()
    def loading_interface(self, models_parameters):
        self.radio_layout.hide()
        self.clear_output()
        model_run = ui_model_lunch(models_parameters, self)
        self.thread_pool.start(model_run)

    @Slot()
    def print(self, text):
        if text.strip() == "":
            return
        self.display_text_area.append("")
        self.display_text_area.append(text)
        self.display_text_area.setMarkdown(text)

    @Slot()
    def append_you(self, text):
        """追加带有 '你: ' 样式的文本"""
        self._append_styled_text("user:  ", 11, True, Qt.GlobalColor.blue, text)

    @Slot()
    def append_model(self, model_name: str = "model", text: str = ""):
        """追加带有 '模型: ' 样式的文本"""
        self._append_styled_text(f"{model_name}:  ", 11, True, Qt.GlobalColor.blue, text)

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
        if self.model not in self.message:
            self.message[self.model] = []
        self.message[self.model].append(prefix + text)

    def toggle_that_model_massage(self):
        self.clear_output()
        if self.model in self.message:
            message_list = copy.deepcopy(self.message[self.model])
            del self.message[self.model]
            for text in message_list:
                parts = text.split(":", 1)  # 分割一次，最多分成两部分
                if 'user' in parts[0].strip():
                    self.append_you(parts[1])
                else:
                    self.append_model(parts[0], parts[1])

    def input(self, text):
        self.input_line_edit.setText(text)

    def get_input_text(self):
        return self.input_line_edit.toPlainText()

    def clear_input(self):
        self.input_line_edit.clear()

    def clear_output(self):
        self.display_text_area.clear()

    def clear(self):
        self.clear_input()
        self.clear_output()

    def check_models_parameters(self, models_parameters):
        self.radio_layout.check_models_parameters(models_parameters)

    @Slot()
    def submit(self):
        if self.input_line_edit.toPlainText().strip() == "":
            return
            # 显示进度条并初始化进度
        self.progress_bar.setVisible(True)
        self.append_you(self.get_input_text())
        model_lunch = ui_model_run(self.get_input_text(), self.model, self)
        self.thread_pool.start(model_lunch)
        self.clear_input()

    def stop_model(self):
        pass
