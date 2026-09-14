from __future__ import annotations

from components.api_worker import AsyncApiMixin
from i18n.ui_localizer import format_api_error, localize_tree
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
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

    # Vertical rhythm for the credential forms: a tight gap keeps each label
    # attached to its own input, while FIELD_GAP separates one input from the
    # next field group.
    LABEL_GAP = 6
    FIELD_GAP = 18
    SECTION_GAP = 10
    AUTH_FIELD_HEIGHT = 38

    def __init__(self, api, parent=None):
        QDialog.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self._busy = False
        self._backend_connected: bool | None = None
        self.setWindowTitle("ModelForge · 本地工作区登录")
        self.setMinimumSize(440, 500)
        self.setModal(True)
        self._init_ui()
        hint = self.sizeHint()
        self.resize(max(hint.width(), 500), max(hint.height(), 560))
        self._check_backend_status()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 28)
        root.setSpacing(12)
        brand = QLabel("◈  MODEL FORGE")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet("font-size: 23px; font-weight: 800; letter-spacing: 3px;")
        root.addWidget(brand)
        subtitle = QLabel("本地 AI 工作区\n登录以连接你的 ModelForge 服务")
        subtitle.setProperty("role", "eyebrow")
        subtitle.setAlignment(Qt.AlignCenter)
        root.addWidget(subtitle)
        backend_row = QHBoxLayout()
        backend_row.setSpacing(6)
        backend_row.addStretch(1)
        self.backend_light = QLabel("●")
        self.backend_light.setProperty("status", "warning")
        self.backend_light.setAccessibleName("后端连接信号灯")
        self.backend = QLabel("后端：正在检查本地服务")
        self.backend.setProperty("status", "warning")
        self.backend.setToolTip(str(self.api.base_url))
        self.backend.setAccessibleName("服务端连接状态")
        backend_row.addWidget(self.backend_light)
        backend_row.addWidget(self.backend)
        backend_row.addStretch(1)
        root.addLayout(backend_row)
        self.notice = QLabel("请输入账号信息。")
        self.notice.setProperty("role", "muted")
        self.notice.setAlignment(Qt.AlignCenter)
        self.notice.setAccessibleName("登录操作状态")
        root.addWidget(self.notice)

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
        field.setFixedHeight(LoginDialog.AUTH_FIELD_HEIGHT)
        field.setPlaceholderText(placeholder)
        field.setAccessibleName(placeholder)
        if secret:
            field.setEchoMode(QLineEdit.Password)
            field.setAccessibleDescription("密码输入内容不会显示。")
        return field

    def _field_group(self, text: str, field: QLineEdit) -> QWidget:
        """Bundle a label with its input so groups can be spaced apart evenly."""
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.LABEL_GAP)
        layout.addWidget(self._label(text, field))
        layout.addWidget(field)
        return group

    @staticmethod
    def _form_layout() -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(32)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return form

    @staticmethod
    def _is_error_code(text: str) -> bool:
        candidate = text.split("(", 1)[0].strip()
        return bool(candidate) and all(char.isupper() or char.isdigit() or char in {"_", "-"} for char in candidate)

    def _display_error(self, error: str) -> str:
        return format_api_error(error) if self._is_error_code(str(error)) else str(error)

    def _polish_status(self, *widgets: QLabel) -> None:
        for widget in widgets:
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _set_backend_status(self, text: str, status: str, connected: bool | None) -> None:
        self._backend_connected = connected
        self.backend.setText(text)
        self.backend.setProperty("status", status)
        self.backend_light.setProperty("status", status)
        self._polish_status(self.backend, self.backend_light)

    def _set_notice(self, text: str, status: str | None = None) -> None:
        self.notice.setText(text)
        self.notice.setProperty("role", None if status else "muted")
        if status:
            self.notice.setProperty("status", status)
        else:
            self.notice.setProperty("status", None)
        self._polish_status(self.notice)

    def _check_backend_status(self) -> None:
        self._set_backend_status("后端：正在检查本地服务", "warning", None)
        self._run_api(
            self.api.get_info,
            self._backend_check_succeeded,
            self._backend_check_failed,
            request_key="backend_status",
        )

    def _backend_check_succeeded(self, _result) -> None:
        self._set_backend_status("后端：已连接", "online", True)

    def _backend_check_failed(self, error: str) -> None:
        self._set_backend_status(f"后端：未连接（{self._display_error(error)}）", "error", False)
        if not self._busy:
            self._set_notice("请确认 ModelForge 服务正在运行。", "error")

    def _ensure_backend_available(self) -> bool:
        if self._backend_connected is not False:
            return True
        self._check_backend_status()
        message = "后端服务未连接，请确认 ModelForge 服务正在运行后再试。"
        self._set_notice(message, "error")
        QMessageBox.warning(self, "后端未连接", message)
        return False

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
        layout.setSpacing(self.SECTION_GAP)
        hint = QLabel("登录后继续")
        hint.setProperty("role", "eyebrow")
        layout.addWidget(hint)
        self.login_user = self._field("用户名")
        self.login_pwd = self._field("密码", True)
        self.login_pwd.returnPressed.connect(self.handle_login)
        form = self._form_layout()
        form.addRow(self._label("用户名", self.login_user), self.login_user)
        form.addRow(self._label("密码", self.login_pwd), self.login_pwd)
        layout.addLayout(form)
        self.login_action = QPushButton("登录工作区")
        self.login_action.setProperty("accent", True)
        self.login_action.clicked.connect(self.handle_login)
        layout.addWidget(self.login_action)
        layout.addStretch(1)
        return page

    def _register_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(self.FIELD_GAP)
        hint = QLabel("创建本地工作区账号")
        hint.setProperty("role", "eyebrow")
        layout.addWidget(hint)
        self.reg_user = self._field("用户名（3–32 个字符）")
        self.reg_email = self._field("邮箱（可选）")
        self.reg_pwd = self._field("密码（至少 8 个字符）", True)
        self.reg_pwd2 = self._field("确认密码", True)
        self.reg_pwd2.returnPressed.connect(self.handle_register)
        self.reg_user.editingFinished.connect(lambda: self._validate_register_after_edit("username"))
        self.reg_email.editingFinished.connect(lambda: self._validate_register_after_edit("email"))
        self.reg_pwd.editingFinished.connect(lambda: self._validate_register_after_edit("password"))
        self.reg_pwd2.editingFinished.connect(lambda: self._validate_register_after_edit("confirmation"))
        form = self._form_layout()
        for text, field in (
            ("用户名", self.reg_user),
            ("邮箱（可选）", self.reg_email),
            ("密码", self.reg_pwd),
            ("确认密码", self.reg_pwd2),
        ):
            form.addRow(self._label(text, field), field)
        layout.addLayout(form)
        self.register_feedback = QLabel("填写后将自动校验账号信息。")
        self.register_feedback.setProperty("role", "muted")
        self.register_feedback.setAccessibleName("创建账号表单校验状态")
        layout.addWidget(self.register_feedback)
        self.register_action = QPushButton("创建账号")
        self.register_action.setProperty("accent", True)
        self.register_action.clicked.connect(self.handle_register)
        layout.addWidget(self.register_action)
        layout.addStretch(1)
        return page

    def _set_register_feedback(self, text: str, status: str | None = None) -> None:
        self.register_feedback.setText(text)
        self.register_feedback.setProperty("role", None if status else "muted")
        self.register_feedback.setProperty("status", status)
        self._polish_status(self.register_feedback)

    def _validate_register_field(self, field: str) -> tuple[bool, str]:
        username = self.reg_user.text().strip()
        email = self.reg_email.text().strip()
        password = self.reg_pwd.text()
        confirmation = self.reg_pwd2.text()
        if field == "username":
            if not username:
                return False, "请输入用户名。"
            if len(username) < 3 or len(username) > 32:
                return False, "用户名长度须在 3-32 个字符之间。"
            return True, "用户名格式正确。"
        if field == "email":
            if not email:
                return True, "邮箱可留空。"
            if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
                return False, "邮箱格式不正确。"
            return True, "邮箱格式正确。"
        if field == "password":
            if not password:
                return False, "请输入密码。"
            if len(password) < 8:
                return False, "密码至少 8 个字符。"
            return True, "密码长度正确。"
        if field == "confirmation":
            if not confirmation:
                return False, "请再次输入密码。"
            if password != confirmation:
                return False, "两次输入的密码不相同。"
            return True, "确认密码匹配。"
        return True, "表单校验通过。"

    def _validate_register_after_edit(self, field: str) -> None:
        ok, message = self._validate_register_field(field)
        self._set_register_feedback(message, "online" if ok else "error")
        value = {
            "username": self.reg_user.text().strip(),
            "email": self.reg_email.text().strip(),
            "password": self.reg_pwd.text(),
            "confirmation": self.reg_pwd2.text(),
        }[field]
        if not ok and value:
            QMessageBox.warning(self, "表单信息有误", message)

    def _validate_register_form(self) -> tuple[bool, str]:
        for field in ("username", "email", "password", "confirmation"):
            ok, message = self._validate_register_field(field)
            if not ok:
                return False, message
        return True, "表单校验通过。"

    def _set_busy(self, busy: bool, notice: str = "") -> None:
        self._busy = busy
        for button in (self.connect_button, self.create_button, self.login_action, self.register_action):
            button.setEnabled(not busy)
        if busy:
            self._set_notice(notice, "warning")

    def handle_login(self) -> None:
        if self._busy:
            return
        if not self._ensure_backend_available():
            return
        username, password = self.login_user.text().strip(), self.login_pwd.text()
        if not username:
            message = "请输入用户名。"
            self._set_notice(message, "error")
            QMessageBox.warning(self, "需要登录信息", message)
            return
        if not password:
            message = "请输入密码。"
            self._set_notice(message, "error")
            QMessageBox.warning(self, "需要登录信息", message)
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
        self._set_backend_status("后端：已连接", "online", True)
        self._set_notice("已验证身份。", "online")
        self.accept()

    def _login_failed(self, error: str) -> None:
        self._set_busy(False)
        message = self._display_error(error)
        self._set_notice(f"登录未完成：{message}", "error")
        if self._is_error_code(str(error)) and "SERVICE_UNAVAILABLE" in str(error):
            self._set_backend_status("后端：未连接", "error", False)
        self.login_pwd.setFocus()

    def handle_register(self) -> None:
        if self._busy:
            return
        if not self._ensure_backend_available():
            return
        username, email = self.reg_user.text().strip(), self.reg_email.text().strip()
        password = self.reg_pwd.text()
        ok, message = self._validate_register_form()
        self._set_register_feedback(message, "online" if ok else "error")
        if not ok:
            QMessageBox.warning(self, "表单信息有误", message)
            if "用户名" in message:
                self.reg_user.setFocus()
            elif "邮箱" in message:
                self.reg_email.setFocus()
            elif "再次" in message or "两次" in message:
                self.reg_pwd2.setFocus()
            else:
                self.reg_pwd.setFocus()
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
        self._set_backend_status("后端：已连接", "online", True)
        self._set_notice("账号已创建，请使用新账号登录。", "online")

    def _register_failed(self, error: str) -> None:
        self._set_busy(False)
        message = self._display_error(error)
        self._set_notice(f"账号创建未完成：{message}", "error")
        if self._is_error_code(str(error)) and "SERVICE_UNAVAILABLE" in str(error):
            self._set_backend_status("后端：未连接", "error", False)
        QMessageBox.warning(self, "账号创建未完成", message)
        self.reg_user.setFocus()

    def closeEvent(self, event) -> None:
        self.shutdown_async_api()
        super().closeEvent(event)
