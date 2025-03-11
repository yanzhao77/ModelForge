from typing import Any, Dict, Optional
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QWidget, QMessageBox
)

from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class DialogConfig:
    """对话框配置"""
    title: str = ""
    icon: str = ""
    width: int = 600
    height: int = 400
    modal: bool = True
    resizable: bool = True

class BaseDialog(QDialog):
    """基础对话框类"""
    
    # 自定义信号
    data_changed = Signal(dict)  # 数据变更信号
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        config: Optional[DialogConfig] = None
    ):
        """
        初始化基础对话框
        
        Args:
            parent: 父窗口
            config: 对话框配置
        """
        try:
            super().__init__(parent)
            
            # 保存配置
            self.config = config or DialogConfig()
            
            # 设置窗口属性
            self._setup_window()
            
            # 创建布局
            self.main_layout = QVBoxLayout()
            self.setLayout(self.main_layout)
            
            # 初始化UI
            self._init_ui()
            
            logger.debug(f"对话框 {self.__class__.__name__} 初始化完成")
        except Exception as e:
            logger.error(f"对话框初始化失败: {str(e)}")
            raise
            
    def _setup_window(self):
        """设置窗口属性"""
        try:
            # 设置标题
            self.setWindowTitle(self.config.title)
            
            # 设置图标
            if self.config.icon:
                self.setWindowIcon(QIcon(self.config.icon))
            
            # 设置大小
            self.resize(self.config.width, self.config.height)
            
            # 设置模态
            if self.config.modal:
                self.setWindowModality(Qt.WindowModal)
            
            # 设置是否可调整大小
            if not self.config.resizable:
                self.setFixedSize(self.config.width, self.config.height)
                
            logger.debug("窗口属性设置完成")
        except Exception as e:
            logger.error(f"设置窗口属性失败: {str(e)}")
            raise
            
    def _init_ui(self):
        """初始化UI"""
        try:
            # 创建内容区域
            self._create_content()
            
            # 创建按钮区域
            self._create_buttons()
            
            logger.debug("UI初始化完成")
        except Exception as e:
            logger.error(f"初始化UI失败: {str(e)}")
            raise
            
    def _create_content(self):
        """创建内容区域"""
        # 子类实现具体内容
        pass
        
    def _create_buttons(self):
        """创建按钮区域"""
        try:
            # 创建按钮布局
            button_layout = QHBoxLayout()
            
            # 创建确定和取消按钮
            self.ok_button = QPushButton("确定")
            self.cancel_button = QPushButton("取消")
            
            # 设置按钮属性
            self.ok_button.setDefault(True)
            self.ok_button.clicked.connect(self.accept)
            self.cancel_button.clicked.connect(self.reject)
            
            # 添加按钮到布局
            button_layout.addStretch()
            button_layout.addWidget(self.ok_button)
            button_layout.addWidget(self.cancel_button)
            
            # 添加按钮布局到主布局
            self.main_layout.addLayout(button_layout)
            
            logger.debug("按钮区域创建完成")
        except Exception as e:
            logger.error(f"创建按钮区域失败: {str(e)}")
            raise
            
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        # 子类实现具体数据设置
        pass
        
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        # 子类实现具体数据获取
        return {}
        
    def validate(self) -> bool:
        """验证数据"""
        # 子类实现具体验证逻辑
        return True
        
    def accept(self):
        """确定按钮处理"""
        try:
            # 验证数据
            if not self.validate():
                return
                
            # 发送数据变更信号
            self.data_changed.emit(self.get_data())
            
            # 调用父类的accept
            super().accept()
            
            logger.debug("对话框已确认")
        except Exception as e:
            logger.error(f"确认对话框失败: {str(e)}")
            self.show_error("确认失败", str(e))
            
    def reject(self):
        """取消按钮处理"""
        try:
            super().reject()
            logger.debug("对话框已取消")
        except Exception as e:
            logger.error(f"取消对话框失败: {str(e)}")
            
    def show_error(self, title: str, message: str):
        """显示错误消息"""
        try:
            QMessageBox.critical(self, title, message)
            logger.error(f"显示错误消息: {title} - {message}")
        except Exception as e:
            logger.error(f"显示错误消息失败: {str(e)}")
            
    def show_warning(self, title: str, message: str):
        """显示警告消息"""
        try:
            QMessageBox.warning(self, title, message)
            logger.warning(f"显示警告消息: {title} - {message}")
        except Exception as e:
            logger.error(f"显示警告消息失败: {str(e)}")
            
    def show_info(self, title: str, message: str):
        """显示信息消息"""
        try:
            QMessageBox.information(self, title, message)
            logger.info(f"显示信息消息: {title} - {message}")
        except Exception as e:
            logger.error(f"显示信息消息失败: {str(e)}")
            
    def show_question(self, title: str, message: str) -> bool:
        """显示询问消息"""
        try:
            reply = QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            return reply == QMessageBox.Yes
        except Exception as e:
            logger.error(f"显示询问消息失败: {str(e)}")
            return False 