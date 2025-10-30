import sys
import random
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextBrowser, QMenu,
                               QVBoxLayout, QWidget, QPushButton)
from PySide6.QtGui import QTextCursor, QColor, QAction, QFont, QTextCharFormat
from PySide6.QtCore import Qt, QTimer, QSize


class EnhancedTextBrowser(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.setup_context_menu()
        self.setup_dynamic_update()

    def init_ui(self):
        # 基础样式配置
        self.setStyleSheet("""
            QTextBrowser {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 2px solid #3A3A3A;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Segoe UI', Arial;
            }
        """)

    def setup_context_menu(self):
        # 创建右键菜单动作
        self.copy_action = QAction("复制", self)
        self.copy_action.triggered.connect(self.copy)
        self.clear_action = QAction("清空内容", self)
        self.clear_action.triggered.connect(self.clear_content)

        # 菜单构建
        self.context_menu = QMenu(self)
        self.context_menu.addAction(self.copy_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.clear_action)

    def contextMenuEvent(self, event):
        self.context_menu.exec(event.globalPos())

    def clear_content(self):
        self.clear()
        self.append("内容已清空")

    def setup_dynamic_update(self):
        # 动态内容更新定时器
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.append_random_content)
        self.update_timer.start(3000)

    def append_random_content(self):
        try:
            colors = ["#FF5555", "#55FF55", "#5555FF", "#FFFF55"]
            formats = {
                "bold": QTextCharFormat(),
                "italic": QTextCharFormat(),
                "color": QTextCharFormat()
            }

            formats["bold"].setFontWeight(QFont.Bold)
            formats["italic"].setFontItalic(True)
            formats["color"].setForeground(QColor(random.choice(colors)))

            # 动态插入富文本
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)

            for _ in range(3):
                fmt = random.choice(list(formats.values()))
                cursor.setCharFormat(fmt)
                cursor.insertText(f"动态内容 {random.randint(1, 100)} ")

            self.setTextCursor(cursor)
            for _ in range(3):
                fmt = random.choice(list(formats.values()))
                cursor.setCharFormat(fmt)
                cursor.insertText(f"动态内容 {random.randint(1, 100)} ")

                # 添加执行点检查
                QApplication.processEvents()  # 防止界面冻结
        except KeyboardInterrupt:
            self.cleanup_resources()
            sys.exit(1)
        except Exception as e:
            print(f"内容生成错误: {repr(e)}")


def cleanup_resources(self):
    """安全释放资源"""
    self.update_timer.stop()
    self.text_browser.clear()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.center()

    def init_ui(self):
        self.setWindowTitle("增强型QTextBrowser演示")
        self.resize(800, 600)

        # 主控件布局
        central_widget = QWidget()
        layout = QVBoxLayout()

        self.text_browser = EnhancedTextBrowser()
        btn_insert_html = QPushButton("插入HTML内容")
        btn_insert_html.clicked.connect(self.insert_html_content)

        layout.addWidget(self.text_browser)
        layout.addWidget(btn_insert_html)
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def center(self):
        # 窗口居中实现
        frame_geo = self.frameGeometry()
        screen_center = self.screen().availableGeometry().center()
        frame_geo.moveCenter(screen_center)
        self.move(frame_geo.topLeft())

    def insert_html_content(self):
        html_content = """
        <div style='color:#FFA500; font-size:16pt;'>
            <b>HTML内容示例：</b>
            <ul>
                <li style='color:#00FF00;'>列表项1</li>
                <li style='color:#FF0000;'>列表项2</li>
            </ul>
            <img src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAOxAAADsQBlSsOGwAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAB/SURBVDiN7ZIxCsAgDEWfU7h1cS1O/QV/QDq5dXAQHLo4dHDoJxQKtVYQvAihr3k0JCEi6h0K8AB5mB0wA1vgHq4XwL7gCQx+2oE5kA8yDMBVkZkBlUy/6cXqgBXYgM3H7j5Hf5H0Bf7D3/MAUyYVHZF5zO8AAAAASUVORK5CYII='>
        </div>
        """
        self.text_browser.append(html_content)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
