from __future__ import annotations

from components.api_worker import AsyncApiMixin
from i18n.ui_localizer import format_api_error, localize_tree
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class LoginDialog(QDialog, AsyncApiMixin):
    """Accessible, cancellable desktop sign-in and registration entry point."""

    def __init__(self, api, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._busy = False
        self.setWindowTitle("ModelForge · 本地工作区登录")
        self.setMinimumSize(420, 430)
        self.resize(500, 490)
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
        subtitle = QLabel("本地 AI 工作区\n登录以连接你的 ModelForge 服务")
        subtitle.setProperty("role", "eyebrow")
        subtitle.setAlignment(Qt.AlignCenter)
        root.addWidget(subtitle)
        self.backend = QLabel("服务状态：正在检查本地服务")
        self.backend.setProperty("status", "warning")
        self.backend.setToolTip(str(self.api.base_url))
        self.backend.setAccessibleName("服务端连接状态")
        self.backend.setAlignment(Qt.AlignCenter)
        root.addWidget(self.backend)

        switches = QHBoxLayout()
        self.connect_button = QPushButton("登录")
        self.connect_button.setAccessibleName("显示登录表单")
        self.connect_button.setCheckable(True)
        self.connect_button.setChecked(True)
        self.connect_button.setProperty("accent", True)
        self.create_button = QPushButton("创建账号")
        self.create_button.setAccessibleName("显示创建账号表单")
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

    @staticmethod
    def _label(text: str, field: QLineEdit) -> QLabel:
        label = QLabel(text)
        label.setBuddy(field)
        return label

    @staticmethod
    def _field(placeholder: str, secret: bool = False) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setAccessibleName(placeholder)
        if secret:
            field.setEchoMode(QLineEdit.Password)
            field.setAccessibleDescription("密码输入内容不会显示。")
        return field

    def _show_page(self, index: int) -> None:
        if self._busy:
            return
        self.stack.setCurrentIndex(index)
        self.connect_button.setChecked(index == 0)
        self.create_button.setChecked(index == 1)
        self.connect_button.setProperty("accent", index == 0)
        self.create_button.setProperty("accent", index == 1)
        for button in (self.connect_button, self.create_button):
            button.style().unpolish(button)
            button.style().polish(button)

    def _login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        hint = QLabel("登录后继续")
        hint.setProperty("role", "eyebrow")
        layout.addWidget(hint)
        self.login_user = self._field("用户名")
        self.login_pwd = self._field("密码", True)
        self.login_pwd.returnPressed.connect(self.handle_login)
        layout.addWidget(self._label("用户名", self.login_user))
        layout.addWidget(self.login_user)
        layout.addWidget(self._label("密码", self.login_pwd))
        layout.addWidget(self.login_pwd)
        self.login_action = QPushButton("登录工作区")
        self.login_action.setProperty("accent", True)
        self.login_action.clicked.connect(self.handle_login)
        layout.addWidget(self.login_action)
        layout.addStretch(1)
        return page

    def _register_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(9)
        hint = QLabel("创建本地工作区账号")
        hint.setProperty("role", "eyebrow")
        layout.addWidget(hint)
        self.reg_user = self._field("用户名（3–32 个字符）")
        self.reg_email = self._field("邮箱（可选）")
        self.reg_pwd = self._field("密码（至少 8 个字符）", True)
        self.reg_pwd2 = self._field("确认密码", True)
        self.reg_pwd2.returnPressed.connect(self.handle_register)
        for text, field in (
            ("用户名", self.reg_user),
            ("邮箱（可选）", self.reg_email),
            ("密码", self.reg_pwd),
            ("确认密码", self.reg_pwd2),
        ):
            layout.addWidget(self._label(text, field))
            layout.addWidget(field)
        self.register_action = QPushButton("创建账号")
        self.register_action.setProperty("accent", True)
        self.register_action.clicked.connect(self.handle_register)
        layout.addWidget(self.register_action)
        return page

    def _set_busy(self, busy: bool, notice: str = "") -> None:
        self._busy = busy
        for button in (self.connect_button, self.create_button, self.login_action, self.register_action):
            button.setEnabled(not busy)
        if busy:
            self.backend.setText(notice)
            self.backend.setProperty("status", "warning")
            self.backend.style().unpolish(self.backend)
            self.backend.style().polish(self.backend)

    def handle_login(self) -> None:
        if self._busy:
            return
        username, password = self.login_user.text().strip(), self.login_pwd.text()
        if not username or not password:
            QMessageBox.warning(self, "需要登录信息", "请输入用户名和密码。")
            return
        self._set_busy(True, "正在验证登录信息…")
        self._run_api(
            lambda: self.api.login(username, password),
            self._login_succeeded,
            self._login_failed,
            request_key="login",
        )

    def _login_succeeded(self, _result) -> None:
        self._set_busy(False)
        self.backend.setText("服务状态：已验证身份")
        self.backend.setProperty("status", "online")
        self.backend.style().unpolish(self.backend)
        self.backend.style().polish(self.backend)
        self.accept()

    def _login_failed(self, error: str) -> None:
        self._set_busy(False)
        self.backend.setText(f"登录未完成：{format_api_error(error)}")
        self.backend.setProperty("status", "error")
        self.backend.style().unpolish(self.backend)
        self.backend.style().polish(self.backend)
        self.login_pwd.setFocus()

    def handle_register(self) -> None:
        if self._busy:
            return
        username, email = self.reg_user.text().strip(), self.reg_email.text().strip()
        password, confirmation = self.reg_pwd.text(), self.reg_pwd2.text()
        if not username or not password:
            QMessageBox.warning(self, "需要账号信息", "用户名和密码不能为空。")
            return
        if password != confirmation:
            QMessageBox.warning(self, "密码不一致", "两次输入的密码不相同。")
            self.reg_pwd2.setFocus()
            return
        self._set_busy(True, "正在创建账号…")
        self._run_api(
            lambda: self.api.register(username, password, email or None),
            lambda _result: self._register_succeeded(username),
            self._register_failed,
            request_key="register",
        )

    def _register_succeeded(self, username: str) -> None:
        self._set_busy(False)
        self.login_user.setText(username)
        self.login_pwd.setFocus()
        self._show_page(0)
        self.backend.setText("账号已创建，请使用新账号登录。")
        self.backend.setProperty("status", "online")
        self.backend.style().unpolish(self.backend)
        self.backend.style().polish(self.backend)

    def _register_failed(self, error: str) -> None:
        self._set_busy(False)
        QMessageBox.warning(self, "账号创建未完成", format_api_error(error))
        self.reg_user.setFocus()

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
