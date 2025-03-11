from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices, QIcon, QAction
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, 
    QHBoxLayout, QScrollArea, QWidget, QFrame, QMenu, QMessageBox
)

from common.const.common_const import LoggerNames, get_logger, common_const
from common.const.config import config_manager
from .base_menu import BaseMenu, MenuAction
import sys

logger = get_logger(LoggerNames.UI)

@dataclass
class HelpMenuConfig:
    """帮助菜单配置"""
    actions: Dict[str, MenuAction] = field(default_factory=lambda: {
        "documentation": MenuAction(
            name="documentation",
            text="文档",
            shortcut="F1",
            tooltip="查看在线文档",
            status_tip="打开在线文档网站"
        ),
        "tutorial": MenuAction(
            name="tutorial",
            text="教程",
            tooltip="查看使用教程",
            status_tip="打开使用教程页面"
        ),
        "report_bug": MenuAction(
            name="report_bug",
            text="报告问题",
            tooltip="报告问题或提出建议",
            status_tip="打开问题报告页面"
        ),
        "check_update": MenuAction(
            name="check_update",
            text="检查更新",
            tooltip="检查新版本",
            status_tip="检查是否有新版本可用"
        ),
        "about": MenuAction(
            name="about",
            text="关于",
            tooltip="关于本软件",
            status_tip="显示关于对话框"
        )
    })
    
    urls: Dict[str, str] = field(default_factory=lambda: {
        "documentation": "https://modelforge.readthedocs.io/",
        "tutorial": "https://modelforge.readthedocs.io/tutorial/",
        "report_bug": "https://github.com/modelforge/issues",
        "check_update": "https://github.com/modelforge/releases"
    })

@dataclass
class AboutInfo:
    """关于对话框信息"""
    title: str = "关于 ModelForge 1.0"
    app_name: str = "ModelForge 1.0"
    description: str = """
        <p>欢迎使用 ModelForge 1.0，这是一个强大的机器学习模型管理和运行工具！</p>
        <p>使用 ModelForge，您可以轻松地加载、运行和切换不同的模型，所有这些都通过用户友好的界面完成。</p>
        <p>主要功能：</p>
        <ul>
            <li>加载和运行多个模型</li>
            <li>无缝切换不同模型</li>
            <li>高效管理资源</li>
            <li>用户友好的图形界面</li>
        </ul>
        <p>感谢您使用 ModelForge 1.0！</p>
        <p>版本：1.0.0</p>
        <p>构建时间：2024-01-01</p>
        <p>许可证：MIT</p>
        <p><a href='https://github.com/modelforge'>访问项目主页</a></p>
    """
    icon_path: str = ""
    icon_size: int = 128
    
    def __post_init__(self):
        """验证配置参数"""
        try:
            # 通过安全的方式获取应用配置
            if hasattr(config_manager, 'app_config'):
                self.title = f"关于 {config_manager.app_config.project_name} {config_manager.app_config.version}"
                self.app_name = f"{config_manager.app_config.project_name} {config_manager.app_config.version}"
                
                # 如果有图标路径，则使用它
                if hasattr(config_manager.app_config, 'icon_paths') and 'transition' in config_manager.app_config.icon_paths:
                    self.icon_path = config_manager.app_config.icon_paths["transition"]
            
            # 验证必要的字段
            if not self.title:
                self.title = "关于 ModelForge"
            if not self.app_name:
                self.app_name = "ModelForge"
            if not self.description:
                self.description = "<p>ModelForge 是一个模型管理工具</p>"
            if self.icon_size <= 0:
                self.icon_size = 128
        except Exception as e:
            logger.error(f"关于对话框信息验证失败: {str(e)}")
            # 设置默认值
            self.title = "关于 ModelForge"
            self.app_name = "ModelForge"
            self.description = "<p>ModelForge 是一个模型管理工具</p>"
            self.icon_size = 128

class AboutDialog(QDialog):
    """关于对话框"""
    
    def __init__(self, parent=None, info: Optional[AboutInfo] = None):
        """
        初始化关于对话框
        
        Args:
            parent: 父窗口
            info: 关于对话框信息
        """
        try:
            super().__init__(parent)
            self.info = info or AboutInfo()
            self._setup_ui()
            logger.debug("关于对话框初始化完成")
        except Exception as e:
            logger.error(f"关于对话框初始化失败: {str(e)}")
            raise
        
    def _setup_ui(self):
        """设置UI组件"""
        try:
            self.setWindowTitle(self.info.title)
            self.setMinimumWidth(500)
            self.setMinimumHeight(600)
            
            # 创建主布局
            main_layout = QVBoxLayout()
            main_layout.setSpacing(20)
            main_layout.setContentsMargins(20, 20, 20, 20)
            
            # 创建滚动区域
            scroll_area = QScrollArea(self)
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            
            # 创建内容部件
            content_widget = QWidget()
            content_layout = QVBoxLayout(content_widget)
            content_layout.setSpacing(20)
            content_layout.setContentsMargins(0, 0, 0, 0)
            
            # 添加图标
            if self.info.icon_path:
                content_layout.addWidget(self._create_icon_label())
            
            # 添加标题
            content_layout.addWidget(self._create_title_label())
            
            # 添加描述
            content_layout.addWidget(self._create_description_label())
            
            # 设置滚动区域的部件
            scroll_area.setWidget(content_widget)
            
            # 添加滚动区域到主布局
            main_layout.addWidget(scroll_area)
            
            # 添加按钮布局
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            button_layout.addWidget(self._create_close_button())
            main_layout.addLayout(button_layout)
            
            self.setLayout(main_layout)
            logger.debug("关于对话框UI初始化完成")
            
        except Exception as e:
            logger.error(f"关于对话框UI初始化失败: {str(e)}")
            raise
            
    def _create_icon_label(self) -> QLabel:
        """
        创建图标标签
        
        Returns:
            图标标签
        """
        try:
            icon_label = QLabel(self)
            pixmap = QPixmap(self.info.icon_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    self.info.icon_size,
                    self.info.icon_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                icon_label.setPixmap(pixmap)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return icon_label
        except Exception as e:
            logger.error(f"创建图标标签失败: {str(e)}")
            return QLabel(self)  # 返回空标签
            
    def _create_title_label(self) -> QLabel:
        """
        创建标题标签
        
        Returns:
            标题标签
        """
        try:
            title_label = QLabel(f"<h1>{self.info.app_name}</h1>", self)
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("QLabel { color: #2c3e50; }")
            return title_label
        except Exception as e:
            logger.error(f"创建标题标签失败: {str(e)}")
            return QLabel("<h1>ModelForge</h1>", self)
            
    def _create_description_label(self) -> QLabel:
        """
        创建描述标签
        
        Returns:
            描述标签
        """
        try:
            description_label = QLabel(self.info.description, self)
            description_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            description_label.setWordWrap(True)
            description_label.setOpenExternalLinks(True)
            description_label.setStyleSheet("""
                QLabel {
                    line-height: 150%;
                    color: #34495e;
                }
                QLabel a {
                    color: #3498db;
                    text-decoration: none;
                }
                QLabel a:hover {
                    color: #2980b9;
                    text-decoration: underline;
                }
            """)
            return description_label
        except Exception as e:
            logger.error(f"创建描述标签失败: {str(e)}")
            return QLabel("<p>ModelForge 是一个强大的模型管理工具</p>", self)
            
    def _create_close_button(self) -> QPushButton:
        """
        创建关闭按钮
        
        Returns:
            关闭按钮
        """
        try:
            close_button = QPushButton("关闭", self)
            close_button.clicked.connect(self.close)
            close_button.setFixedWidth(100)
            close_button.setStyleSheet("""
                QPushButton {
                    padding: 8px;
                    background-color: #2980b9;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #3498db;
                }
                QPushButton:pressed {
                    background-color: #2472a4;
                }
            """)
            return close_button
        except Exception as e:
            logger.error(f"创建关闭按钮失败: {str(e)}")
            btn = QPushButton("关闭", self)
            btn.clicked.connect(self.close)
            return btn

class HelpMenu(QMenu):
    """帮助菜单"""
    
    def __init__(self, parent=None, main_window=None):
        """初始化帮助菜单"""
        try:
            super().__init__("帮助(&H)", parent)
            self.main_window = main_window
            self._setup_actions()
            logger.debug("帮助菜单初始化完成")
        except Exception as e:
            logger.error(f"帮助菜单初始化失败: {str(e)}")
    
    def _setup_actions(self):
        """设置菜单动作"""
        try:

            
            # 文档
            self.docs_action = QAction("文档(&D)", self)
            self.docs_action.triggered.connect(self._open_docs)
            self.addAction(self.docs_action)
            
            # 分隔线
            self.addSeparator()
            
            # 检查更新
            self.update_action = QAction("检查更新(&U)", self)
            self.update_action.triggered.connect(self._check_update)
            self.addAction(self.update_action)
            
            # 分隔线
            self.addSeparator()
            # 关于
            self.about_action = QAction("关于(&A)", self)
            self.about_action.triggered.connect(self._show_about)
            self.addAction(self.about_action)

            
            logger.debug("帮助菜单设置完成")
        except Exception as e:
            logger.error(f"帮助菜单设置失败: {str(e)}")
    
    @Slot()
    def _show_about(self):
        """显示关于对话框"""
        try:
            # 安全地获取项目信息
            project_name = config_manager.app_config.project_name
            version = config_manager.app_config.version
            
            if hasattr(config_manager, 'app_config'):
                project_name = config_manager.app_config.project_name
                version = config_manager.app_config.version
                
            about_text = f"""
            <h2>{project_name} v{version}</h2>
            <p>一个强大的AI模型应用平台</p>
            <p>作者: {config_manager.app_config.author}</p>
            <p>网址: {config_manager.app_config.url}</p>
            <p>&copy; 2023-2024 All Rights Reserved</p>
            """
            QMessageBox.about(self, f"关于 {project_name}", about_text)
            logger.debug("显示关于对话框")
        except Exception as e:
            logger.error(f"显示关于对话框失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"显示关于对话框失败: {str(e)}")
    
    @Slot()
    def _open_docs(self):
        """打开文档"""
        try:
            # 这里需要实现打开文档功能
            QMessageBox.information(self, "提示", "文档功能正在开发中")
            logger.debug("打开文档（功能开发中）")
        except Exception as e:
            logger.error(f"打开文档失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"打开文档失败: {str(e)}")
    
    @Slot()
    def _check_update(self):
        """检查更新"""
        try:
            # 这里需要实现检查更新功能
            QMessageBox.information(self, "提示", "检查更新功能正在开发中")
            logger.debug("检查更新（功能开发中）")
        except Exception as e:
            logger.error(f"检查更新失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"检查更新失败: {str(e)}")
