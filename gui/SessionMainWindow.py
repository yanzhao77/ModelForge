"""
支持会话管理和记忆系统的主窗口
集成用户登录、会话管理、GGUF 下载等功能
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, Slot, QThread, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QVBoxLayout, QWidget, QSplitter,
    QToolBar, QProgressBar, QHBoxLayout, QMenuBar,
    QMessageBox, QTextEdit, QLineEdit, QPushButton,
    QLabel
)

from common.const.common_const import common_const
from gui.login_dialog import LoginDialog
from gui.session_sidebar import SessionSidebar
from gui.dialog.gguf_download_dialog import GGUFDownloadDialog
from database.db_manager import DatabaseManager
from pytorch.session_model_generate import SessionModelGenerate


class ModelThread(QThread):
    """模型推理线程"""
    response_ready = Signal(str)
    error_occurred = Signal(str)
    
    def __init__(self, model_generator, question):
        super().__init__()
        self.model_generator = model_generator
        self.question = question
    
    def run(self):
        try:
            response = self.model_generator.pipeline_answer(self.question)
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))


class SessionMainWindow(QMainWindow):
    """支持会话管理的主窗口"""
    
    def __init__(self):
        super().__init__()
        
        # 用户信息
        self.user_id = None
        self.username = None
        self.token = None
        
        # 数据库管理器
        self.db_manager = DatabaseManager()
        
        # 模型生成器
        self.model_generator = None
        self.current_session_id = None
        
        # 显示登录对话框
        if not self.show_login_dialog():
            sys.exit(0)
        
        # 初始化界面
        self.init_ui()
    
    def show_login_dialog(self):
        """显示登录对话框"""
        login_dialog = LoginDialog(self)
        
        if login_dialog.exec() == LoginDialog.Accepted:
            user_info = login_dialog.get_user_info()
            self.user_id = user_info['user_id']
            self.username = user_info['username']
            self.token = user_info['token']
            return True
        return False
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle(f"{common_const.project_name} - {self.username}")
        self.setMinimumSize(1200, 700)
        self.setWindowIcon(QIcon(common_const.icon_main_view))
        
        # 主容器
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # 菜单栏
        self.create_menu_bar()
        
        # 工具栏
        self.create_toolbar()
        
        # 主分割器（三栏布局）
        main_splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：会话列表
        self.session_sidebar = SessionSidebar(self.user_id, self)
        self.session_sidebar.session_switched.connect(self.on_session_switched)
        self.session_sidebar.session_created.connect(self.on_session_created)
        self.session_sidebar.session_deleted.connect(self.on_session_deleted)
        main_splitter.addWidget(self.session_sidebar)
        
        # 中间：对话区域
        chat_widget = self.create_chat_widget()
        main_splitter.addWidget(chat_widget)
        
        # 设置分割器比例
        main_splitter.setSizes([250, 950])
        
        main_layout.addWidget(main_splitter)
        
        # 进度条
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.hide()
        progress_layout.addStretch()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch()
        main_layout.addLayout(progress_layout)
        
        # 状态栏
        self.statusBar().showMessage(f"欢迎, {self.username}!")
        
        # 自动创建第一个会话
        if not self.session_sidebar.current_session_id:
            self.session_sidebar.create_new_session()
    
    def create_menu_bar(self):
        """创建菜单栏"""
        menu_bar = QMenuBar()
        
        # 文件菜单
        file_menu = menu_bar.addMenu("文件")
        
        new_session_action = QAction("新建对话", self)
        new_session_action.setShortcut("Ctrl+N")
        new_session_action.triggered.connect(self.session_sidebar.create_new_session)
        file_menu.addAction(new_session_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 模型菜单
        model_menu = menu_bar.addMenu("模型")
        
        load_model_action = QAction("加载模型", self)
        load_model_action.triggered.connect(self.load_model)
        model_menu.addAction(load_model_action)
        
        download_gguf_action = QAction("下载 GGUF 模型", self)
        download_gguf_action.triggered.connect(self.show_gguf_download_dialog)
        model_menu.addAction(download_gguf_action)
        
        # 会话菜单
        session_menu = menu_bar.addMenu("会话")
        
        clear_session_action = QAction("清空当前会话", self)
        clear_session_action.triggered.connect(self.clear_current_session)
        session_menu.addAction(clear_session_action)
        
        # 帮助菜单
        help_menu = menu_bar.addMenu("帮助")
        
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        self.setMenuBar(menu_bar)
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        
        # 新建会话
        new_session_btn = QAction("新建对话", self)
        new_session_btn.triggered.connect(self.session_sidebar.create_new_session)
        toolbar.addAction(new_session_btn)
        
        toolbar.addSeparator()
        
        # 加载模型
        load_model_btn = QAction("加载模型", self)
        load_model_btn.triggered.connect(self.load_model)
        toolbar.addAction(load_model_btn)
        
        # 下载 GGUF
        download_gguf_btn = QAction("下载 GGUF", self)
        download_gguf_btn.triggered.connect(self.show_gguf_download_dialog)
        toolbar.addAction(download_gguf_btn)
        
        self.addToolBar(toolbar)
    
    def create_chat_widget(self):
        """创建对话区域"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 对话显示区域
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        layout.addWidget(self.chat_display)
        
        # 输入区域
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息...")
        self.input_field.returnPressed.connect(self.send_message)
        self.input_field.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                font-size: 14px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)
        
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        
        layout.addLayout(input_layout)
        
        widget.setLayout(layout)
        return widget
    
    def load_model(self):
        """加载模型"""
        from PySide6.QtWidgets import QFileDialog
        
        model_path = QFileDialog.getExistingDirectory(
            self,
            "选择模型目录",
            str(common_const.default_model_path)
        )
        
        if model_path:
            self.statusBar().showMessage(f"正在加载模型: {model_path}")
            try:
                # 创建模型生成器
                self.model_generator = SessionModelGenerate(
                    user_id=self.user_id,
                    session_id=self.current_session_id,
                    db_manager=self.db_manager,
                    model_path=model_path
                )
                
                # 初始化模型
                self.model_generator.pipeline_question()
                
                self.statusBar().showMessage(f"模型加载成功: {model_path}")
                QMessageBox.information(self, "成功", "模型加载成功！")
            except Exception as e:
                self.statusBar().showMessage("模型加载失败")
                QMessageBox.critical(self, "错误", f"模型加载失败:\n{str(e)}")
    
    def show_gguf_download_dialog(self):
        """显示 GGUF 下载对话框"""
        dialog = GGUFDownloadDialog(self)
        dialog.exec()
    
    def send_message(self):
        """发送消息"""
        message = self.input_field.text().strip()
        if not message:
            return
        
        if not self.model_generator:
            QMessageBox.warning(self, "警告", "请先加载模型")
            return
        
        # 显示用户消息
        self.append_message("用户", message)
        self.input_field.clear()
        self.send_btn.setEnabled(False)
        
        # 在后台线程中生成回复
        self.model_thread = ModelThread(self.model_generator, message)
        self.model_thread.response_ready.connect(self.on_response_ready)
        self.model_thread.error_occurred.connect(self.on_error_occurred)
        self.model_thread.start()
    
    def on_response_ready(self, response):
        """收到模型回复"""
        self.append_message("助手", response)
        self.send_btn.setEnabled(True)
        self.session_sidebar.refresh()  # 刷新会话列表
    
    def on_error_occurred(self, error_msg):
        """发生错误"""
        self.append_message("系统", f"错误: {error_msg}")
        self.send_btn.setEnabled(True)
    
    def append_message(self, role: str, content: str):
        """添加消息到显示区域"""
        if role == "用户":
            html = f'<div style="margin: 10px 0;"><b style="color: #2196F3;">{role}:</b> {content}</div>'
        elif role == "助手":
            html = f'<div style="margin: 10px 0;"><b style="color: #4CAF50;">{role}:</b> {content}</div>'
        else:
            html = f'<div style="margin: 10px 0;"><b style="color: #FF5722;">{role}:</b> {content}</div>'
        
        self.chat_display.append(html)
    
    def on_session_switched(self, session_id: int):
        """会话切换"""
        self.current_session_id = session_id
        self.chat_display.clear()
        
        # 如果模型已加载，切换会话
        if self.model_generator:
            self.model_generator.switch_session(session_id)
            
            # 加载历史消息
            from api.session_service import SessionService
            with self.db_manager.get_session() as db:
                messages = SessionService.get_session_messages(db, session_id)
                for msg in messages:
                    self.append_message(
                        "用户" if msg.role == "user" else "助手",
                        msg.content
                    )
        
        self.statusBar().showMessage(f"已切换到会话 {session_id}")
    
    def on_session_created(self, session_id: int):
        """新会话创建"""
        self.current_session_id = session_id
        self.chat_display.clear()
        
        # 如果模型已加载，切换到新会话
        if self.model_generator:
            self.model_generator.switch_session(session_id)
        
        self.statusBar().showMessage("已创建新会话")
    
    def on_session_deleted(self, session_id: int):
        """会话删除"""
        if session_id == self.current_session_id:
            self.chat_display.clear()
        self.statusBar().showMessage("会话已删除")
    
    def clear_current_session(self):
        """清空当前会话"""
        if not self.current_session_id:
            return
        
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前会话的所有消息吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.model_generator:
                self.model_generator.clear_session()
            self.chat_display.clear()
            self.session_sidebar.refresh()
            QMessageBox.information(self, "成功", "会话已清空")
    
    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 ModelForge",
            f"""<h3>ModelForge</h3>
            <p>本地大模型推理与训练平台</p>
            <p>版本: 2.0 (支持会话管理和记忆系统)</p>
            <p>当前用户: {self.username}</p>
            <p><b>新功能:</b></p>
            <ul>
                <li>✅ 用户登录和注册</li>
                <li>✅ 多会话管理</li>
                <li>✅ 跨会话记忆</li>
                <li>✅ GGUF 模型下载</li>
                <li>✅ 对话历史持久化</li>
            </ul>
            """
        )
    
    def closeEvent(self, event):
        """关闭事件"""
        reply = QMessageBox.question(
            self,
            "确认退出",
            "确定要退出 ModelForge 吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 释放模型资源
            if self.model_generator:
                try:
                    self.model_generator.release_resources()
                except:
                    pass
            event.accept()
        else:
            event.ignore()
