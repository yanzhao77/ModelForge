import sys

from PyQt6.QtCore import QRunnable

from pytorch.model_generate import model_generate


class ui_model_lunch(QRunnable):
    def __init__(self, folder_path, text_area):
        super().__init__()
        self.folder_path = folder_path
        self.text_area = text_area

    def run(self):
        # 重定向标准输出
        sys.stdout = self
        # 在这里执行耗时的模型加载操作
        try:
            # 模型加载过程
            model = model_generate(self.folder_path)
            model.pipeline_question()
            self.text_area.model = model
        except Exception as e:
            print(f"Error loading files: {e}")

    def write(self, text):
        # sys.stdout = sys.__stdout__
        self.text_area.write(text)


class ui_model_run(QRunnable):
    def __init__(self, text, model, text_area):
        super().__init__()
        self.text = text
        self.model = model
        self.text_area = text_area

    def run(self):
        # 重定向标准输出
        sys.stdout = self
        # 在这里执行耗时的模型加载操作
        try:
            self.model.pipeline_answer(self.text)
            self.text_area.progress_bar.setVisible(False)  # 隐藏进度条
        except Exception as e:
            print(f"Error loading files: {e}")

    def write(self, text):
        # sys.stdout = sys.__stdout__
        self.text_area.write(text)


class CustomStdin:
    def __init__(self, input_line_edit):
        self.input_line_edit = input_line_edit
        self.buffer = []

    def readline(self):
        if not self.buffer and not self.input_line_edit.text().strip() == "":
            self.buffer.append(self.input_line_edit.text())
            self.input_line_edit.clear()
        return self.buffer.pop(0) + '\n' if self.buffer else ''


class CustomStdout:
    def __init__(self, display_text_area):
        self.display_text_area = display_text_area
        self.buffer = []

    def write(self, text):
        if not self.buffer:
            self.buffer.append(text)
            self.display_text_area.append(text)
            self.buffer.append('\n')
            self.display_text_area.append('\n')
    def flush(self):
        if not self.buffer:
            self.buffer.clear()