import copy
import sys
import time
from typing import Dict, Optional, List, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto

import markdown
from PySide6.QtCore import Qt, QThreadPool, Slot, Signal, QSize
from PySide6.QtGui import QTextCursor, QFont, QTextCharFormat, QColor, QFontMetrics
from PySide6.QtWidgets import (
    QSplitter, QVBoxLayout, QWidget, QProgressBar, 
    QMessageBox, QApplication
)

from common.baseCustom.Custom import CustomOutput, CustomInput, InputConfig, TextAreaConfig
from common.baseCustom.ui_service import ModelLauncher, ModelLaunchConfig
from common.const.common_const import LoggerNames, get_logger
from gui.QTextArea import QTextArea
from gui.tree_view.radio_layout import RadioLayout

logger = get_logger(LoggerNames.UI)

class MessageType(Enum):
    """消息类型"""
    USER = auto()
    MODEL = auto()
    SYSTEM = auto()
    ERROR = auto()

@dataclass
class Message:
    """消息数据类"""
    type: MessageType
    content: str
    sender: str = ""
    timestamp: float = field(default_factory=lambda: time.time())

@dataclass
class TextAreaState:
    """文本区域状态数据类"""
    messages: Dict[str, List[Message]] = field(default_factory=dict)
    model_dict: Dict[str, Any] = field(default_factory=dict)
    current_model: Optional[Any] = None
    font_size: int = 10
    max_history: int = 1000
    auto_scroll: bool = True
    
    def add_message(self, model_key: str, message: Message) -> None:
        """添加消息到历史记录"""
        if model_key not in self.messages:
            self.messages[model_key] = []
        
        messages = self.messages[model_key]
        messages.append(message)
        
        # 限制历史记录大小
        if len(messages) > self.max_history:
            messages.pop(0)
    
    def clear_messages(self, model_key: Optional[str] = None) -> None:
        """清空消息历史"""
        if model_key:
            self.messages.pop(model_key, None)
        else:
            self.messages.clear()

class TextArea(QWidget):
    # 定义信号
    message_received = Signal(str)
    model_loaded = Signal(str)
    error_occurred = Signal(str)
    state_changed = Signal()

    def __init__(self):
        """初始化文本区域"""
        try:
            super().__init__()
            self.state = TextAreaState()
            self._init_ui()
            self._setup_thread_pool()
            self._setup_io_redirection()
            logger.info("文本区域初始化完成")
        except Exception as e:
            logger.error(f"文本区域初始化失败: {str(e)}")
            raise

    def _init_ui(self) -> None:
        """初始化UI组件"""
        try:
            # 创建布局
            self.layout = QVBoxLayout()
            self.setLayout(self.layout)
            self.layout.setContentsMargins(5, 5, 5, 5)
            self.layout.setSpacing(5)

            # 创建并配置文本显示区域
            self.display_text_area = self._create_text_area(True)
            self.input_line_edit = self._create_text_area(False)
            self._setup_text_areas()

            # 创建分割器
            self.splitter = self._create_splitter()

            # 创建单选按钮布局
            self.radio_layout = RadioLayout(self)

            # 添加组件到主布局
            self.layout.addWidget(self.splitter)
            self.layout.addWidget(self.radio_layout)

            # 连接信号
            self._connect_signals()
            
        except Exception as e:
            logger.error(f"UI初始化失败: {str(e)}")
            raise

    def _create_text_area(self, read_only: bool = False) -> QTextArea:
        """创建文本区域"""
        try:
            text_area = QTextArea()
            text_area.setReadOnly(read_only)
            text_area.setFont(self._get_default_font())
            return text_area
        except Exception as e:
            logger.error(f"创建文本区域失败: {str(e)}")
            raise

    def _setup_text_areas(self) -> None:
        """配置文本区域"""
        try:
            # 配置输入区域
            self.input_line_edit.setPlaceholderText("请输入...")
            self.input_line_edit.setMinimumHeight(50)
            self.input_line_edit.setMaximumHeight(100)
            
            # 配置显示区域
            self.display_text_area.setMinimumHeight(200)
            self.display_text_area.setLineWrapMode(QTextArea.LineWrapMode.WidgetWidth)
            
            # 应用样式
            self._apply_text_area_styles()
            
        except Exception as e:
            logger.error(f"配置文本区域失败: {str(e)}")
            raise

    def _create_splitter(self) -> QSplitter:
        """创建分割器"""
        try:
            splitter = QSplitter(Qt.Orientation.Vertical)
            splitter.addWidget(self.display_text_area)
            splitter.addWidget(self.input_line_edit)
            splitter.setSizes([350, 50])
            return splitter
        except Exception as e:
            logger.error(f"创建分割器失败: {str(e)}")
            raise

    def _get_default_font(self) -> QFont:
        """获取默认字体"""
        try:
            font = QFont("Microsoft YaHei", self.state.font_size)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            return font
        except Exception as e:
            logger.error(f"获取默认字体失败: {str(e)}")
            return QFont()

    def _apply_text_area_styles(self) -> None:
        """应用文本区域样式"""
        try:
            style = """
                QTextEdit {
                    background-color: white;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 5px;
                }
                QTextEdit:focus {
                    border-color: #66afe9;
                    outline: 0;
                    box-shadow: inset 0 1px 1px rgba(0,0,0,.075),0 0 8px rgba(102,175,233,.6);
                }
            """
            self.display_text_area.setStyleSheet(style)
            self.input_line_edit.setStyleSheet(style)
        except Exception as e:
            logger.error(f"应用样式失败: {str(e)}")

    def _connect_signals(self) -> None:
        """连接信号"""
        try:
            self.input_line_edit.submitTextSignal.connect(self._handle_submit)
            self.message_received.connect(self._handle_message)
            self.error_occurred.connect(self._handle_error)
            self.state_changed.connect(self._handle_state_change)
        except Exception as e:
            logger.error(f"连接信号失败: {str(e)}")
            raise

    def _setup_thread_pool(self) -> None:
        """设置线程池"""
        try:
            self.thread_pool = QThreadPool()
            self.thread_pool.setMaxThreadCount(4)  # 限制最大线程数
            self.progress_bar: Optional[QProgressBar] = None
        except Exception as e:
            logger.error(f"设置线程池失败: {str(e)}")
            raise

    def _setup_io_redirection(self) -> None:
        """设置输入输出重定向"""
        try:
            sys.stdout = CustomOutput(TextAreaConfig(self.display_text_area))
            sys.stdin = CustomInput(InputConfig(self.input_line_edit))
        except Exception as e:
            logger.error(f"设置IO重定向失败: {str(e)}")
            raise

    @Slot()
    def _handle_submit(self) -> None:
        """处理提交事件"""
        text = self.input_line_edit.toPlainText().strip()
        if not text:
            return

        try:
            if not self.state.current_model:
                raise ValueError("未选择模型")

            if self.progress_bar:
                self.progress_bar.setVisible(True)
            
            # 添加用户消息
            message = Message(
                type=MessageType.USER,
                content=text,
                sender="user"
            )
            self.state.add_message(str(self.state.current_model), message)
            self.append_you(text)
            
            # 启动模型处理
            # ModelLauncher(ModelLaunchConfig())
            model_lunch = ui_model_run(text, self.state.current_model, self)
            self.thread_pool.start(model_lunch)
            self.clear_input()

        except Exception as e:
            logger.error(f"提交处理失败: {str(e)}")
            self.error_occurred.emit(str(e))

    @Slot(str)
    def _handle_message(self, message: str) -> None:
        """处理接收到的消息"""
        try:
            if not message.strip():
                return
                
            # 添加模型消息
            msg = Message(
                type=MessageType.MODEL,
                content=message,
                sender=str(self.state.current_model)
            )
            self.state.add_message(str(self.state.current_model), msg)
            self.print(message)
            
        except Exception as e:
            logger.error(f"消息处理失败: {str(e)}")
            self.error_occurred.emit(str(e))

    @Slot(str)
    def _handle_error(self, error: str) -> None:
        """处理错误"""
        try:
            logger.error(f"发生错误: {error}")
            
            # 添加错误消息
            msg = Message(
                type=MessageType.ERROR,
                content=error,
                sender="system"
            )
            if self.state.current_model:
                self.state.add_message(str(self.state.current_model), msg)
            
            # 显示错误消息
            self._append_styled_text(
                "错误: ", 11, True, 
                Qt.GlobalColor.red, error
            )
            
            # 显示错误对话框
            QMessageBox.critical(self, "错误", error)
            
        except Exception as e:
            logger.error(f"错误处理失败: {str(e)}")

    @Slot()
    def _handle_state_change(self) -> None:
        """处理状态变化"""
        try:
            self._toggle_model_messages()
        except Exception as e:
            logger.error(f"状态变化处理失败: {str(e)}")

    def set_model_name(self, model_name: str) -> None:
        """设置模型名称"""
        try:
            if not model_name:
                raise ValueError("模型名称不能为空")
                
            if self.state.current_model:
                self.state.current_model.model_name = model_name
                self.state.model_dict[model_name] = self.state.current_model
                self.model_loaded.emit(model_name)
                logger.info(f"模型名称已设置: {model_name}")
                
        except Exception as e:
            logger.error(f"设置模型名称失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def select_model(self, model_name: str) -> None:
        """选择模型"""
        try:
            if not model_name:
                raise ValueError("模型名称不能为空")
                
            if model_name in self.state.model_dict:
                self.state.current_model = self.state.model_dict[model_name]
                self.state_changed.emit()
                logger.info(f"已选择模型: {model_name}")
            else:
                raise ValueError(f"模型不存在: {model_name}")
                
        except Exception as e:
            logger.error(f"选择模型失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def get_model(self, model_name: str) -> Optional[Any]:
        """获取模型"""
        try:
            return self.state.model_dict.get(model_name)
        except Exception as e:
            logger.error(f"获取模型失败: {str(e)}")
            return None

    @Slot()
    def loading_model(self, models_parameters: dict) -> None:
        """加载模型"""
        try:
            if not models_parameters:
                raise ValueError("模型参数不能为空")
                
            self.radio_layout.setVisible(True)
            self.clear_output()
            
            model_run = ui_model_lunch(models_parameters, self)
            self.thread_pool.start(model_run)
            logger.info("开始加载模型")
            
        except Exception as e:
            logger.error(f"模型加载失败: {str(e)}")
            self.error_occurred.emit(str(e))

    @Slot()
    def loading_interface(self, models_parameters: dict) -> None:
        """加载接口"""
        try:
            if not models_parameters:
                raise ValueError("接口参数不能为空")
                
            self.radio_layout.hide()
            self.clear_output()
            
            model_run = ui_model_lunch(models_parameters, self)
            self.thread_pool.start(model_run)
            logger.info("开始加载接口")
            
        except Exception as e:
            logger.error(f"接口加载失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def print(self, text: str) -> None:
        """打印文本"""
        if not text.strip():
            return
            
        try:
            self.display_text_area.append("")
            html_content = markdown.markdown(
                text,
                extensions=['fenced_code', 'tables']
            )
            cursor = self.display_text_area.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertHtml(html_content)
            
            if self.state.auto_scroll:
                self.display_text_area.setTextCursor(cursor)
                
        except Exception as e:
            logger.error(f"打印失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def _append_styled_text(
        self, 
        prefix: str, 
        size: int, 
        bold: bool, 
        color: Qt.GlobalColor, 
        text: str
    ) -> None:
        """添加带样式的文本"""
        try:
            self.display_text_area.append("")
            cursor = self.display_text_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)

            # 设置前缀样式
            format_prefix = QTextCharFormat()
            format_prefix.setFontPointSize(size)
            format_prefix.setFontWeight(
                QFont.Weight.Bold if bold else QFont.Weight.Normal
            )
            format_prefix.setForeground(QColor(color))
            cursor.insertText(prefix, format_prefix)

            # 设置文本样式
            format_text = QTextCharFormat()
            format_text.setFontPointSize(self.state.font_size)
            format_text.setFontWeight(QFont.Weight.Normal)
            format_text.setForeground(QColor(Qt.GlobalColor.black))
            cursor.insertText(text, format_text)

            if self.state.auto_scroll:
                self.display_text_area.setTextCursor(cursor)

        except Exception as e:
            logger.error(f"添加样式文本失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def append_you(self, text: str) -> None:
        """添加用户消息"""
        self._append_styled_text(
            "user:  ", 11, True, 
            Qt.GlobalColor.blue, text
        )

    def append_model(self, model_name: str = "model", text: str = "") -> None:
        """添加模型消息"""
        self._append_styled_text(
            f"{model_name}:  ", 11, True,
            Qt.GlobalColor.blue, text
        )

    def _toggle_model_messages(self) -> None:
        """切换模型消息显示"""
        try:
            self.clear_output()
            
            if not self.state.current_model:
                return
                
            model_key = str(self.state.current_model)
            if model_key not in self.state.messages:
                return
                
            for message in self.state.messages[model_key]:
                if message.type == MessageType.USER:
                    self.append_you(message.content)
                elif message.type == MessageType.MODEL:
                    self.append_model(message.sender, message.content)
                elif message.type == MessageType.ERROR:
                    self._append_styled_text(
                        "错误: ", 11, True,
                        Qt.GlobalColor.red, message.content
                    )
                    
        except Exception as e:
            logger.error(f"切换模型消息显示失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def input(self, text: str) -> None:
        """设置输入文本"""
        try:
            self.input_line_edit.setText(text)
        except Exception as e:
            logger.error(f"设置输入文本失败: {str(e)}")

    def get_input_text(self) -> str:
        """获取输入文本"""
        try:
            return self.input_line_edit.toPlainText()
        except Exception as e:
            logger.error(f"获取输入文本失败: {str(e)}")
            return ""

    def clear_input(self) -> None:
        """清空输入区域"""
        try:
            self.input_line_edit.clear()
        except Exception as e:
            logger.error(f"清空输入区域失败: {str(e)}")

    def clear_output(self) -> None:
        """清空输出区域"""
        try:
            self.display_text_area.clear()
        except Exception as e:
            logger.error(f"清空输出区域失败: {str(e)}")

    def clear(self) -> None:
        """清空所有区域"""
        try:
            self.clear_input()
            self.clear_output()
            self.state.clear_messages()
        except Exception as e:
            logger.error(f"清空所有区域失败: {str(e)}")

    def check_models_parameters(self, models_parameters: dict) -> bool:
        """检查模型参数"""
        try:
            return bool(models_parameters)
        except Exception as e:
            logger.error(f"检查模型参数失败: {str(e)}")
            return False

    def stop_model(self) -> None:
        """停止模型"""
        try:
            if self.state.current_model:
                self.state.current_model.stop()
                logger.info("模型已停止")
        except Exception as e:
            logger.error(f"停止模型失败: {str(e)}")
            self.error_occurred.emit(str(e))

    def set_font_size(self, size: int) -> None:
        """设置字体大小"""
        try:
            if 8 <= size <= 72:
                self.state.font_size = size
                font = self._get_default_font()
                self.display_text_area.setFont(font)
                self.input_line_edit.setFont(font)
                logger.info(f"字体大小已设置为: {size}")
        except Exception as e:
            logger.error(f"设置字体大小失败: {str(e)}")

    def set_auto_scroll(self, enabled: bool) -> None:
        """设置自动滚动"""
        try:
            self.state.auto_scroll = enabled
            logger.info(f"自动滚动已{'启用' if enabled else '禁用'}")
        except Exception as e:
            logger.error(f"设置自动滚动失败: {str(e)}")

    def set_max_history(self, count: int) -> None:
        """设置最大历史记录数"""
        try:
            if count > 0:
                self.state.max_history = count
                logger.info(f"最大历史记录数已设置为: {count}")
        except Exception as e:
            logger.error(f"设置最大历史记录数失败: {str(e)}")
