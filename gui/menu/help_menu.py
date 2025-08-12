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
        <p><b>ModelForge</b> 是一个本地大模型推理与训练平台，支持多种模型格式（如 <b>safetensors</b>、<b>gguf</b>），可通过图形界面与模型交互，支持在线搜索增强与性能监控。</p>
        <ul>
            <li>支持 HuggingFace Transformers（safetensors）和 llama-cpp-python（gguf）模型加载与推理</li>
            <li>自动识别模型格式，智能选择推理后端</li>
            <li>PySide6 图形界面，支持启动过渡动画</li>
            <li>在线搜索增强（Web Search）</li>
            <li>性能监控与日志输出</li>
            <li>支持 Windows 平台一键打包</li>
        </ul>
        <p>适合 AI 开发者和研究者在本地环境下高效调用和微调大模型。</p>
        <p style="color:gray;font-size:small;">仅供学习与研究使用，禁止用于商业用途。</p>
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
