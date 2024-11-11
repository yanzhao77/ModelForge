from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox, QDialog
)


class model_open_dialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()

    def initUI(self):
        self.setWindowTitle('模型配置')
        self.model_name = ""
        self.model_path = ""
        # 主布局
        layout = QVBoxLayout()

        # 模型名称
        model_name_layout = QHBoxLayout()
        model_name_label = QLabel('模型名称:')
        self.model_name_input = QLineEdit()
        model_name_layout.addWidget(model_name_label)
        model_name_layout.addWidget(self.model_name_input)
        layout.addLayout(model_name_layout)

        # 模型地址
        model_path_layout = QHBoxLayout()
        model_path_label = QLabel('模型地址:')
        self.model_path_input = QLineEdit()
        browse_button = QPushButton('浏览')  # 使用默认按钮样式
        browse_button.clicked.connect(self.browse_folder)
        model_path_layout.addWidget(model_path_label)
        model_path_layout.addWidget(self.model_path_input)
        model_path_layout.addWidget(browse_button)
        layout.addLayout(model_path_layout)

        # 保存按钮
        save_button = QPushButton('打开模型')
        save_button.clicked.connect(self.save_config)
        layout.addWidget(save_button)

        self.setLayout(layout)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择文件夹')
        if folder:
            self.model_path_input.setText(folder)

    def save_config(self):
        self.model_name = self.model_name_input.text().strip()
        self.model_path = self.model_path_input.text().strip()

        if not self.model_name or not self.model_path:
            QMessageBox.warning(self, '警告', '模型名称和地址不能为空！')
            return
        self.accept()  # 关闭对话框
