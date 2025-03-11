from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QTableWidgetItem, QHeaderView
)

from .base_table_dialog import BaseTableDialog, TableConfig, DialogConfig
from common.const.common_const import LoggerNames, get_logger, common_const, model_enum

logger = get_logger(LoggerNames.UI)

@dataclass
class InterfaceOpenData:
    """接口打开数据类"""
    interface_name: str = ""
    model_name: str = ""
    interfaces: Dict[str, Dict[str, str]] = field(default_factory=dict)

class InterfaceOpenDialog(BaseTableDialog):
    """接口打开对话框"""
    
    def __init__(
        self, 
        parent: Optional[QWidget] = None,
        interface_parameters: Optional[Dict[str, Any]] = None
    ):
        # 创建对话框配置
        dialog_config = DialogConfig(
            title="打开接口",
            width=600,
            height=400,
            resizable=True
        )
        
        # 创建表格配置
        table_config = TableConfig(
            headers=["接口名称", "模型名称"],
            column_stretches=[
                QHeaderView.ResizeToContents,
                QHeaderView.Stretch
            ],
            enable_context_menu=False,
            enable_search=True,
            enable_multi_select=False,
            enable_edit=False
        )
        
        super().__init__(parent, dialog_config, table_config)
        
        # 初始化数据
        self.data = InterfaceOpenData()
        
        # 处理接口参数
        if interface_parameters:
            self._process_interface_parameters(interface_parameters)
            
        # 连接双击信号
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        
    def _process_interface_parameters(self, parameters: Dict[str, Any]):
        """处理接口参数"""
        try:
            # 清空接口字典
            self.data.interfaces.clear()
            
            # 遍历参数
            for item in parameters.values():
                if item[common_const.model_type] == model_enum.interface:
                    self.data.interfaces[item[common_const.model_name]] = {
                        "name": item[common_const.model_name],
                        "type": item[common_const.model_type_name]
                    }
                    
            # 更新表格数据
            self._update_interface_table()
            
            logger.debug(f"处理接口参数完成: {len(self.data.interfaces)}个接口")
        except Exception as e:
            logger.error(f"处理接口参数失败: {str(e)}")
            raise
            
    def _update_interface_table(self):
        """更新接口表格"""
        try:
            # 准备表格数据
            table_data = []
            for interface_name, interface_data in self.data.interfaces.items():
                table_data.append([
                    interface_name,
                    interface_data["type"]
                ])
                
            # 设置表格数据
            self.set_table_data(table_data)
            
            logger.debug("接口表格更新完成")
        except Exception as e:
            logger.error(f"更新接口表格失败: {str(e)}")
            
    @Slot(QTableWidgetItem)
    def _on_item_double_clicked(self, item: QTableWidgetItem):
        """处理双击事件"""
        try:
            self.accept()
            logger.debug("接受双击选择")
        except Exception as e:
            logger.error(f"处理双击事件失败: {str(e)}")
            
    def validate(self) -> bool:
        """验证数据"""
        try:
            # 检查是否选择了接口
            current_row = self.get_current_row()
            if current_row < 0:
                self.show_error("验证失败", "请选择要打开的接口")
                return False
                
            return True
        except Exception as e:
            logger.error(f"验证数据失败: {str(e)}")
            return False
            
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        try:
            # 获取选中的行
            current_row = self.get_current_row()
            if current_row >= 0:
                interface_name = self.get_cell_data(current_row, 0)
                model_name = self.get_cell_data(current_row, 1)
                
                return {
                    "interface_name": interface_name,
                    "model_name": model_name
                }
            return {}
        except Exception as e:
            logger.error(f"获取数据失败: {str(e)}")
            raise
            
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        try:
            # 设置选中的接口
            interface_name = data.get("interface_name", "")
            if interface_name:
                items = self.table.findItems(interface_name, Qt.MatchExactly)
                if items:
                    self.table.setCurrentItem(items[0])
                    
            logger.debug("数据设置完成")
        except Exception as e:
            logger.error(f"设置数据失败: {str(e)}")
            raise
            
    def get_selected_interface(self) -> str:
        """获取选中的接口名称"""
        try:
            current_row = self.get_current_row()
            if current_row >= 0:
                return self.get_cell_data(current_row, 1)
            return ""
        except Exception as e:
            logger.error(f"获取选中接口失败: {str(e)}")
            return ""
