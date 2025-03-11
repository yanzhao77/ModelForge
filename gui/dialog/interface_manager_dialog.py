from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
    QMenu, QFileDialog
)
from pathlib import Path
import os
import json
import shutil

from .base_dialog import BaseDialog, DialogConfig
from .interface_show_dialog import InterfaceShowDialog
from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class InterfaceInfo:
    """接口信息数据类"""
    name: str
    type: str
    path: str
    api_key: str = ""
    base_url: str = ""
    status: str = "未测试"

@dataclass
class InterfaceManagerData:
    """接口管理数据类"""
    interfaces: List[InterfaceInfo] = field(default_factory=list)
    config_dir: str = "configs/interfaces"
    backup_dir: str = "configs/backups"

class InterfaceManagerDialog(BaseDialog):
    """接口管理对话框"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        config = DialogConfig(
            title="接口管理",
            width=800,
            height=600,
            resizable=True
        )
        super().__init__(parent, config)
        
        # 初始化数据
        self.data = InterfaceManagerData()
        
    def _create_content(self):
        """创建内容区域"""
        try:
            # 创建工具栏
            self._create_toolbar()
            
            # 创建接口列表
            self._create_interface_list()
            
            # 加载接口数据
            self._load_interfaces()
            
            logger.debug("接口管理对话框内容创建完成")
        except Exception as e:
            logger.error(f"创建接口管理对话框内容失败: {str(e)}")
            raise
            
    def _create_toolbar(self):
        """创建工具栏"""
        try:
            # 创建布局
            layout = QHBoxLayout()
            
            # 创建按钮
            add_button = QPushButton("添加")
            edit_button = QPushButton("编辑")
            delete_button = QPushButton("删除")
            test_button = QPushButton("测试")
            import_button = QPushButton("导入")
            export_button = QPushButton("导出")
            refresh_button = QPushButton("刷新")
            
            # 连接信号
            add_button.clicked.connect(self._add_interface)
            edit_button.clicked.connect(self._edit_interface)
            delete_button.clicked.connect(self._delete_interface)
            test_button.clicked.connect(self._test_interface)
            import_button.clicked.connect(self._import_interface)
            export_button.clicked.connect(self._export_interface)
            refresh_button.clicked.connect(self._refresh_interfaces)
            
            # 添加到布局
            layout.addWidget(add_button)
            layout.addWidget(edit_button)
            layout.addWidget(delete_button)
            layout.addWidget(test_button)
            layout.addWidget(import_button)
            layout.addWidget(export_button)
            layout.addWidget(refresh_button)
            layout.addStretch()
            
            # 添加到主布局
            self.main_layout.addLayout(layout)
            
            logger.debug("工具栏创建完成")
        except Exception as e:
            logger.error(f"创建工具栏失败: {str(e)}")
            raise
            
    def _create_interface_list(self):
        """创建接口列表"""
        try:
            # 创建表格
            self.interface_table = QTableWidget()
            self.interface_table.setColumnCount(6)
            self.interface_table.setHorizontalHeaderLabels([
                "名称", "类型", "API密钥", "基础URL",
                "状态", "配置文件"
            ])
            
            # 设置列宽
            self.interface_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.interface_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.interface_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.interface_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.interface_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            self.interface_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            
            # 设置右键菜单
            self.interface_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.interface_table.customContextMenuRequested.connect(self._show_context_menu)
            
            # 添加到主布局
            self.main_layout.addWidget(self.interface_table)
            
            logger.debug("接口列表创建完成")
        except Exception as e:
            logger.error(f"创建接口列表失败: {str(e)}")
            raise
            
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        try:
            # 获取选中的行
            row = self.interface_table.rowAt(pos.y())
            if row < 0:
                return
                
            # 创建菜单
            menu = QMenu(self)
            
            # 添加菜单项
            edit_action = menu.addAction("编辑")
            delete_action = menu.addAction("删除")
            test_action = menu.addAction("测试")
            export_action = menu.addAction("导出")
            
            # 显示菜单
            action = menu.exec_(self.interface_table.viewport().mapToGlobal(pos))
            
            # 处理菜单选择
            if action == edit_action:
                self._edit_interface()
            elif action == delete_action:
                self._delete_interface()
            elif action == test_action:
                self._test_interface()
            elif action == export_action:
                self._export_interface()
                
            logger.debug(f"显示右键菜单: row={row}")
        except Exception as e:
            logger.error(f"显示右键菜单失败: {str(e)}")
            
    def _load_interfaces(self):
        """加载接口数据"""
        try:
            # 创建配置目录
            os.makedirs(self.data.config_dir, exist_ok=True)
            os.makedirs(self.data.backup_dir, exist_ok=True)
            
            # 清空数据
            self.data.interfaces.clear()
            
            # 遍历配置文件
            for file in os.listdir(self.data.config_dir):
                if not file.endswith(".json"):
                    continue
                    
                path = os.path.join(self.data.config_dir, file)
                try:
                    # 读取配置文件
                    with open(path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        
                    # 创建接口信息
                    interface = InterfaceInfo(
                        name=config.get("name", ""),
                        type=config.get("type", ""),
                        path=path,
                        api_key=config.get("api_key", ""),
                        base_url=config.get("base_url", ""),
                        status=config.get("status", "未测试")
                    )
                    
                    # 添加到列表
                    self.data.interfaces.append(interface)
                except Exception as e:
                    logger.error(f"加载接口配置失败: {path} - {str(e)}")
                    
            # 更新表格
            self._update_interface_table()
            
            logger.debug(f"加载接口数据完成: {len(self.data.interfaces)}个接口")
        except Exception as e:
            logger.error(f"加载接口数据失败: {str(e)}")
            self.show_error("加载失败", str(e))
            
    def _update_interface_table(self):
        """更新接口表格"""
        try:
            # 清空表格
            self.interface_table.setRowCount(0)
            
            # 添加数据
            for interface in self.data.interfaces:
                row = self.interface_table.rowCount()
                self.interface_table.insertRow(row)
                
                # 设置单元格
                self.interface_table.setItem(row, 0, QTableWidgetItem(interface.name))
                self.interface_table.setItem(row, 1, QTableWidgetItem(interface.type))
                self.interface_table.setItem(row, 2, QTableWidgetItem("*" * 8))
                self.interface_table.setItem(row, 3, QTableWidgetItem(interface.base_url))
                self.interface_table.setItem(row, 4, QTableWidgetItem(interface.status))
                self.interface_table.setItem(row, 5, QTableWidgetItem(interface.path))
                
            logger.debug("接口表格更新完成")
        except Exception as e:
            logger.error(f"更新接口表格失败: {str(e)}")
            
    def _add_interface(self):
        """添加接口"""
        try:
            # 创建对话框
            dialog = InterfaceShowDialog(self)
            
            if dialog.exec_():
                # 获取数据
                data = dialog.get_data()
                
                # 创建配置文件
                file_name = f"{data['name']}.json"
                path = os.path.join(self.data.config_dir, file_name)
                
                # 保存配置
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                    
                # 创建接口信息
                interface = InterfaceInfo(
                    name=data["name"],
                    type=data["type"],
                    path=path,
                    api_key=data["api_key"],
                    base_url=data["base_url"]
                )
                
                # 添加到列表
                self.data.interfaces.append(interface)
                
                # 更新表格
                self._update_interface_table()
                
                logger.debug(f"添加接口成功: {data['name']}")
        except Exception as e:
            logger.error(f"添加接口失败: {str(e)}")
            self.show_error("添加失败", str(e))
            
    def _edit_interface(self):
        """编辑接口"""
        try:
            # 获取选中的行
            current_row = self.interface_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要编辑的接口")
                return
                
            # 获取接口数据
            interface = self.data.interfaces[current_row]
            
            # 读取配置文件
            with open(interface.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            # 创建对话框
            dialog = InterfaceShowDialog(self)
            dialog.set_data(data)
            
            if dialog.exec_():
                # 获取数据
                new_data = dialog.get_data()
                
                # 备份原文件
                backup_path = os.path.join(
                    self.data.backup_dir,
                    f"{interface.name}_{interface.type}.json"
                )
                shutil.copy2(interface.path, backup_path)
                
                # 保存新配置
                with open(interface.path, "w", encoding="utf-8") as f:
                    json.dump(new_data, f, indent=4, ensure_ascii=False)
                    
                # 更新接口信息
                interface.name = new_data["name"]
                interface.type = new_data["type"]
                interface.api_key = new_data["api_key"]
                interface.base_url = new_data["base_url"]
                
                # 更新表格
                self._update_interface_table()
                
                logger.debug(f"编辑接口成功: {new_data['name']}")
        except Exception as e:
            logger.error(f"编辑接口失败: {str(e)}")
            self.show_error("编辑失败", str(e))
            
    def _delete_interface(self):
        """删除接口"""
        try:
            # 获取选中的行
            current_row = self.interface_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要删除的接口")
                return
                
            # 获取接口数据
            interface = self.data.interfaces[current_row]
            
            # 确认删除
            if not self.show_question("确认", f"确定要删除接口 {interface.name} 吗?"):
                return
                
            # 备份配置文件
            backup_path = os.path.join(
                self.data.backup_dir,
                f"{interface.name}_{interface.type}.json"
            )
            shutil.copy2(interface.path, backup_path)
            
            # 删除配置文件
            os.remove(interface.path)
            
            # 从列表中删除
            self.data.interfaces.pop(current_row)
            
            # 更新表格
            self._update_interface_table()
            
            logger.debug(f"删除接口成功: {interface.name}")
        except Exception as e:
            logger.error(f"删除接口失败: {str(e)}")
            self.show_error("删除失败", str(e))
            
    def _test_interface(self):
        """测试接口"""
        try:
            # 获取选中的行
            current_row = self.interface_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要测试的接口")
                return
                
            # 获取接口数据
            interface = self.data.interfaces[current_row]
            
            # TODO: 实现接口测试逻辑
            interface.status = "测试中"
            self._update_interface_table()
            
            logger.debug(f"测试接口: {interface.name}")
        except Exception as e:
            logger.error(f"测试接口失败: {str(e)}")
            self.show_error("测试失败", str(e))
            
    def _import_interface(self):
        """导入接口"""
        try:
            # 选择文件
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "选择接口配置文件",
                str(Path.home()),
                "JSON文件 (*.json);;所有文件 (*.*)"
            )
            
            if not paths:
                return
                
            # 导入配置
            for path in paths:
                try:
                    # 读取配置文件
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                    # 创建新文件名
                    file_name = f"{data['name']}.json"
                    new_path = os.path.join(self.data.config_dir, file_name)
                    
                    # 复制文件
                    shutil.copy2(path, new_path)
                    
                    # 创建接口信息
                    interface = InterfaceInfo(
                        name=data["name"],
                        type=data["type"],
                        path=new_path,
                        api_key=data["api_key"],
                        base_url=data["base_url"]
                    )
                    
                    # 添加到列表
                    self.data.interfaces.append(interface)
                except Exception as e:
                    logger.error(f"导入接口配置失败: {path} - {str(e)}")
                    
            # 更新表格
            self._update_interface_table()
            
            logger.debug(f"导入接口完成: {len(paths)}个文件")
        except Exception as e:
            logger.error(f"导入接口失败: {str(e)}")
            self.show_error("导入失败", str(e))
            
    def _export_interface(self):
        """导出接口"""
        try:
            # 获取选中的行
            current_row = self.interface_table.currentRow()
            if current_row < 0:
                self.show_warning("提示", "请选择要导出的接口")
                return
                
            # 获取接口数据
            interface = self.data.interfaces[current_row]
            
            # 选择保存路径
            path, _ = QFileDialog.getSaveFileName(
                self,
                "导出接口配置",
                os.path.join(str(Path.home()), f"{interface.name}.json"),
                "JSON文件 (*.json);;所有文件 (*.*)"
            )
            
            if not path:
                return
                
            # 复制文件
            shutil.copy2(interface.path, path)
            
            logger.debug(f"导出接口成功: {interface.name} -> {path}")
        except Exception as e:
            logger.error(f"导出接口失败: {str(e)}")
            self.show_error("导出失败", str(e))
            
    def _refresh_interfaces(self):
        """刷新接口列表"""
        try:
            self._load_interfaces()
            logger.debug("刷新接口列表完成")
        except Exception as e:
            logger.error(f"刷新接口列表失败: {str(e)}")
            self.show_error("刷新失败", str(e))
            
    def validate(self) -> bool:
        """验证数据"""
        return True
        
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        try:
            return {
                "interfaces": [
                    {
                        "name": interface.name,
                        "type": interface.type,
                        "path": interface.path,
                        "api_key": interface.api_key,
                        "base_url": interface.base_url,
                        "status": interface.status
                    }
                    for interface in self.data.interfaces
                ]
            }
        except Exception as e:
            logger.error(f"获取数据失败: {str(e)}")
            raise
            
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        try:
            # 清空数据
            self.data.interfaces.clear()
            
            # 添加接口
            for interface_data in data.get("interfaces", []):
                interface = InterfaceInfo(
                    name=interface_data["name"],
                    type=interface_data["type"],
                    path=interface_data["path"],
                    api_key=interface_data["api_key"],
                    base_url=interface_data["base_url"],
                    status=interface_data["status"]
                )
                self.data.interfaces.append(interface)
                
            # 更新表格
            self._update_interface_table()
            
            logger.debug("数据设置完成")
        except Exception as e:
            logger.error(f"设置数据失败: {str(e)}")
            raise
