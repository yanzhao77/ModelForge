from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog
)
from pathlib import Path
import os
import json

from .base_dialog import BaseDialog, DialogConfig
from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class ModelOpenData:
    """模型打开数据类"""
    model_path: str = ""
    model_type: str = ""
    recent_models: List[Dict[str, str]] = field(default_factory=list)
    max_recent: int = 10

class ModelOpenDialog(BaseDialog):
    """模型打开对话框"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        config = DialogConfig(
            title="打开模型",
            width=600,
            height=400,
            resizable=True
        )
        super().__init__(parent, config)
        
        # 初始化数据
        self.data = ModelOpenData()
        
    def _create_content(self):
        """创建内容区域"""
        try:
            # 创建文件选择区域
            self._create_file_select()
            
            # 创建最近模型列表
            self._create_recent_list()
            
            logger.debug("模型打开对话框内容创建完成")
        except Exception as e:
            logger.error(f"创建模型打开对话框内容失败: {str(e)}")
            raise
            
    def _create_file_select(self):
        """创建文件选择区域"""
        try:
            # 创建布局
            layout = QHBoxLayout()
            
            # 创建输入控件
            self.path_input = QLineEdit()
            self.path_input.setReadOnly(True)
            self.path_input.setPlaceholderText("选择模型文件...")
            
            # 创建按钮
            browse_button = QPushButton("浏览")
            browse_button.clicked.connect(self._browse_file)
            
            # 添加到布局
            layout.addWidget(self.path_input)
            layout.addWidget(browse_button)
            
            # 添加到主布局
            self.main_layout.addLayout(layout)
            
            logger.debug("文件选择区域创建完成")
        except Exception as e:
            logger.error(f"创建文件选择区域失败: {str(e)}")
            raise
            
    def _create_recent_list(self):
        """创建最近模型列表"""
        try:
            # 创建标题
            title_label = QLabel("最近使用的模型")
            self.main_layout.addWidget(title_label)
            
            # 创建列表
            self.recent_list = QListWidget()
            self.recent_list.itemDoubleClicked.connect(self._select_recent)
            
            # 添加到主布局
            self.main_layout.addWidget(self.recent_list)
            
            logger.debug("最近模型列表创建完成")
        except Exception as e:
            logger.error(f"创建最近模型列表失败: {str(e)}")
            raise
            
    def _browse_file(self):
        """浏览文件"""
        try:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择模型文件",
                str(Path.home()),
                "模型文件 (*.bin *.gguf *.pt *.pth);;所有文件 (*.*)"
            )
            
            if path:
                self.path_input.setText(path)
                logger.debug(f"选择模型文件: {path}")
        except Exception as e:
            logger.error(f"浏览文件失败: {str(e)}")
            self.show_error("选择失败", str(e))
            
    def _select_recent(self, item: QListWidgetItem):
        """选择最近使用的模型"""
        try:
            # 获取模型数据
            model_data = item.data(Qt.UserRole)
            if model_data:
                self.path_input.setText(model_data["path"])
                logger.debug(f"选择最近模型: {model_data}")
        except Exception as e:
            logger.error(f"选择最近模型失败: {str(e)}")
            self.show_error("选择失败", str(e))
            
    def _update_recent_list(self):
        """更新最近模型列表"""
        try:
            self.recent_list.clear()
            
            for model in self.data.recent_models:
                item = QListWidgetItem()
                item.setText(f"{model['name']} ({model['type']})")
                item.setData(Qt.UserRole, model)
                self.recent_list.addItem(item)
                
            logger.debug("最近模型列表更新完成")
        except Exception as e:
            logger.error(f"更新最近模型列表失败: {str(e)}")
            
    def _add_recent_model(self, path: str, model_type: str):
        """添加最近使用的模型"""
        try:
            # 创建模型数据
            model = {
                "name": os.path.basename(path),
                "path": path,
                "type": model_type
            }
            
            # 检查是否已存在
            for i, m in enumerate(self.data.recent_models):
                if m["path"] == path:
                    # 移动到列表开头
                    self.data.recent_models.pop(i)
                    self.data.recent_models.insert(0, model)
                    return
                    
            # 添加到列表开头
            self.data.recent_models.insert(0, model)
            
            # 限制列表长度
            if len(self.data.recent_models) > self.data.max_recent:
                self.data.recent_models = self.data.recent_models[:self.data.max_recent]
                
            logger.debug(f"添加最近模型: {model}")
        except Exception as e:
            logger.error(f"添加最近模型失败: {str(e)}")
            
    def validate(self) -> bool:
        """验证数据"""
        try:
            path = self.path_input.text().strip()
            if not path:
                self.show_error("验证失败", "请选择模型文件")
                return False
                
            if not os.path.exists(path):
                self.show_error("验证失败", "模型文件不存在")
                return False
                
            return True
        except Exception as e:
            logger.error(f"验证数据失败: {str(e)}")
            return False
            
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        try:
            path = self.path_input.text().strip()
            
            # 根据文件扩展名判断模型类型
            model_type = "未知"
            ext = os.path.splitext(path)[1].lower()
            if ext == ".bin":
                model_type = "二进制"
            elif ext == ".gguf":
                model_type = "GGUF"
            elif ext in [".pt", ".pth"]:
                model_type = "PyTorch"
                
            # 添加到最近使用列表
            self._add_recent_model(path, model_type)
            
            return {
                "model_path": path,
                "model_type": model_type,
                "recent_models": self.data.recent_models
            }
        except Exception as e:
            logger.error(f"获取数据失败: {str(e)}")
            raise
            
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        try:
            # 设置路径
            self.path_input.setText(data.get("model_path", ""))
            
            # 设置最近使用列表
            self.data.recent_models = data.get("recent_models", [])
            self._update_recent_list()
            
            logger.debug("数据设置完成")
        except Exception as e:
            logger.error(f"设置数据失败: {str(e)}")
            raise
