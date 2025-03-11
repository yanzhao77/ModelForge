from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit,
    QMenu
)

from .base_dialog import BaseDialog, DialogConfig
from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class TableConfig:
    """表格配置数据类"""
    headers: List[str]
    column_stretches: List[QHeaderView.ResizeMode] = None
    enable_context_menu: bool = True
    enable_search: bool = True
    enable_multi_select: bool = False
    enable_edit: bool = False

class BaseTableDialog(BaseDialog):
    """基础表格对话框类"""
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        config: Optional[DialogConfig] = None,
        table_config: Optional[TableConfig] = None
    ):
        super().__init__(parent, config)
        
        # 保存表格配置
        self.table_config = table_config or TableConfig([])
        
        # 初始化搜索文本
        self.search_text = ""
        
    def _create_content(self):
        """创建内容区域"""
        try:
            # 创建搜索区域
            if self.table_config.enable_search:
                self._create_search_bar()
            
            # 创建表格
            self._create_table()
            
            # 创建工具栏
            self._create_toolbar()
            
            logger.debug("表格对话框内容创建完成")
        except Exception as e:
            logger.error(f"创建表格对话框内容失败: {str(e)}")
            raise
            
    def _create_search_bar(self):
        """创建搜索栏"""
        try:
            # 创建布局
            layout = QHBoxLayout()
            
            # 创建搜索框
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("搜索...")
            self.search_input.textChanged.connect(self._on_search_changed)
            
            # 添加到布局
            layout.addWidget(QLabel("搜索:"))
            layout.addWidget(self.search_input)
            layout.addStretch()
            
            # 添加到主布局
            self.main_layout.addLayout(layout)
            
            logger.debug("搜索栏创建完成")
        except Exception as e:
            logger.error(f"创建搜索栏失败: {str(e)}")
            raise
            
    def _create_table(self):
        """创建表格"""
        try:
            # 创建表格
            self.table = QTableWidget()
            
            # 设置列数和表头
            self.table.setColumnCount(len(self.table_config.headers))
            self.table.setHorizontalHeaderLabels(self.table_config.headers)
            
            # 设置列宽
            if self.table_config.column_stretches:
                for col, mode in enumerate(self.table_config.column_stretches):
                    self.table.horizontalHeader().setSectionResizeMode(col, mode)
            else:
                # 默认最后一列自适应
                for col in range(len(self.table_config.headers) - 1):
                    self.table.horizontalHeader().setSectionResizeMode(
                        col, QHeaderView.ResizeToContents
                    )
                self.table.horizontalHeader().setSectionResizeMode(
                    len(self.table_config.headers) - 1, QHeaderView.Stretch
                )
            
            # 设置选择模式
            if self.table_config.enable_multi_select:
                self.table.setSelectionMode(QTableWidget.MultiSelection)
            else:
                self.table.setSelectionMode(QTableWidget.SingleSelection)
            self.table.setSelectionBehavior(QTableWidget.SelectRows)
            
            # 设置编辑模式
            if not self.table_config.enable_edit:
                self.table.setEditTriggers(QTableWidget.NoEditTriggers)
                
            # 设置右键菜单
            if self.table_config.enable_context_menu:
                self.table.setContextMenuPolicy(Qt.CustomContextMenu)
                self.table.customContextMenuRequested.connect(self._show_context_menu)
                
            # 添加到主布局
            self.main_layout.addWidget(self.table)
            
            logger.debug("表格创建完成")
        except Exception as e:
            logger.error(f"创建表格失败: {str(e)}")
            raise
            
    def _create_toolbar(self):
        """创建工具栏"""
        try:
            # 创建布局
            layout = QHBoxLayout()
            
            # 创建按钮
            buttons = self._get_toolbar_buttons()
            
            # 添加按钮
            for text, callback in buttons:
                button = QPushButton(text)
                button.clicked.connect(callback)
                layout.addWidget(button)
                
            # 添加弹簧
            layout.addStretch()
            
            # 添加到主布局
            self.main_layout.addLayout(layout)
            
            logger.debug("工具栏创建完成")
        except Exception as e:
            logger.error(f"创建工具栏失败: {str(e)}")
            raise
            
    def _get_toolbar_buttons(self) -> List[Tuple[str, callable]]:
        """获取工具栏按钮配置"""
        return []
            
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        try:
            # 获取选中的行
            row = self.table.rowAt(pos.y())
            if row < 0:
                return
                
            # 创建菜单
            menu = QMenu(self)
            
            # 添加菜单项
            self._add_context_menu_items(menu)
            
            # 显示菜单
            menu.exec_(self.table.viewport().mapToGlobal(pos))
            
            logger.debug(f"显示右键菜单: row={row}")
        except Exception as e:
            logger.error(f"显示右键菜单失败: {str(e)}")
            
    def _add_context_menu_items(self, menu: QMenu):
        """添加右键菜单项"""
        pass
            
    def _on_search_changed(self, text: str):
        """处理搜索文本变化"""
        try:
            self.search_text = text.lower()
            self._filter_table()
            
            logger.debug(f"搜索文本更新: {text}")
        except Exception as e:
            logger.error(f"处理搜索文本变化失败: {str(e)}")
            
    def _filter_table(self):
        """过滤表格数据"""
        try:
            # 遍历所有行
            for row in range(self.table.rowCount()):
                show = False
                
                # 检查每一列
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item and self.search_text in item.text().lower():
                        show = True
                        break
                        
                # 显示或隐藏行
                self.table.setRowHidden(row, not show)
                
            logger.debug("表格数据过滤完成")
        except Exception as e:
            logger.error(f"过滤表格数据失败: {str(e)}")
            
    def get_selected_rows(self) -> List[int]:
        """获取选中的行"""
        try:
            return [item.row() for item in self.table.selectedItems()]
        except Exception as e:
            logger.error(f"获取选中行失败: {str(e)}")
            return []
            
    def get_current_row(self) -> int:
        """获取当前行"""
        try:
            return self.table.currentRow()
        except Exception as e:
            logger.error(f"获取当前行失败: {str(e)}")
            return -1
            
    def set_table_data(self, data: List[List[str]]):
        """设置表格数据"""
        try:
            # 设置行数
            self.table.setRowCount(len(data))
            
            # 添加数据
            for row, row_data in enumerate(data):
                for col, text in enumerate(row_data):
                    self.table.setItem(row, col, QTableWidgetItem(str(text)))
                    
            logger.debug(f"表格数据设置完成: {len(data)}行")
        except Exception as e:
            logger.error(f"设置表格数据失败: {str(e)}")
            
    def get_table_data(self) -> List[List[str]]:
        """获取表格数据"""
        try:
            data = []
            for row in range(self.table.rowCount()):
                row_data = []
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    row_data.append(item.text() if item else "")
                data.append(row_data)
            return data
        except Exception as e:
            logger.error(f"获取表格数据失败: {str(e)}")
            return []
            
    def clear_table(self):
        """清空表格"""
        try:
            self.table.setRowCount(0)
            logger.debug("表格已清空")
        except Exception as e:
            logger.error(f"清空表格失败: {str(e)}")
            
    def refresh_table(self):
        """刷新表格"""
        try:
            self._filter_table()
            logger.debug("表格已刷新")
        except Exception as e:
            logger.error(f"刷新表格失败: {str(e)}")
            
    def get_cell_data(self, row: int, col: int) -> str:
        """获取单元格数据"""
        try:
            item = self.table.item(row, col)
            return item.text() if item else ""
        except Exception as e:
            logger.error(f"获取单元格数据失败: row={row}, col={col}, error={str(e)}")
            return ""
            
    def set_cell_data(self, row: int, col: int, text: str):
        """设置单元格数据"""
        try:
            self.table.setItem(row, col, QTableWidgetItem(str(text)))
            logger.debug(f"设置单元格数据: row={row}, col={col}, text={text}")
        except Exception as e:
            logger.error(f"设置单元格数据失败: row={row}, col={col}, text={text}, error={str(e)}")
            
    def insert_row(self, row: int, data: List[str]):
        """插入行"""
        try:
            self.table.insertRow(row)
            for col, text in enumerate(data):
                self.table.setItem(row, col, QTableWidgetItem(str(text)))
            logger.debug(f"插入行: row={row}, data={data}")
        except Exception as e:
            logger.error(f"插入行失败: row={row}, data={data}, error={str(e)}")
            
    def remove_row(self, row: int):
        """删除行"""
        try:
            self.table.removeRow(row)
            logger.debug(f"删除行: row={row}")
        except Exception as e:
            logger.error(f"删除行失败: row={row}, error={str(e)}")
            
    def move_row(self, from_row: int, to_row: int):
        """移动行"""
        try:
            # 获取行数据
            data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(from_row, col)
                data.append(item.text() if item else "")
                
            # 删除原行
            self.table.removeRow(from_row)
            
            # 插入新行
            self.table.insertRow(to_row)
            for col, text in enumerate(data):
                self.table.setItem(to_row, col, QTableWidgetItem(text))
                
            logger.debug(f"移动行: from={from_row}, to={to_row}")
        except Exception as e:
            logger.error(f"移动行失败: from={from_row}, to={to_row}, error={str(e)}")
            
    def sort_table(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        """排序表格"""
        try:
            self.table.sortItems(column, order)
            logger.debug(f"排序表格: column={column}, order={order}")
        except Exception as e:
            logger.error(f"排序表格失败: column={column}, order={order}, error={str(e)}")
            
    def export_table(self, file_path: str):
        """导出表格数据"""
        try:
            import csv
            
            # 获取表格数据
            data = [self.table_config.headers]  # 添加表头
            data.extend(self.get_table_data())
            
            # 写入CSV文件
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(data)
                
            logger.debug(f"导出表格数据: {file_path}")
        except Exception as e:
            logger.error(f"导出表格数据失败: {file_path}, error={str(e)}")
            raise
            
    def import_table(self, file_path: str):
        """导入表格数据"""
        try:
            import csv
            
            # 读取CSV文件
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader)  # 跳过表头
                data = list(reader)
                
            # 设置表格数据
            self.set_table_data(data)
            
            logger.debug(f"导入表格数据: {file_path}")
        except Exception as e:
            logger.error(f"导入表格数据失败: {file_path}, error={str(e)}")
            raise 