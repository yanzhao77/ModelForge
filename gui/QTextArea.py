from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTextEdit


class QTextArea(QTextEdit):
    submitTextSignal = Signal(str)

    def __init__(self, *args, **kwargs):
        super(QTextArea, self).__init__(*args, **kwargs)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.submit_text()
            event.accept()  # 标记事件已处理
        else:
            super().keyPressEvent(event)  # 调用父类的 keyPressEvent 方法以保持默认行为

    def submit_text(self):
        # 发送信号
        self.submitTextSignal.emit(self.toPlainText())
