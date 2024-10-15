import sys

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QLabel
from PyQt6.QtGui import QFont

class MyWindow(QWidget):
    def __init__(self):
        super().__init__()

        # 设置窗口标题
        self.setWindowTitle("QLineEdit Font Example")

        # 创建一个垂直布局
        layout = QVBoxLayout()

        # 创建多个QLineEdit并设置不同的字体
        line_edit1 = QLineEdit(self)
        line_edit1.setPlaceholderText("Arial 14")
        font1 = QFont("Arial", 14)
        line_edit1.setFont(font1)
        layout.addWidget(line_edit1)

        line_edit2 = QLineEdit(self)
        line_edit2.setPlaceholderText("Courier New 12")
        font2 = QFont("Courier New", 12)
        line_edit2.setFont(font2)
        layout.addWidget(line_edit2)

        line_edit3 = QLineEdit(self)
        line_edit3.setPlaceholderText("Times New Roman 16")
        font3 = QFont("Times New Roman", 16)
        line_edit3.setFont(font3)
        layout.addWidget(line_edit3)

        line_edit4 = QLineEdit(self)
        line_edit4.setPlaceholderText("微软雅黑 18")
        font4 = QFont("Microsoft YaHei", 18)
        line_edit4.setFont(font4)
        layout.addWidget(line_edit4)

        line_edit5 = QLineEdit(self)
        line_edit5.setPlaceholderText("宋体 20")
        font5 = QFont("SimSun", 20)
        line_edit5.setFont(font5)
        layout.addWidget(line_edit5)

        # 添加标签以显示说明
        label = QLabel("每个QLineEdit都设置了不同的字体和大小")
        layout.addWidget(label)

        # 设置窗口的布局
        self.setLayout(layout)

if __name__ == "__main__":
    app = QApplication([])

    window = MyWindow()
    window.show()

    sys.exit(app.exec())