"""
登录/注册对话框
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QTabWidget, QWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon

from database.db_manager import DatabaseManager
from api.auth_service import AuthService


class LoginDialog(QDialog):
    """登录/注册对话框"""
    
    # 定义信号
    login_success = Signal(int, str, str)  # user_id, username, token
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_manager = DatabaseManager()
        self.user_id = None
        self.username = None
        self.token = None
        
        self.init_ui()
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("ModelForge - 用户登录")
        self.setFixedSize(400, 300)
        self.setModal(True)
        
        # 主布局
        main_layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("欢迎使用 ModelForge")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        main_layout.addWidget(title_label)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 登录标签页
        login_tab = self._create_login_tab()
        tab_widget.addTab(login_tab, "登录")
        
        # 注册标签页
        register_tab = self._create_register_tab()
        tab_widget.addTab(register_tab, "注册")
        
        main_layout.addWidget(tab_widget)
        
        self.setLayout(main_layout)
    
    def _create_login_tab(self):
        """创建登录标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 用户名
        username_layout = QHBoxLayout()
        username_label = QLabel("用户名:")
        username_label.setFixedWidth(70)
        self.login_username_input = QLineEdit()
        self.login_username_input.setPlaceholderText("请输入用户名")
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.login_username_input)
        layout.addLayout(username_layout)
        
        # 密码
        password_layout = QHBoxLayout()
        password_label = QLabel("密码:")
        password_label.setFixedWidth(70)
        self.login_password_input = QLineEdit()
        self.login_password_input.setPlaceholderText("请输入密码")
        self.login_password_input.setEchoMode(QLineEdit.Password)
        self.login_password_input.returnPressed.connect(self.handle_login)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.login_password_input)
        layout.addLayout(password_layout)
        
        # 登录按钮
        login_btn = QPushButton("登录")
        login_btn.clicked.connect(self.handle_login)
        login_btn.setStyleSheet("padding: 8px; font-size: 14px;")
        layout.addWidget(login_btn)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def _create_register_tab(self):
        """创建注册标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 用户名
        username_layout = QHBoxLayout()
        username_label = QLabel("用户名:")
        username_label.setFixedWidth(70)
        self.register_username_input = QLineEdit()
        self.register_username_input.setPlaceholderText("请输入用户名")
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.register_username_input)
        layout.addLayout(username_layout)
        
        # 邮箱
        email_layout = QHBoxLayout()
        email_label = QLabel("邮箱:")
        email_label.setFixedWidth(70)
        self.register_email_input = QLineEdit()
        self.register_email_input.setPlaceholderText("请输入邮箱（可选）")
        email_layout.addWidget(email_label)
        email_layout.addWidget(self.register_email_input)
        layout.addLayout(email_layout)
        
        # 密码
        password_layout = QHBoxLayout()
        password_label = QLabel("密码:")
        password_label.setFixedWidth(70)
        self.register_password_input = QLineEdit()
        self.register_password_input.setPlaceholderText("请输入密码")
        self.register_password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.register_password_input)
        layout.addLayout(password_layout)
        
        # 确认密码
        confirm_layout = QHBoxLayout()
        confirm_label = QLabel("确认密码:")
        confirm_label.setFixedWidth(70)
        self.register_confirm_input = QLineEdit()
        self.register_confirm_input.setPlaceholderText("请再次输入密码")
        self.register_confirm_input.setEchoMode(QLineEdit.Password)
        self.register_confirm_input.returnPressed.connect(self.handle_register)
        confirm_layout.addWidget(confirm_label)
        confirm_layout.addWidget(self.register_confirm_input)
        layout.addLayout(confirm_layout)
        
        # 注册按钮
        register_btn = QPushButton("注册")
        register_btn.clicked.connect(self.handle_register)
        register_btn.setStyleSheet("padding: 8px; font-size: 14px;")
        layout.addWidget(register_btn)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def handle_login(self):
        """处理登录"""
        username = self.login_username_input.text().strip()
        password = self.login_password_input.text()
        
        if not username or not password:
            QMessageBox.warning(self, "警告", "请输入用户名和密码")
            return
        
        # 调用认证服务
        with self.db_manager.get_session() as db:
            success, message, user, token = AuthService.login_user(db, username, password)
            
            if success:
                self.user_id = user.id
                self.username = user.username
                self.token = token
                
                # 发射登录成功信号
                self.login_success.emit(user.id, user.username, token)
                
                QMessageBox.information(self, "成功", f"欢迎回来，{username}！")
                self.accept()
            else:
                QMessageBox.warning(self, "登录失败", message)
    
    def handle_register(self):
        """处理注册"""
        username = self.register_username_input.text().strip()
        email = self.register_email_input.text().strip()
        password = self.register_password_input.text()
        confirm = self.register_confirm_input.text()
        
        # 验证输入
        if not username or not password:
            QMessageBox.warning(self, "警告", "用户名和密码不能为空")
            return
        
        if len(username) < 3:
            QMessageBox.warning(self, "警告", "用户名至少3个字符")
            return
        
        if len(password) < 6:
            QMessageBox.warning(self, "警告", "密码至少6个字符")
            return
        
        if password != confirm:
            QMessageBox.warning(self, "警告", "两次密码输入不一致")
            return
        
        # 调用认证服务
        with self.db_manager.get_session() as db:
            success, message, user = AuthService.register_user(
                db, username, password, email if email else None
            )
            
            if success:
                QMessageBox.information(self, "成功", f"注册成功！请登录。")
                # 清空注册表单
                self.register_username_input.clear()
                self.register_email_input.clear()
                self.register_password_input.clear()
                self.register_confirm_input.clear()
                
                # 切换到登录标签页
                self.findChild(QTabWidget).setCurrentIndex(0)
                # 自动填充用户名
                self.login_username_input.setText(username)
                self.login_password_input.setFocus()
            else:
                QMessageBox.warning(self, "注册失败", message)
    
    def get_user_info(self):
        """获取登录用户信息"""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "token": self.token
        }
