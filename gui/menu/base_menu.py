from typing import Optional, Callable, Dict, Any, List, Union
from dataclasses import dataclass, field
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenuBar, QMenu, QWidget, QMessageBox

from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class MenuAction:
    """菜单动作配置"""
    name: str
    text: str
    slot: Optional[Callable] = None
    shortcut: Optional[Union[str, QKeySequence]] = None
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    tooltip: Optional[str] = None
    icon: Optional[str] = None
    status_tip: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

class BaseMenu:
    """基础菜单类，所有菜单类的父类"""
    
    def __init__(self, menu_bar: QMenuBar, parent: QWidget, title: str):
        """
        初始化基础菜单
        
        Args:
            menu_bar: 菜单栏
            parent: 父窗口
            title: 菜单标题
        """
        try:
            self.parent = parent
            self.menu = menu_bar.addMenu(title)
            self.actions: Dict[str, QAction] = {}
            self.submenus: Dict[str, QMenu] = {}
            self._setup_menu()
            logger.debug(f"菜单 '{title}' 初始化完成")
        except Exception as e:
            logger.error(f"菜单 '{title}' 初始化失败: {str(e)}")
            raise
        
    def _setup_menu(self):
        """设置菜单项，子类需要重写此方法"""
        pass
        
    def add_action(self,
                   name: str, 
                   text: str,
                   slot: Optional[Callable] = None,
                   shortcut: Optional[Union[str, QKeySequence]] = None,
                   checkable: bool = False,
                   checked: bool = False,
                   enabled: bool = True,
                   menu: QMenu = None,
                   tooltip: Optional[str] = None,
                   icon: Optional[str] = None,
                   status_tip: Optional[str] = None,
                   data: Optional[Dict[str, Any]] = None) -> QAction:
        """
        添加菜单项
        
        Args:
            name: 动作名称（内部使用）
            text: 显示文本
            slot: 槽函数
            shortcut: 快捷键
            checkable: 是否可勾选
            checked: 是否已勾选
            enabled: 是否启用
            tooltip: 工具提示
            icon: 图标路径
            status_tip: 状态栏提示
            data: 附加数据
            
        Returns:
            创建的QAction对象
        """
        try:
            if name in self.actions:
                logger.warning(f"菜单项 '{name}' 已存在，将被覆盖")

            if menu is not None:
                action = QAction(text, menu)
            else:
                action = QAction(text, self.menu)
            
            if shortcut:
                if isinstance(shortcut, str):
                    shortcut = QKeySequence(shortcut)
                action.setShortcut(shortcut)
                
            if tooltip:
                action.setToolTip(tooltip)
                
            if icon:
                action.setIcon(icon)
                
            if status_tip:
                action.setStatusTip(status_tip)
                
            if data:
                for key, value in data.items():
                    action.setData({key: value})
                    
            action.setCheckable(checkable)
            action.setChecked(checked)
            action.setEnabled(enabled)
            
            if slot:
                action.triggered.connect(slot)

            if menu is not None:
                menu.addAction(action)
            else:
                self.menu.addAction(action)

            self.actions[name] = action
            logger.debug(f"添加菜单项: {name} - {text}")
            return action
            
        except Exception as e:
            logger.error(f"添加菜单项失败: {str(e)}")
            raise
            
    def add_separator(self):
        """添加分隔线"""
        try:
            self.menu.addSeparator()
            logger.debug("添加分隔线")
        except Exception as e:
            logger.error(f"添加分隔线失败: {str(e)}")
            
    def add_submenu(self, name: str, title: str) -> QMenu:
        """
        添加子菜单
        
        Args:
            name: 子菜单名称（内部使用）
            title: 子菜单标题
            
        Returns:
            创建的子菜单对象
        """
        try:
            if name in self.submenus:
                logger.warning(f"子菜单 '{name}' 已存在，将被覆盖")
                
            submenu = QMenu(title, self.menu)
            self.menu.addMenu(submenu)
            self.submenus[name] = submenu
            logger.debug(f"添加子菜单: {name} - {title}")
            return submenu
            
        except Exception as e:
            logger.error(f"添加子菜单失败: {str(e)}")
            raise
            
    def get_action(self, name: str) -> Optional[QAction]:
        """
        获取菜单项
        
        Args:
            name: 动作名称
            
        Returns:
            QAction对象，如果不存在则返回None
        """
        if action := self.actions.get(name):
            return action
        logger.warning(f"菜单项 '{name}' 不存在")
        return None
        
    def get_submenu(self, name: str) -> Optional[QMenu]:
        """
        获取子菜单
        
        Args:
            name: 子菜单名称
            
        Returns:
            QMenu对象，如果不存在则返回None
        """
        if submenu := self.submenus.get(name):
            return submenu
        logger.warning(f"子菜单 '{name}' 不存在")
        return None
        
    def enable_action(self, name: str, enabled: bool = True):
        """
        启用/禁用菜单项
        
        Args:
            name: 动作名称
            enabled: 是否启用
        """
        try:
            if action := self.get_action(name):
                action.setEnabled(enabled)
                logger.debug(f"{'启用' if enabled else '禁用'}菜单项: {name}")
        except Exception as e:
            logger.error(f"设置菜单项状态失败: {str(e)}")
            
    def set_checked(self, name: str, checked: bool = True):
        """
        设置菜单项的勾选状态
        
        Args:
            name: 动作名称
            checked: 是否勾选
        """
        try:
            if action := self.get_action(name):
                action.setChecked(checked)
                logger.debug(f"设置菜单项 {name} 勾选状态: {checked}")
        except Exception as e:
            logger.error(f"设置菜单项勾选状态失败: {str(e)}")
            
    def set_text(self, name: str, text: str):
        """
        设置菜单项文本
        
        Args:
            name: 动作名称
            text: 新文本
        """
        try:
            if action := self.get_action(name):
                action.setText(text)
                logger.debug(f"设置菜单项 {name} 文本: {text}")
        except Exception as e:
            logger.error(f"设置菜单项文本失败: {str(e)}")
            
    def remove_action(self, name: str):
        """
        移除菜单项
        
        Args:
            name: 动作名称
        """
        try:
            if action := self.get_action(name):
                self.menu.removeAction(action)
                del self.actions[name]
                logger.debug(f"移除菜单项: {name}")
        except Exception as e:
            logger.error(f"移除菜单项失败: {str(e)}")
            
    def remove_submenu(self, name: str):
        """
        移除子菜单
        
        Args:
            name: 子菜单名称
        """
        try:
            if submenu := self.get_submenu(name):
                self.menu.removeAction(submenu.menuAction())
                del self.submenus[name]
                logger.debug(f"移除子菜单: {name}")
        except Exception as e:
            logger.error(f"移除子菜单失败: {str(e)}")
            
    def clear_menu(self):
        """清空菜单"""
        try:
            self.menu.clear()
            self.actions.clear()
            self.submenus.clear()
            logger.debug("清空菜单")
        except Exception as e:
            logger.error(f"清空菜单失败: {str(e)}")
            
    @Slot()
    def handle_error(self, error: str):
        """
        处理错误
        
        Args:
            error: 错误信息
        """
        logger.error(f"菜单操作失败: {error}")
        QMessageBox.critical(self.parent, "错误", error)
        
    def is_action_enabled(self, name: str) -> bool:
        """
        检查菜单项是否启用
        
        Args:
            name: 动作名称
            
        Returns:
            是否启用
        """
        if action := self.get_action(name):
            return action.isEnabled()
        return False
        
    def is_action_checked(self, name: str) -> bool:
        """
        检查菜单项是否勾选
        
        Args:
            name: 动作名称
            
        Returns:
            是否勾选
        """
        if action := self.get_action(name):
            return action.isChecked()
        return False
        
    def get_all_actions(self) -> List[QAction]:
        """
        获取所有菜单项
        
        Returns:
            所有菜单项列表
        """
        return list(self.actions.values())
        
    def get_all_submenus(self) -> List[QMenu]:
        """
        获取所有子菜单
        
        Returns:
            所有子菜单列表
        """
        return list(self.submenus.values()) 