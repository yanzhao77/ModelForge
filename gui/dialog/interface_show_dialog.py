from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox
)

from .base_dialog import BaseDialog, DialogConfig
from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class Message:
    """消息数据类"""
    role: str
    content: str

@dataclass
class InterfaceShowData:
    """接口显示数据类"""
    name: str = ""
    type: str = ""
    api_key: str = ""
    base_url: str = ""
    proxy: str = ""
    timeout: int = 30
    messages: List[Message] = field(default_factory=list)

class AddMessageDialog(BaseDialog):
    """添加消息对话框"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        config = DialogConfig(
            title="添加消息",
            width=400,
            height=300,
            resizable=False
        )
        super().__init__(parent, config)
        
    def _create_content(self):
        """创建内容区域"""
        try:
            # 创建表单布局
            form_layout = QFormLayout()
            
            # 创建输入控件
            self.role_input = QLineEdit()
            self.content_input = QTextEdit()
            
            # 添加到布局
            form_layout.addRow("角色:", self.role_input)
            form_layout.addRow("内容:", self.content_input)
            
            # 添加到主布局
            self.main_layout.addLayout(form_layout)
            
            logger.debug("添加消息对话框内容创建完成")
        except Exception as e:
            logger.error(f"创建添加消息对话框内容失败: {str(e)}")
            raise
            
    def validate(self) -> bool:
        """验证数据"""
        try:
            if not self.role_input.text().strip():
                self.show_error("验证失败", "角色不能为空")
                return False
                
            if not self.content_input.toPlainText().strip():
                self.show_error("验证失败", "内容不能为空")
                return False
                
            return True
        except Exception as e:
            logger.error(f"验证数据失败: {str(e)}")
            return False
            
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        return {
            "role": self.role_input.text().strip(),
            "content": self.content_input.toPlainText().strip()
        }
        
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        try:
            self.role_input.setText(data.get("role", ""))
            self.content_input.setText(data.get("content", ""))
        except Exception as e:
            logger.error(f"设置数据失败: {str(e)}")
            raise

class InterfaceShowDialog(BaseDialog):
    """接口显示对话框"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        config = DialogConfig(
            title="接口详情",
            width=800,
            height=600
        )
        super().__init__(parent, config)
        
        # 初始化数据
        self.data = InterfaceShowData()
        
    def _create_content(self):
        """创建内容区域"""
        try:
            # 创建基本信息区域
            self._create_basic_info()
            
            # 创建消息列表区域
            self._create_message_list()
            
            logger.debug("接口显示对话框内容创建完成")
        except Exception as e:
            logger.error(f"创建接口显示对话框内容失败: {str(e)}")
            raise
            
    def _create_basic_info(self):
        """创建基本信息区域"""
        try:
            # 创建表单布局
            form_layout = QFormLayout()
            
            # 创建输入控件
            self.name_input = QLineEdit()
            self.type_input = QLineEdit()
            self.api_key_input = QLineEdit()
            self.base_url_input = QLineEdit()
            self.proxy_input = QLineEdit()
            self.timeout_input = QLineEdit()
            
            # 设置属性
            self.api_key_input.setEchoMode(QLineEdit.Password)
            self.timeout_input.setValidator(QIntValidator(1, 3600))
            
            # 添加到布局
            form_layout.addRow("名称:", self.name_input)
            form_layout.addRow("类型:", self.type_input)
            form_layout.addRow("API密钥:", self.api_key_input)
            form_layout.addRow("基础URL:", self.base_url_input)
            form_layout.addRow("代理:", self.proxy_input)
            form_layout.addRow("超时(秒):", self.timeout_input)
            
            # 添加到主布局
            self.main_layout.addLayout(form_layout)
            
            logger.debug("基本信息区域创建完成")
        except Exception as e:
            logger.error(f"创建基本信息区域失败: {str(e)}")
            raise
            
    def _create_message_list(self):
        """创建消息列表区域"""
        try:
            # 创建消息列表标题
            title_layout = QHBoxLayout()
            title_label = QLabel("消息列表")
            title_layout.addWidget(title_label)
            title_layout.addStretch()
            
            # 创建按钮
            add_button = QPushButton("添加")
            edit_button = QPushButton("编辑")
            delete_button = QPushButton("删除")
            copy_button = QPushButton("复制")
            
            # 添加按钮到布局
            title_layout.addWidget(add_button)
            title_layout.addWidget(edit_button)
            title_layout.addWidget(delete_button)
            title_layout.addWidget(copy_button)
            
            # 创建表格
            self.message_table = QTableWidget()
            self.message_table.setColumnCount(2)
            self.message_table.setHorizontalHeaderLabels(["角色", "内容"])
            self.message_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            
            # 连接信号
            add_button.clicked.connect(self._add_message)
            edit_button.clicked.connect(self._edit_message)
            delete_button.clicked.connect(self._delete_message)
            copy_button.clicked.connect(self._copy_message)
            
            # 添加到主布局
            self.main_layout.addLayout(title_layout)
            self.main_layout.addWidget(self.message_table)
            
            logger.debug("消息列表区域创建完成")
        except Exception as e:
            logger.error(f"创建消息列表区域失败: {str(e)}")
            raise
            
    def _add_message(self):
        """添加消息"""
        try:
            dialog = AddMessageDialog(self)
            if dialog.exec_():
                data = dialog.get_data()
                row = self.message_table.rowCount()
                self.message_table.insertRow(row)
                self.message_table.setItem(row, 0, QTableWidgetItem(data["role"]))
                self.message_table.setItem(row, 1, QTableWidgetItem(data["content"]))
                logger.debug(f"添加消息成功: {data}")
        except Exception as e:
            logger.error(f"添加消息失败: {str(e)}")
            self.show_error("添加失败", str(e))
            
    def _edit_message(self):
        """编辑消息"""
        try:
            current_row = self.message_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要编辑的消息")
                return
                
            # 获取当前数据
            role = self.message_table.item(current_row, 0).text()
            content = self.message_table.item(current_row, 1).text()
            
            # 创建编辑对话框
            dialog = AddMessageDialog(self)
            dialog.set_data({"role": role, "content": content})
            
            if dialog.exec_():
                data = dialog.get_data()
                self.message_table.setItem(current_row, 0, QTableWidgetItem(data["role"]))
                self.message_table.setItem(current_row, 1, QTableWidgetItem(data["content"]))
                logger.debug(f"编辑消息成功: {data}")
        except Exception as e:
            logger.error(f"编辑消息失败: {str(e)}")
            self.show_error("编辑失败", str(e))
            
    def _delete_message(self):
        """删除消息"""
        try:
            current_row = self.message_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要删除的消息")
                return
                
            if self.show_question("确认", "确定要删除选中的消息吗?"):
                self.message_table.removeRow(current_row)
                logger.debug(f"删除消息成功: row={current_row}")
        except Exception as e:
            logger.error(f"删除消息失败: {str(e)}")
            self.show_error("删除失败", str(e))
            
    def _copy_message(self):
        """复制消息"""
        try:
            current_row = self.message_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要复制的消息")
                return
                
            # 获取当前数据
            role = self.message_table.item(current_row, 0).text()
            content = self.message_table.item(current_row, 1).text()
            
            # 添加新行
            row = self.message_table.rowCount()
            self.message_table.insertRow(row)
            self.message_table.setItem(row, 0, QTableWidgetItem(role))
            self.message_table.setItem(row, 1, QTableWidgetItem(content))
            
            logger.debug(f"复制消息成功: from={current_row}, to={row}")
        except Exception as e:
            logger.error(f"复制消息失败: {str(e)}")
            self.show_error("复制失败", str(e))
            
    def validate(self) -> bool:
        """验证数据"""
        try:
            if not self.name_input.text().strip():
                self.show_error("验证失败", "名称不能为空")
                return False
                
            if not self.type_input.text().strip():
                self.show_error("验证失败", "类型不能为空")
                return False
                
            if not self.api_key_input.text().strip():
                self.show_error("验证失败", "API密钥不能为空")
                return False
                
            if not self.base_url_input.text().strip():
                self.show_error("验证失败", "基础URL不能为空")
                return False
                
            timeout_text = self.timeout_input.text().strip()
            if not timeout_text or not timeout_text.isdigit():
                self.show_error("验证失败", "超时必须是有效的数字")
                return False
                
            return True
        except Exception as e:
            logger.error(f"验证数据失败: {str(e)}")
            return False
            
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        try:
            # 获取基本信息
            data = {
                "name": self.name_input.text().strip(),
                "type": self.type_input.text().strip(),
                "api_key": self.api_key_input.text().strip(),
                "base_url": self.base_url_input.text().strip(),
                "proxy": self.proxy_input.text().strip(),
                "timeout": int(self.timeout_input.text().strip()),
                "messages": []
            }
            
            # 获取消息列表
            for row in range(self.message_table.rowCount()):
                message = {
                    "role": self.message_table.item(row, 0).text(),
                    "content": self.message_table.item(row, 1).text()
                }
                data["messages"].append(message)
                
            return data
        except Exception as e:
            logger.error(f"获取数据失败: {str(e)}")
            raise
            
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        try:
            # 设置基本信息
            self.name_input.setText(data.get("name", ""))
            self.type_input.setText(data.get("type", ""))
            self.api_key_input.setText(data.get("api_key", ""))
            self.base_url_input.setText(data.get("base_url", ""))
            self.proxy_input.setText(data.get("proxy", ""))
            self.timeout_input.setText(str(data.get("timeout", 30)))
            
            # 设置消息列表
            self.message_table.setRowCount(0)
            for message in data.get("messages", []):
                row = self.message_table.rowCount()
                self.message_table.insertRow(row)
                self.message_table.setItem(row, 0, QTableWidgetItem(message["role"]))
                self.message_table.setItem(row, 1, QTableWidgetItem(message["content"]))
                
            logger.debug("数据设置完成")
        except Exception as e:
            logger.error(f"设置数据失败: {str(e)}")
            raise
