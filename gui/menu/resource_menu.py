from dataclasses import dataclass
from typing import Dict, Any, Optional

from PySide6.QtWidgets import QMenu

from common.const.common_const import LoggerNames, get_logger
from .base_menu import BaseMenu

logger = get_logger(LoggerNames.UI)

@dataclass
class ResourceParameters:
    """资源参数基类"""
    model_name: str
    model_type: str
    parameters_editable: bool = True

class ResourceMenu(BaseMenu):
    """资源菜单基类，用于处理模型和接口的共同功能"""
    
    def __init__(self, menu_bar, main_window, title: str):
        super().__init__(menu_bar, main_window, title)
        self.main_window = main_window
        self.parameters = None
        self.recent_menu: Optional[QMenu] = None
        
    def _setup_menu(self):
        """设置菜单项"""
        try:
            # 基本操作
            self._add_basic_actions()
            
            # 最近列表子菜单
            self.recent_menu = self.add_submenu("recent list","最近列表")
            self.add_separator()
            
            # 添加其他操作
            self._add_additional_actions()
            
            logger.info(f"{self.__class__.__name__} 初始化完成")
        except Exception as e:
            logger.error(f"设置 {self.__class__.__name__} 失败: {str(e)}")
            raise
            
    def _add_basic_actions(self):
        """添加基本操作"""
        pass
        
    def _add_additional_actions(self):
        """添加额外操作"""
        pass
        
    def clear_resource_list(self):
        """清空资源列表"""
        try:
            self.main_window.clear_ui()
            if self.recent_menu:
                self.recent_menu.clear()
            logger.info(f"已清空 {self.__class__.__name__} 列表")
        except Exception as e:
            logger.error(f"清空 {self.__class__.__name__} 列表失败: {str(e)}")
            self.handle_error(f"清空 {self.__class__.__name__} 列表失败")
            
    def update_recent_list(self):
        """更新最近列表"""
        try:
            if not self.recent_menu:
                return
                
            self.recent_menu.clear()
            
            if not self.parameters:
                self.add_action(
                    "no_recent",
                    "无最近记录",
                    enabled=False
                )
                return
                
            self._populate_recent_list()
            logger.info(f"已更新 {self.__class__.__name__} 最近列表")
        except Exception as e:
            logger.error(f"更新 {self.__class__.__name__} 最近列表失败: {str(e)}")
            self.handle_error(f"更新 {self.__class__.__name__} 最近列表失败")
            
    def _populate_recent_list(self):
        """填充最近列表"""
        pass
        
    def load_resource(self, resource_params: Dict[str, Any]):
        """加载资源"""
        try:
            self.main_window.tree_view.load_for_treeview(resource_params)
            logger.info(f"已加载资源: {resource_params.get('model_name', 'unknown')}")
        except Exception as e:
            logger.error(f"加载资源失败: {str(e)}")
            self.handle_error("加载资源失败")
            
    def load_default_resource(self) -> Dict[str, Any]:
        """加载默认资源"""
        pass 