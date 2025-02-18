from PyQt6.QtWidgets import QWidget, QHBoxLayout, QCheckBox

from common.const.common_const import common_const


class RadioLayout(QWidget):
    def __init__(self, text_area):
        super().__init__()
        self.text_area = text_area
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

        # 监听复选框的变化（如果需要）
        self.deepSeek_checkbox.stateChanged.connect(self.on_checkbox_state_changed)
        self.online_search_checkbox.stateChanged.connect(self.on_checkbox_state_changed)

    def on_checkbox_state_changed(self, state):
        if self.text_area.model is None:
            return
        self.text_area.model.is_deepSeek = self.deepSeek_checkbox.isChecked()
        self.text_area.model.online_search = self.online_search_checkbox.isChecked()

    def check_models_parameters(self, models_parameters):
        if models_parameters is None:
            return
        models_parameters[common_const.is_deepSeek] = self.deepSeek_checkbox.isChecked()
        models_parameters[common_const.online_search] = self.online_search_checkbox.isChecked()
