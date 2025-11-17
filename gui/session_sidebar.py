"""
会话管理侧边栏
显示用户的所有会话，支持创建、删除、切换会话
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QMenu, QLabel
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QAction

from database.db_manager import DatabaseManager
from api.session_service import SessionService


class SessionSidebar(QWidget):
    """会话管理侧边栏"""
    
    # 定义信号
    session_switched = Signal(int)  # session_id
    session_created = Signal(int)  # session_id
    session_deleted = Signal(int)  # session_id
    
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.db_manager = DatabaseManager()
        self.current_session_id = None
        
        self.init_ui()
        self.load_sessions()
    
    def init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 标题
        title_label = QLabel("对话列表")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(title_label)
        
        # 新建会话按钮
        new_session_btn = QPushButton("+ 新建对话")
        new_session_btn.clicked.connect(self.create_new_session)
        new_session_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        layout.addWidget(new_session_btn)
        
        # 会话列表
        self.session_list = QListWidget()
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.show_context_menu)
        self.session_list.itemClicked.connect(self.on_session_clicked)
        self.session_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)
        layout.addWidget(self.session_list)
        
        self.setLayout(layout)
    
    def load_sessions(self):
        """加载会话列表"""
        self.session_list.clear()
        
        with self.db_manager.get_session() as db:
            sessions = SessionService.get_user_sessions(db, self.user_id)
            
            for session in sessions:
                # 获取消息数量
                message_count = SessionService.get_session_message_count(db, session.id)
                
                # 创建列表项
                item_text = f"{session.title}\n{message_count} 条消息"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, session.id)
                
                # 高亮当前会话
                if session.id == self.current_session_id:
                    item.setSelected(True)
                
                self.session_list.addItem(item)
    
    def create_new_session(self):
        """创建新会话"""
        with self.db_manager.get_session() as db:
            session = SessionService.create_session(
                db=db,
                user_id=self.user_id,
                title="新对话"
            )
            self.current_session_id = session.id
            self.load_sessions()
            self.session_created.emit(session.id)
    
    def on_session_clicked(self, item: QListWidgetItem):
        """会话被点击"""
        session_id = item.data(Qt.UserRole)
        if session_id != self.current_session_id:
            self.current_session_id = session_id
            self.session_switched.emit(session_id)
    
    def show_context_menu(self, position):
        """显示右键菜单"""
        item = self.session_list.itemAt(position)
        if not item:
            return
        
        session_id = item.data(Qt.UserRole)
        
        menu = QMenu()
        
        # 重命名
        rename_action = QAction("重命名", self)
        rename_action.triggered.connect(lambda: self.rename_session(session_id))
        menu.addAction(rename_action)
        
        # 清空消息
        clear_action = QAction("清空消息", self)
        clear_action.triggered.connect(lambda: self.clear_session(session_id))
        menu.addAction(clear_action)
        
        menu.addSeparator()
        
        # 删除
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self.delete_session(session_id))
        menu.addAction(delete_action)
        
        menu.exec_(self.session_list.mapToGlobal(position))
    
    def rename_session(self, session_id: int):
        """重命名会话"""
        from PySide6.QtWidgets import QInputDialog
        
        with self.db_manager.get_session() as db:
            session = SessionService.get_session_by_id(db, session_id, self.user_id)
            if not session:
                return
            
            new_title, ok = QInputDialog.getText(
                self,
                "重命名对话",
                "请输入新的对话标题:",
                text=session.title
            )
            
            if ok and new_title.strip():
                SessionService.update_session_title(db, session_id, new_title.strip(), self.user_id)
                self.load_sessions()
    
    def clear_session(self, session_id: int):
        """清空会话消息"""
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空此对话的所有消息吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            with self.db_manager.get_session() as db:
                SessionService.clear_session_messages(db, session_id, self.user_id)
                self.load_sessions()
                QMessageBox.information(self, "成功", "消息已清空")
    
    def delete_session(self, session_id: int):
        """删除会话"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除此对话吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            with self.db_manager.get_session() as db:
                SessionService.delete_session(db, session_id, self.user_id)
                
                # 如果删除的是当前会话，创建新会话
                if session_id == self.current_session_id:
                    self.create_new_session()
                else:
                    self.load_sessions()
                
                self.session_deleted.emit(session_id)
                QMessageBox.information(self, "成功", "对话已删除")
    
    def set_current_session(self, session_id: int):
        """设置当前会话"""
        self.current_session_id = session_id
        self.load_sessions()
    
    def refresh(self):
        """刷新会话列表"""
        self.load_sessions()
