"""ModelForge workstation connection dialog."""
from __future__ import annotations
from i18n.ui_localizer import localize_tree

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget


class LoginDialog(QDialog):
    """Connects a local desktop workstation to the existing API service."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("ModelForge · 本地工作区登录")
        self.setFixedSize(500, 490)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 30)
        root.setSpacing(14)
        brand = QLabel("◈  MODEL FORGE")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet("font-size: 23px; font-weight: 800; letter-spacing: 3px;")
        root.addWidget(brand)
        subtitle = QLabel("本地 AI 工作区\n连接你的 ModelForge 服务")
        subtitle.setProperty("role", "eyebrow")
        subtitle.setAlignment(Qt.AlignCenter)
        root.addWidget(subtitle)
        self.backend = QLabel(f"●  BACKEND ENDPOINT  {self.api.base_url}")
        self.backend.setProperty("status", "warning")
        self.backend.setAlignment(Qt.AlignCenter)
        root.addWidget(self.backend)

        switches = QHBoxLayout()
        self.connect_button = QPushButton("登录")
        self.connect_button.setCheckable(True)
        self.connect_button.setChecked(True)
        self.connect_button.setProperty("accent", True)
        self.create_button = QPushButton("创建账号")
        self.create_button.setCheckable(True)
        self.connect_button.clicked.connect(lambda: self._show_page(0))
        self.create_button.clicked.connect(lambda: self._show_page(1))
        switches.addWidget(self.connect_button)
        switches.addWidget(self.create_button)
        root.addLayout(switches)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._login_page())
        self.stack.addWidget(self._register_page())
        root.addWidget(self.stack, 1)
        localize_tree(self)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.connect_button.setChecked(index == 0)
        self.create_button.setChecked(index == 1)
        self.connect_button.setProperty("accent", index == 0)
        self.create_button.setProperty("accent", index == 1)
        for button in (self.connect_button, self.create_button):
            button.style().unpolish(button)
            button.style().polish(button)

    @staticmethod
    def _field(placeholder: str, secret: bool = False) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        if secret:
            field.setEchoMode(QLineEdit.Password)
        return field

    def _login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        hint = QLabel("登录后继续")
        hint.setProperty("role", "eyebrow")
        layout.addWidget(hint)
        self.login_user = self._field("WORKSTATION USERNAME")
        self.login_pwd = self._field("ACCESS PASSWORD", True)
        self.login_pwd.returnPressed.connect(self.handle_login)
        layout.addWidget(self.login_user)
        layout.addWidget(self.login_pwd)
        action = QPushButton("登录工作区")
        action.setProperty("accent", True)
        action.clicked.connect(self.handle_login)
        layout.addWidget(action)
        layout.addStretch(1)
        return page

    def _register_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(9)
        hint = QLabel("创建本地工作区账号")
        hint.setProperty("role", "eyebrow")
        layout.addWidget(hint)
        self.reg_user = self._field("USERNAME · 3–32 CHARACTERS")
        self.reg_email = self._field("EMAIL · OPTIONAL")
        self.reg_pwd = self._field("PASSWORD · AT LEAST 6 CHARACTERS", True)
        self.reg_pwd2 = self._field("CONFIRM PASSWORD", True)
        self.reg_pwd2.returnPressed.connect(self.handle_register)
        for field in (self.reg_user, self.reg_email, self.reg_pwd, self.reg_pwd2):
            layout.addWidget(field)
        action = QPushButton("创建账号")
        action.setProperty("accent", True)
        action.clicked.connect(self.handle_register)
        layout.addWidget(action)
        return page

    def handle_login(self) -> None:
        username, password = self.login_user.text().strip(), self.login_pwd.text()
        if not username or not password:
            QMessageBox.warning(self, "Connection required", "Enter your workstation username and password.")
            return
        try:
            self.api.login(username, password)
        except Exception as error:
            self.backend.setText(f"●  CONNECTION FAILED  ·  {error}")
            self.backend.setProperty("status", "error")
            self.backend.style().unpolish(self.backend)
            self.backend.style().polish(self.backend)
            return
        self.backend.setText("●  BACKEND AUTHENTICATED")
        self.backend.setProperty("status", "online")
        self.accept()

    def handle_register(self) -> None:
        username, email = self.reg_user.text().strip(), self.reg_email.text().strip()
        password, confirmation = self.reg_pwd.text(), self.reg_pwd2.text()
        if not username or not password:
            QMessageBox.warning(self, "Account required", "Username and password are required.")
            return
        if password != confirmation:
            QMessageBox.warning(self, "Password confirmation", "The supplied passwords do not match.")
            return
        try:
            self.api.register(username, password, email or None)
        except Exception as error:
            QMessageBox.warning(self, "Account creation", str(error))
            return
        self.login_user.setText(username)
        self.login_pwd.setFocus()
        self._show_page(0)
