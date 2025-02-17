# 定义一个用于重定向标准输出的类
class CustomStdout:
    def __init__(self, text_area):
        self.text_area = text_area

    def write(self, text):
        self.text_area.print(text)

    def print(self, text):
        self.text_area.print(text)
    def isatty(self):
        return False
    def flush(self):
        self.text_area.flush()


class CustomStdin:
    def __init__(self, input_line_edit):
        self.input_line_edit = input_line_edit
        self.buffer = []

    def readline(self):
        if not self.buffer and not self.input_line_edit.text().strip() == "":
            self.buffer.append(self.input_line_edit.text())
            self.input_line_edit.clear()
        return self.buffer.pop(0) + '\n' if self.buffer else ''
