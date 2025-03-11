from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QComboBox, QPushButton, QTabWidget
)

from .base_dialog import BaseDialog, DialogConfig
from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

@dataclass
class ModelParameters:
    """模型参数数据类"""
    # 基本参数
    model_path: str = ""
    model_type: str = ""
    device: str = "cpu"
    threads: int = 4
    context_size: int = 2048
    
    # 生成参数
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    repeat_penalty: float = 1.1
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    
    # 高级参数
    seed: int = -1
    batch_size: int = 1
    max_tokens: int = 2048
    stop_strings: List[str] = field(default_factory=list)
    
    # 系统参数
    use_mmap: bool = True
    use_cache: bool = True
    low_memory: bool = False
    verbose: bool = False

class ModelParametersDialog(BaseDialog):
    """模型参数对话框"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        config = DialogConfig(
            title="模型参数",
            width=600,
            height=500,
            resizable=True
        )
        super().__init__(parent, config)
        
        # 初始化数据
        self.parameters = ModelParameters()
        
    def _create_content(self):
        """创建内容区域"""
        try:
            # 创建标签页
            tab_widget = QTabWidget()
            
            # 添加基本参数页
            basic_tab = self._create_basic_tab()
            tab_widget.addTab(basic_tab, "基本参数")
            
            # 添加生成参数页
            generation_tab = self._create_generation_tab()
            tab_widget.addTab(generation_tab, "生成参数")
            
            # 添加高级参数页
            advanced_tab = self._create_advanced_tab()
            tab_widget.addTab(advanced_tab, "高级参数")
            
            # 添加系统参数页
            system_tab = self._create_system_tab()
            tab_widget.addTab(system_tab, "系统参数")
            
            # 添加到主布局
            self.main_layout.addWidget(tab_widget)
            
            logger.debug("模型参数对话框内容创建完成")
        except Exception as e:
            logger.error(f"创建模型参数对话框内容失败: {str(e)}")
            raise
            
    def _create_basic_tab(self) -> QWidget:
        """创建基本参数标签页"""
        try:
            # 创建页面部件
            widget = QWidget()
            layout = QFormLayout()
            
            # 创建输入控件
            self.model_path_input = QLineEdit()
            browse_button = QPushButton("浏览")
            browse_button.clicked.connect(self._browse_model_path)
            
            path_layout = QHBoxLayout()
            path_layout.addWidget(self.model_path_input)
            path_layout.addWidget(browse_button)
            
            self.model_type_combo = QComboBox()
            self.model_type_combo.addItems([
                "LLaMA", "GPT-J", "GPT-2", "GPT-Neo",
                "BLOOM", "OPT", "其他"
            ])
            
            self.device_combo = QComboBox()
            self.device_combo.addItems(["cpu", "cuda", "mps"])
            
            self.threads_spin = QSpinBox()
            self.threads_spin.setRange(1, 32)
            self.threads_spin.setValue(4)
            
            self.context_size_spin = QSpinBox()
            self.context_size_spin.setRange(1, 8192)
            self.context_size_spin.setValue(2048)
            self.context_size_spin.setSingleStep(256)
            
            # 添加到布局
            layout.addRow("模型路径:", path_layout)
            layout.addRow("模型类型:", self.model_type_combo)
            layout.addRow("设备:", self.device_combo)
            layout.addRow("线程数:", self.threads_spin)
            layout.addRow("上下文大小:", self.context_size_spin)
            
            # 设置布局
            widget.setLayout(layout)
            
            return widget
        except Exception as e:
            logger.error(f"创建基本参数标签页失败: {str(e)}")
            raise
            
    def _create_generation_tab(self) -> QWidget:
        """创建生成参数标签页"""
        try:
            # 创建页面部件
            widget = QWidget()
            layout = QFormLayout()
            
            # 创建输入控件
            self.temperature_spin = QDoubleSpinBox()
            self.temperature_spin.setRange(0.0, 2.0)
            self.temperature_spin.setValue(0.7)
            self.temperature_spin.setSingleStep(0.1)
            
            self.top_p_spin = QDoubleSpinBox()
            self.top_p_spin.setRange(0.0, 1.0)
            self.top_p_spin.setValue(0.95)
            self.top_p_spin.setSingleStep(0.05)
            
            self.top_k_spin = QSpinBox()
            self.top_k_spin.setRange(1, 100)
            self.top_k_spin.setValue(40)
            
            self.repeat_penalty_spin = QDoubleSpinBox()
            self.repeat_penalty_spin.setRange(1.0, 2.0)
            self.repeat_penalty_spin.setValue(1.1)
            self.repeat_penalty_spin.setSingleStep(0.1)
            
            self.presence_penalty_spin = QDoubleSpinBox()
            self.presence_penalty_spin.setRange(-2.0, 2.0)
            self.presence_penalty_spin.setValue(0.0)
            self.presence_penalty_spin.setSingleStep(0.1)
            
            self.frequency_penalty_spin = QDoubleSpinBox()
            self.frequency_penalty_spin.setRange(-2.0, 2.0)
            self.frequency_penalty_spin.setValue(0.0)
            self.frequency_penalty_spin.setSingleStep(0.1)
            
            # 添加到布局
            layout.addRow("温度:", self.temperature_spin)
            layout.addRow("Top P:", self.top_p_spin)
            layout.addRow("Top K:", self.top_k_spin)
            layout.addRow("重复惩罚:", self.repeat_penalty_spin)
            layout.addRow("存在惩罚:", self.presence_penalty_spin)
            layout.addRow("频率惩罚:", self.frequency_penalty_spin)
            
            # 设置布局
            widget.setLayout(layout)
            
            return widget
        except Exception as e:
            logger.error(f"创建生成参数标签页失败: {str(e)}")
            raise
            
    def _create_advanced_tab(self) -> QWidget:
        """创建高级参数标签页"""
        try:
            # 创建页面部件
            widget = QWidget()
            layout = QFormLayout()
            
            # 创建输入控件
            self.seed_spin = QSpinBox()
            self.seed_spin.setRange(-1, 999999)
            self.seed_spin.setValue(-1)
            self.seed_spin.setSpecialValueText("随机")
            
            self.batch_size_spin = QSpinBox()
            self.batch_size_spin.setRange(1, 32)
            self.batch_size_spin.setValue(1)
            
            self.max_tokens_spin = QSpinBox()
            self.max_tokens_spin.setRange(1, 8192)
            self.max_tokens_spin.setValue(2048)
            self.max_tokens_spin.setSingleStep(256)
            
            self.stop_strings_input = QLineEdit()
            self.stop_strings_input.setPlaceholderText("使用逗号分隔多个停止词")
            
            # 添加到布局
            layout.addRow("随机种子:", self.seed_spin)
            layout.addRow("批处理大小:", self.batch_size_spin)
            layout.addRow("最大生成长度:", self.max_tokens_spin)
            layout.addRow("停止词:", self.stop_strings_input)
            
            # 设置布局
            widget.setLayout(layout)
            
            return widget
        except Exception as e:
            logger.error(f"创建高级参数标签页失败: {str(e)}")
            raise
            
    def _create_system_tab(self) -> QWidget:
        """创建系统参数标签页"""
        try:
            # 创建页面部件
            widget = QWidget()
            layout = QFormLayout()
            
            # 创建输入控件
            self.use_mmap_check = QCheckBox()
            self.use_mmap_check.setChecked(True)
            
            self.use_cache_check = QCheckBox()
            self.use_cache_check.setChecked(True)
            
            self.low_memory_check = QCheckBox()
            self.low_memory_check.setChecked(False)
            
            self.verbose_check = QCheckBox()
            self.verbose_check.setChecked(False)
            
            # 添加到布局
            layout.addRow("使用内存映射:", self.use_mmap_check)
            layout.addRow("使用缓存:", self.use_cache_check)
            layout.addRow("低内存模式:", self.low_memory_check)
            layout.addRow("详细日志:", self.verbose_check)
            
            # 设置布局
            widget.setLayout(layout)
            
            return widget
        except Exception as e:
            logger.error(f"创建系统参数标签页失败: {str(e)}")
            raise
            
    def _browse_model_path(self):
        """浏览模型路径"""
        try:
            from PySide6.QtWidgets import QFileDialog
            from pathlib import Path
            
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择模型文件",
                str(Path.home()),
                "模型文件 (*.bin *.gguf *.pt *.pth);;所有文件 (*.*)"
            )
            
            if path:
                self.model_path_input.setText(path)
                logger.debug(f"选择模型文件: {path}")
        except Exception as e:
            logger.error(f"浏览模型路径失败: {str(e)}")
            self.show_error("选择失败", str(e))
            
    def validate(self) -> bool:
        """验证数据"""
        try:
            # 检查模型路径
            if not self.model_path_input.text().strip():
                self.show_error("验证失败", "请选择模型文件")
                return False
                
            # 检查停止词格式
            stop_strings = self.stop_strings_input.text().strip()
            if stop_strings:
                try:
                    [s.strip() for s in stop_strings.split(",")]
                except Exception:
                    self.show_error("验证失败", "停止词格式无效")
                    return False
                    
            return True
        except Exception as e:
            logger.error(f"验证数据失败: {str(e)}")
            return False
            
    def get_data(self) -> Dict[str, Any]:
        """获取数据"""
        try:
            # 获取停止词列表
            stop_strings = []
            if self.stop_strings_input.text().strip():
                stop_strings = [
                    s.strip() 
                    for s in self.stop_strings_input.text().strip().split(",")
                ]
            
            # 返回参数数据
            return {
                # 基本参数
                "model_path": self.model_path_input.text().strip(),
                "model_type": self.model_type_combo.currentText(),
                "device": self.device_combo.currentText(),
                "threads": self.threads_spin.value(),
                "context_size": self.context_size_spin.value(),
                
                # 生成参数
                "temperature": self.temperature_spin.value(),
                "top_p": self.top_p_spin.value(),
                "top_k": self.top_k_spin.value(),
                "repeat_penalty": self.repeat_penalty_spin.value(),
                "presence_penalty": self.presence_penalty_spin.value(),
                "frequency_penalty": self.frequency_penalty_spin.value(),
                
                # 高级参数
                "seed": self.seed_spin.value(),
                "batch_size": self.batch_size_spin.value(),
                "max_tokens": self.max_tokens_spin.value(),
                "stop_strings": stop_strings,
                
                # 系统参数
                "use_mmap": self.use_mmap_check.isChecked(),
                "use_cache": self.use_cache_check.isChecked(),
                "low_memory": self.low_memory_check.isChecked(),
                "verbose": self.verbose_check.isChecked()
            }
        except Exception as e:
            logger.error(f"获取数据失败: {str(e)}")
            raise
            
    def set_data(self, data: Dict[str, Any]):
        """设置数据"""
        try:
            # 设置基本参数
            self.model_path_input.setText(data.get("model_path", ""))
            
            model_type = data.get("model_type", "")
            index = self.model_type_combo.findText(model_type)
            if index >= 0:
                self.model_type_combo.setCurrentIndex(index)
                
            device = data.get("device", "cpu")
            index = self.device_combo.findText(device)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
                
            self.threads_spin.setValue(data.get("threads", 4))
            self.context_size_spin.setValue(data.get("context_size", 2048))
            
            # 设置生成参数
            self.temperature_spin.setValue(data.get("temperature", 0.7))
            self.top_p_spin.setValue(data.get("top_p", 0.95))
            self.top_k_spin.setValue(data.get("top_k", 40))
            self.repeat_penalty_spin.setValue(data.get("repeat_penalty", 1.1))
            self.presence_penalty_spin.setValue(data.get("presence_penalty", 0.0))
            self.frequency_penalty_spin.setValue(data.get("frequency_penalty", 0.0))
            
            # 设置高级参数
            self.seed_spin.setValue(data.get("seed", -1))
            self.batch_size_spin.setValue(data.get("batch_size", 1))
            self.max_tokens_spin.setValue(data.get("max_tokens", 2048))
            
            stop_strings = data.get("stop_strings", [])
            if stop_strings:
                self.stop_strings_input.setText(",".join(stop_strings))
                
            # 设置系统参数
            self.use_mmap_check.setChecked(data.get("use_mmap", True))
            self.use_cache_check.setChecked(data.get("use_cache", True))
            self.low_memory_check.setChecked(data.get("low_memory", False))
            self.verbose_check.setChecked(data.get("verbose", False))
            
            logger.debug("数据设置完成")
        except Exception as e:
            logger.error(f"设置数据失败: {str(e)}")
            raise
