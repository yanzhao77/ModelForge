from PySide6.QtWidgets import QWidget, QHBoxLayout, QCheckBox
from PySide6.QtCore import Signal, Slot
from typing import Dict, Any, Optional

from common.const.common_const import common_const


class RadioLayout(QWidget):
    """单选布局组件，用于显示深度思考和联网搜索选项"""
    
    # 定义信号
    checkbox_state_changed = Signal(bool, str)
    
    def __init__(self, text_area):
        """初始化单选布局
        
        Args:
            text_area: 文本区域组件
        """
        super().__init__()
        self.text_area = text_area
        
        # 创建布局
        self._init_ui()
        
        # 连接信号
        self._connect_signals()
        
        # 初始隐藏
        self.model_button_hide()

    def _init_ui(self):
        """初始化UI组件"""
        # 创建一个新的水平布局用于复选框
        self.radio_layout = QHBoxLayout()

        # 设置布局的间距和边距为0，使组件紧凑排列
        self.radio_layout.setSpacing(0)
        self.radio_layout.setContentsMargins(0, 0, 0, 0)

        # 创建两个QCheckBox并添加到水平布局中
        self.deepSeek_checkbox = QCheckBox("深度思考")
        self.online_search_checkbox = QCheckBox("联网搜索")
        
        self.radio_layout.addWidget(self.deepSeek_checkbox)
        self.radio_layout.addWidget(self.online_search_checkbox)

        # 将布局设置给当前widget
        self.setLayout(self.radio_layout)
    
    def _connect_signals(self):
        """连接信号和槽"""
        self.deepSeek_checkbox.stateChanged.connect(
            lambda state: self.on_checkbox_state_changed(state)
        )
        self.online_search_checkbox.stateChanged.connect(
            lambda state: self.on_checkbox_state_changed(state)
        )

    def model_button_hide(self):
        """隐藏模型按钮"""
        self.hide()

    @Slot(int)
    def on_checkbox_state_changed(self, state):
        """处理复选框状态变化
        
        Args:
            state: 复选框状态
        """
        if self.text_area.model is None:
            return
            
        # 更新模型属性
        self.text_area.model.is_deepSeek = self.deepSeek_checkbox.isChecked()
        self.text_area.model.online_search = self.online_search_checkbox.isChecked()
        
        # 发送信号
        self.checkbox_state_changed.emit(
            self.deepSeek_checkbox.isChecked(), 
            "deepSeek"
        )
        self.checkbox_state_changed.emit(
            self.online_search_checkbox.isChecked(), 
            "online_search"
        )

    def check_models_parameters(self, models_parameters: Optional[Dict[str, Any]]) -> None:
        """检查模型参数
        
        Args:
            models_parameters: 模型参数字典
        
        Returns:
            None
        """
        if models_parameters is None:
            return
            
        # 更新模型参数
        models_parameters[common_const.is_deepSeek] = self.deepSeek_checkbox.isChecked()
        models_parameters[common_const.online_search] = self.online_search_checkbox.isChecked()
    
    def set_checkbox_state(self, is_deepSeek: bool, online_search: bool) -> None:
        """设置复选框状态
        
        Args:
            is_deepSeek: 深度思考状态
            online_search: 联网搜索状态
        
        Returns:
            None
        """
        self.deepSeek_checkbox.setChecked(is_deepSeek)
        self.online_search_checkbox.setChecked(online_search)
