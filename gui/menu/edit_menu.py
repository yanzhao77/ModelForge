from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from PySide6.QtCore import Qt, Slot, QObject
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtWidgets import QWidget, QTextEdit, QLineEdit, QMenuBar

from common.const.common_const import LoggerNames, get_logger
from .base_menu import BaseMenu, MenuAction

logger = get_logger(LoggerNames.UI)

@dataclass
class EditMenuConfig:
    """编辑菜单配置"""
    actions: Dict[str, MenuAction] = field(default_factory=lambda: {
        "undo": MenuAction(
            name="undo",
            text="撤销",
            shortcut="Ctrl+Z",
            tooltip="撤销上一步操作",
            status_tip="撤销上一步操作"
        ),
        "redo": MenuAction(
            name="redo",
            text="重做",
            shortcut="Ctrl+Y",
            tooltip="重做上一步操作",
            status_tip="重做上一步操作"
        ),
        "cut": MenuAction(
            name="cut",
            text="剪切",
            shortcut="Ctrl+X",
            tooltip="剪切选中的内容",
            status_tip="剪切选中的内容到剪贴板"
        ),
        "copy": MenuAction(
            name="copy",
            text="复制",
            shortcut="Ctrl+C",
            tooltip="复制选中的内容",
            status_tip="复制选中的内容到剪贴板"
        ),
        "paste": MenuAction(
            name="paste",
            text="粘贴",
            shortcut="Ctrl+V",
            tooltip="粘贴剪贴板内容",
            status_tip="从剪贴板粘贴内容"
        ),
        "delete": MenuAction(
            name="delete",
            text="删除",
            shortcut="Delete",
            tooltip="删除选中的内容",
            status_tip="删除选中的内容"
        ),
        "select_all": MenuAction(
            name="select_all",
            text="全选",
            shortcut="Ctrl+A",
            tooltip="选择所有内容",
            status_tip="选择所有内容"
        ),
        "unselect_all": MenuAction(
            name="unselect_all",
            text="取消全选",
            shortcut="Ctrl+Shift+A",
            tooltip="取消所有选择",
            status_tip="取消所有选择"
        ),
        "find": MenuAction(
            name="find",
            text="查找",
            shortcut="Ctrl+F",
            tooltip="查找内容",
            status_tip="查找指定内容"
        ),
        "replace": MenuAction(
            name="replace",
            text="替换",
            shortcut="Ctrl+H",
            tooltip="替换内容",
            status_tip="查找并替换内容"
        )
    })
    
    supported_widgets: List[type] = field(default_factory=lambda: [
        QTextEdit,
        QLineEdit
    ])

class EditMenu(BaseMenu):
    """编辑菜单类"""
    
    def __init__(self, menu_bar, parent):
        """
        初始化编辑菜单
        
        Args:
            menu_bar: 菜单栏
            parent: 父窗口
        """
        try:
            self.config = EditMenuConfig()
            super().__init__(menu_bar, parent, "编辑")

            # 连接焦点变化信号
            self.parent.focusChanged.connect(self._on_focus_changed)  # 连接信号
            logger.debug("编辑菜单初始化完成")
        except Exception as e:
            logger.error(f"编辑菜单初始化失败: {str(e)}")
            raise
        
    def _setup_menu(self):
        """设置菜单项"""
        try:
            # 添加撤销/重做动作
            self._add_undo_redo_actions()
            self.add_separator()
            
            # 添加剪切/复制/粘贴/删除动作
            self._add_clipboard_actions()
            self.add_separator()
            
            # 添加选择动作
            self._add_selection_actions()
            self.add_separator()
            
            # 添加查找/替换动作
            self._add_find_replace_actions()
            
            # 初始状态下禁用所有动作
            self._update_actions_state(None)
            
            logger.info("编辑菜单初始化完成")
        except Exception as e:
            logger.error(f"设置编辑菜单失败: {str(e)}")
            raise
            
    def _add_undo_redo_actions(self):
        """添加撤销/重做动作"""
        try:
            for action_key in ["undo", "redo"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    action.shortcut,
                    tooltip=action.tooltip,
                    status_tip=action.status_tip
                )
            logger.debug("添加撤销/重做动作完成")
        except Exception as e:
            logger.error(f"添加撤销/重做动作失败: {str(e)}")
            raise
            
    def _add_clipboard_actions(self):
        """添加剪贴板动作"""
        try:
            for action_key in ["cut", "copy", "paste", "delete"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    action.shortcut,
                    tooltip=action.tooltip,
                    status_tip=action.status_tip
                )
            logger.debug("添加剪贴板动作完成")
        except Exception as e:
            logger.error(f"添加剪贴板动作失败: {str(e)}")
            raise
            
    def _add_selection_actions(self):
        """添加选择动作"""
        try:
            for action_key in ["select_all", "unselect_all"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    action.shortcut,
                    tooltip=action.tooltip,
                    status_tip=action.status_tip
                )
            logger.debug("添加选择动作完成")
        except Exception as e:
            logger.error(f"添加选择动作失败: {str(e)}")
            raise
            
    def _add_find_replace_actions(self):
        """添加查找/替换动作"""
        try:
            for action_key in ["find", "replace"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    action.shortcut,
                    tooltip=action.tooltip,
                    status_tip=action.status_tip
                )
            logger.debug("添加查找/替换动作完成")
        except Exception as e:
            logger.error(f"添加查找/替换动作失败: {str(e)}")
            raise
            
    def _get_focused_widget(self) -> Optional[QWidget]:
        """
        获取当前焦点部件
        
        Returns:
            当前焦点部件，如果没有则返回None
        """
        widget = self.parent.focusWidget()
        if widget and any(isinstance(widget, t) for t in self.config.supported_widgets):
            return widget
        return None
            
    def _update_actions_state(self, widget: Optional[QWidget]):
        """
        更新动作状态
        
        Args:
            widget: 当前焦点部件
        """
        try:
            has_widget = widget is not None
            has_text = False
            has_selection = False
            can_undo = False
            can_redo = False
            
            if has_widget:
                if isinstance(widget, (QTextEdit, QLineEdit)):
                    has_text = bool(widget.text() if isinstance(widget, QLineEdit) else widget.toPlainText())
                    has_selection = bool(widget.hasSelectedText() if isinstance(widget, QLineEdit) else widget.textCursor().hasSelection())
                    if hasattr(widget, "isUndoAvailable"):
                        can_undo = widget.isUndoAvailable()
                    if hasattr(widget, "isRedoAvailable"):
                        can_redo = widget.isRedoAvailable()
            
            # 更新动作状态
            self.enable_action("undo", can_undo)
            self.enable_action("redo", can_redo)
            self.enable_action("cut", has_selection)
            self.enable_action("copy", has_selection)
            self.enable_action("paste", has_widget)
            self.enable_action("delete", has_selection)
            self.enable_action("select_all", has_text)
            self.enable_action("unselect_all", has_selection)
            self.enable_action("find", has_text)
            self.enable_action("replace", has_text)
            
            logger.debug("更新动作状态完成")
        except Exception as e:
            logger.error(f"更新动作状态失败: {str(e)}")
            
    @Slot(QWidget, QWidget)
    def _on_focus_changed(self, old: Optional[QWidget], new: Optional[QWidget]):
        """
        处理焦点变化
        
        Args:
            old: 旧焦点部件
            new: 新焦点部件
        """
        try:
            self._update_actions_state(new if new and any(isinstance(new, t) for t in self.config.supported_widgets) else None)
            logger.debug(f"焦点变化: {type(old).__name__ if old else 'None'} -> {type(new).__name__ if new else 'None'}")
        except Exception as e:
            logger.error(f"处理焦点变化失败: {str(e)}")
            
    @Slot()
    def _handle_undo(self):
        """处理撤销动作"""
        try:
            if widget := self._get_focused_widget():
                widget.undo()
                self._update_actions_state(widget)
                logger.debug("执行撤销操作")
        except Exception as e:
            logger.error(f"撤销操作失败: {str(e)}")
            self.handle_error("撤销操作失败")
            
    @Slot()
    def _handle_redo(self):
        """处理重做动作"""
        try:
            if widget := self._get_focused_widget():
                widget.redo()
                self._update_actions_state(widget)
                logger.debug("执行重做操作")
        except Exception as e:
            logger.error(f"重做操作失败: {str(e)}")
            self.handle_error("重做操作失败")
            
    @Slot()
    def _handle_cut(self):
        """处理剪切动作"""
        try:
            if widget := self._get_focused_widget():
                widget.cut()
                self._update_actions_state(widget)
                logger.debug("执行剪切操作")
        except Exception as e:
            logger.error(f"剪切操作失败: {str(e)}")
            self.handle_error("剪切操作失败")
            
    @Slot()
    def _handle_copy(self):
        """处理复制动作"""
        try:
            if widget := self._get_focused_widget():
                widget.copy()
                self._update_actions_state(widget)
                logger.debug("执行复制操作")
        except Exception as e:
            logger.error(f"复制操作失败: {str(e)}")
            self.handle_error("复制操作失败")
            
    @Slot()
    def _handle_paste(self):
        """处理粘贴动作"""
        try:
            if widget := self._get_focused_widget():
                widget.paste()
                self._update_actions_state(widget)
                logger.debug("执行粘贴操作")
        except Exception as e:
            logger.error(f"粘贴操作失败: {str(e)}")
            self.handle_error("粘贴操作失败")
            
    @Slot()
    def _handle_delete(self):
        """处理删除动作"""
        try:
            if widget := self._get_focused_widget():
                if isinstance(widget, QTextEdit):
                    cursor = widget.textCursor()
                    cursor.removeSelectedText()
                elif isinstance(widget, QLineEdit):
                    widget.del_()
                self._update_actions_state(widget)
                logger.debug("执行删除操作")
        except Exception as e:
            logger.error(f"删除操作失败: {str(e)}")
            self.handle_error("删除操作失败")
            
    @Slot()
    def _handle_select_all(self):
        """处理全选动作"""
        try:
            if widget := self._get_focused_widget():
                widget.selectAll()
                self._update_actions_state(widget)
                logger.debug("执行全选操作")
        except Exception as e:
            logger.error(f"全选操作失败: {str(e)}")
            self.handle_error("全选操作失败")
            
    @Slot()
    def _handle_unselect_all(self):
        """处理取消全选动作"""
        try:
            if widget := self._get_focused_widget():
                if isinstance(widget, QTextEdit):
                    cursor = widget.textCursor()
                    cursor.clearSelection()
                    widget.setTextCursor(cursor)
                elif isinstance(widget, QLineEdit):
                    widget.deselect()
                self._update_actions_state(widget)
                logger.debug("执行取消全选操作")
        except Exception as e:
            logger.error(f"取消全选操作失败: {str(e)}")
            self.handle_error("取消全选操作失败")
            
    @Slot()
    def _handle_find(self):
        """处理查找动作"""
        try:
            if widget := self._get_focused_widget():
                # TODO: 实现查找对话框
                logger.debug("执行查找操作")
        except Exception as e:
            logger.error(f"查找操作失败: {str(e)}")
            self.handle_error("查找操作失败")
            
    @Slot()
    def _handle_replace(self):
        """处理替换动作"""
        try:
            if widget := self._get_focused_widget():
                # TODO: 实现替换对话框
                logger.debug("执行替换操作")
        except Exception as e:
            logger.error(f"替换操作失败: {str(e)}")
            self.handle_error("替换操作失败")
