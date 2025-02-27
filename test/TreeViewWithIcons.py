import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QTextEdit, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 创建一个 QTextEdit 控件
        self.text_edit = QTextEdit(self)

        # 创建一个 QLabel 控件，用于显示当前输入的文本
        self.label = QLabel("Current Text:", self)

        # 设置布局
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.text_edit)
        main_layout.addWidget(self.label)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # 设置窗口标题和大小
        self.setWindowTitle("QTextEdit with Enter Submit")
        self.setGeometry(100, 100, 400, 300)

        # 重写 keyPressEvent 方法
        self.text_edit.keyPressEvent = self.text_edit_key_press_event

    def text_edit_key_press_event(self, event):
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.submit_text()
            event.accept()  # 标记事件已处理
        else:
            # 调用父类的 keyPressEvent 方法以保持默认行为
            super(QTextEdit, self.text_edit).keyPressEvent(event)

    def submit_text(self):
        # 获取当前输入的文本
        current_text = self.text_edit.toPlainText()
        # 更新 QLabel 显示当前输入的文本
        self.label.setText(f"Current Text: {current_text}")
        # 清空 QTextEdit
        self.text_edit.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())