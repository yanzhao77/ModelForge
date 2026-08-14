"""登录/注册对话框（对接新版后端 /api/v1/auth/*）。"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QTabWidget, QWidget,
)
from PySide6.QtCore import Qt

from api_client.client import ModelForgeClient


class LoginDialog(QDialog):
    """登录 + 注册对话框，成功后持有 token 并 accept。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("ModelForge - 用户登录")
        self.setFixedSize(420, 320)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("欢迎使用 ModelForge")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 8px;")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_login_tab(), "登录")
        self.tabs.addTab(self._create_register_tab(), "注册")
        layout.addWidget(self.tabs)
        self.setLayout(layout)

    def _row(self, label: str, echo: bool = False) -> QLineEdit:
        edit = QLineEdit()
        if echo:
            edit.setEchoMode(QLineEdit.Password)
        return edit

    def _create_login_tab(self) -> QWidget:
        w = QWidget();
        lay = QVBoxLayout()
        self.login_user = QLineEdit();
        self.login_user.setPlaceholderText("用户名");
        self.login_pwd = QLineEdit();
        self.login_pwd.setPlaceholderText("密码");
        self.login_pwd.setEchoMode(QLineEdit.Password);
        self.login_pwd.returnPressed.connect(self.handle_login);
        btn = QPushButton("登录");
        btn.clicked.connect(self.handle_login);
        lay.addWidget(QLabel("用户名:"));
        lay.addWidget(self.login_user);
        lay.addWidget(QLabel("密码:"));
        lay.addWidget(self.login_pwd);
        lay.addWidget(btn);
        lay.addStretch();
        w.setLayout(lay);
        return w

    def _create_register_tab(self) -> QWidget:
        w = QWidget();
        lay = QVBoxLayout()
        self.reg_user = QLineEdit();
        self.reg_user.setPlaceholderText("用户名（3-32 字符）");
        self.reg_email = QLineEdit();
        self.reg_email.setPlaceholderText("邮箱（可选）");
        self.reg_pwd = QLineEdit();
        self.reg_pwd.setPlaceholderText("密码（至少 6 位）");
        self.reg_pwd.setEchoMode(QLineEdit.Password);
        self.reg_pwd2 = QLineEdit();
        self.reg_pwd2.setPlaceholderText("确认密码");
        self.reg_pwd2.setEchoMode(QLineEdit.Password);
        self.reg_pwd2.returnPressed.connect(self.handle_register);
        btn = QPushButton("注册");
        btn.clicked.connect(self.handle_register);
        lay.addWidget(QLabel("用户名:"));
        lay.addWidget(self.reg_user);
        lay.addWidget(QLabel("邮箱:"));
        lay.addWidget(self.reg_email);
        lay.addWidget(QLabel("密码:"));
        lay.addWidget(self.reg_pwd);
        lay.addWidget(QLabel("确认密码:"));
        lay.addWidget(self.reg_pwd2);
        lay.addWidget(btn);
        lay.addStretch();
        w.setLayout(lay);
        return w

    def handle_login(self):
        username = self.login_user.text().strip()
        password = self.login_pwd.text()
        if not username or not password:
            QMessageBox.warning(self, "提示", "请输入用户名和密码");
            return
        try:
            self.api.login(username, password)
        except Exception as e:
            QMessageBox.warning(self, "登录失败", str(e));
            return
        QMessageBox.information(self, "成功", f"欢迎回来，{username}！");
        self.accept()

    def handle_register(self):
        username = self.reg_user.text().strip()
        email = self.reg_email.text().strip()
        pwd = self.reg_pwd.text()
        pwd2 = self.reg_pwd2.text()
        if not username or not pwd:
            QMessageBox.warning(self, "提示", "用户名和密码不能为空");
            return
        if pwd != pwd2:
            QMessageBox.warning(self, "提示", "两次密码不一致");
            return
        try:
            self.api.register(username, pwd, email or None)
        except Exception as e:
            QMessageBox.warning(self, "注册失败", str(e));
            return
        QMessageBox.information(self, "成功", "注册成功，请登录");
        self.tabs.setCurrentIndex(0)
        self.login_user.setText(username)
        self.login_pwd.setFocus()