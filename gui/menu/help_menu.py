from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap, QAction
from PySide6.QtWidgets import QMenuBar, QDialog, QVBoxLayout, QLabel, QPushButton

from common.const.common_const import common_const


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {common_const.project_name} {common_const.version}")

        # 创建布局
        layout = QVBoxLayout()

        # 添加图标
        icon_label = QLabel(self)
        pixmap = QPixmap(common_const.transition_main_view).scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # 添加标题
        title_label = QLabel("<h1>ModelForge 1.0</h1>", self)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # 添加描述
        description_text = """
        <p>Welcome to ModelForge 1.0, the ultimate tool for managing and running your machine learning models!</p>
        <p>With ModelForge, you can easily load, run, and switch between different models, all from a user-friendly interface.</p>
        <p>Features:</p>
        <ul>
            <li>Load and run multiple models</li>
            <li>Switch between models seamlessly</li>
            <li>Manage resources efficiently</li>
            <li>User-friendly GUI</li>
        </ul>
        <p>Thank you for using ModelForge 1.0!</p>
        """
        description_label = QLabel(description_text, self)
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description_label)

        # 添加关闭按钮
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self.setLayout(layout)


class help_menu(QMenuBar):
    def __init__(self, menu_Bar=QMenuBar):
        super().__init__(menu_Bar)

        # 创建 Help 菜单
        help_menu = menu_Bar.addMenu('Help')

        # 添加 About 动作
        about_action = QAction('About', self)
        about_action.triggered.connect(self.show_about_dialog)  # 连接槽函数
        help_menu.addAction(about_action)

    @Slot()
    def show_about_dialog(self):
        # 显示关于对话框
        dialog = AboutDialog(self)
        dialog.exec()
