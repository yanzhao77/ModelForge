import logging
from typing import Dict, Any
from dataclasses import dataclass, field
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QCheckBox, QSpinBox, QComboBox, QPushButton,
    QTabWidget, QWidget, QFormLayout, QMenuBar, QAction
)

from common.const.common_const import common_const, LoggerNames, get_logger
from .base_menu import BaseMenu

logger = get_logger(LoggerNames.UI)

@dataclass
class AppSettings:
    """应用程序设置数据类"""
    # 常规设置
    auto_save: bool = True
    auto_save_interval: int = 5  # 分钟
    show_line_numbers: bool = True
    theme: str = "light"
    language: str = "zh_CN"
    
    # 模型设置
    default_model_path: str = common_const.default_model_path
    auto_load_last_model: bool = True
    max_recent_models: int = 10
    
    # 接口设置
    api_timeout: int = 60
    api_retry_count: int = 3
    api_concurrent_limit: int = 5
    
    # 插件设置
    enable_plugins: bool = True
    auto_update_plugins: bool = True
    plugin_safe_mode: bool = True

class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, parent: QWidget = None, settings: AppSettings = None):
        super().__init__(parent)
        self.settings = settings or AppSettings()
        self._setup_ui()
        
    def _setup_ui(self):
        """设置UI"""
        try:
            self.setWindowTitle("设置")
            self.setMinimumWidth(500)
            
            layout = QVBoxLayout()
            
            # 创建选项卡
            tab_widget = QTabWidget()
            tab_widget.addTab(self._create_general_tab(), "常规")
            tab_widget.addTab(self._create_model_tab(), "模型")
            tab_widget.addTab(self._create_interface_tab(), "接口")
            tab_widget.addTab(self._create_plugin_tab(), "插件")
            
            layout.addWidget(tab_widget)
            layout.addWidget(self._create_button_box())
            
            self.setLayout(layout)
            logger.debug("设置对话框UI初始化完成")
            
        except Exception as e:
            logger.error(f"设置对话框UI初始化失败: {str(e)}")
            raise
            
    def _create_general_tab(self) -> QWidget:
        """创建常规设置选项卡"""
        try:
            tab = QWidget()
            layout = QFormLayout()
            
            # 自动保存
            self.auto_save_cb = QCheckBox()
            self.auto_save_cb.setChecked(self.settings.auto_save)
            layout.addRow("自动保存:", self.auto_save_cb)
            
            # 自动保存间隔
            self.save_interval_sb = QSpinBox()
            self.save_interval_sb.setRange(1, 60)
            self.save_interval_sb.setValue(self.settings.auto_save_interval)
            layout.addRow("保存间隔(分钟):", self.save_interval_sb)
            
            # 显示行号
            self.line_numbers_cb = QCheckBox()
            self.line_numbers_cb.setChecked(self.settings.show_line_numbers)
            layout.addRow("显示行号:", self.line_numbers_cb)
            
            # 主题
            self.theme_cb = QComboBox()
            self.theme_cb.addItems(["浅色", "深色", "系统"])
            self.theme_cb.setCurrentText("浅色" if self.settings.theme == "light" else "深色")
            layout.addRow("主题:", self.theme_cb)
            
            # 语言
            self.language_cb = QComboBox()
            self.language_cb.addItems(["简体中文", "English"])
            self.language_cb.setCurrentText("简体中文" if self.settings.language == "zh_CN" else "English")
            layout.addRow("语言:", self.language_cb)
            
            tab.setLayout(layout)
            return tab
            
        except Exception as e:
            logger.error(f"创建常规设置选项卡失败: {str(e)}")
            raise
            
    def _create_model_tab(self) -> QWidget:
        """创建模型设置选项卡"""
        try:
            tab = QWidget()
            layout = QFormLayout()
            
            # 默认模型路径
            self.model_path_label = QLabel(self.settings.default_model_path)
            layout.addRow("默认模型路径:", self.model_path_label)
            
            # 自动加载上次模型
            self.auto_load_cb = QCheckBox()
            self.auto_load_cb.setChecked(self.settings.auto_load_last_model)
            layout.addRow("自动加载上次模型:", self.auto_load_cb)
            
            # 最近模型数量
            self.recent_count_sb = QSpinBox()
            self.recent_count_sb.setRange(0, 50)
            self.recent_count_sb.setValue(self.settings.max_recent_models)
            layout.addRow("最近模型数量:", self.recent_count_sb)
            
            tab.setLayout(layout)
            return tab
            
        except Exception as e:
            logger.error(f"创建模型设置选项卡失败: {str(e)}")
            raise
            
    def _create_interface_tab(self) -> QWidget:
        """创建接口设置选项卡"""
        try:
            tab = QWidget()
            layout = QFormLayout()
            
            # API超时时间
            self.timeout_sb = QSpinBox()
            self.timeout_sb.setRange(10, 300)
            self.timeout_sb.setValue(self.settings.api_timeout)
            layout.addRow("API超时(秒):", self.timeout_sb)
            
            # 重试次数
            self.retry_sb = QSpinBox()
            self.retry_sb.setRange(0, 10)
            self.retry_sb.setValue(self.settings.api_retry_count)
            layout.addRow("重试次数:", self.retry_sb)
            
            # 并发限制
            self.concurrent_sb = QSpinBox()
            self.concurrent_sb.setRange(1, 20)
            self.concurrent_sb.setValue(self.settings.api_concurrent_limit)
            layout.addRow("并发限制:", self.concurrent_sb)
            
            tab.setLayout(layout)
            return tab
            
        except Exception as e:
            logger.error(f"创建接口设置选项卡失败: {str(e)}")
            raise
            
    def _create_plugin_tab(self) -> QWidget:
        """创建插件设置选项卡"""
        try:
            tab = QWidget()
            layout = QFormLayout()
            
            # 启用插件
            self.enable_plugins_cb = QCheckBox()
            self.enable_plugins_cb.setChecked(self.settings.enable_plugins)
            layout.addRow("启用插件:", self.enable_plugins_cb)
            
            # 自动更新插件
            self.auto_update_cb = QCheckBox()
            self.auto_update_cb.setChecked(self.settings.auto_update_plugins)
            layout.addRow("自动更新插件:", self.auto_update_cb)
            
            # 安全模式
            self.safe_mode_cb = QCheckBox()
            self.safe_mode_cb.setChecked(self.settings.plugin_safe_mode)
            layout.addRow("插件安全模式:", self.safe_mode_cb)
            
            tab.setLayout(layout)
            return tab
            
        except Exception as e:
            logger.error(f"创建插件设置选项卡失败: {str(e)}")
            raise
            
    def _create_button_box(self) -> QWidget:
        """创建按钮框"""
        try:
            widget = QWidget()
            layout = QHBoxLayout()
            
            # 确定按钮
            ok_button = QPushButton("确定")
            ok_button.clicked.connect(self.accept)
            
            # 取消按钮
            cancel_button = QPushButton("取消")
            cancel_button.clicked.connect(self.reject)
            
            # 应用按钮
            apply_button = QPushButton("应用")
            apply_button.clicked.connect(self._apply_settings)
            
            layout.addStretch()
            layout.addWidget(ok_button)
            layout.addWidget(cancel_button)
            layout.addWidget(apply_button)
            
            widget.setLayout(layout)
            return widget
            
        except Exception as e:
            logger.error(f"创建按钮框失败: {str(e)}")
            raise
            
    def _apply_settings(self):
        """应用设置"""
        try:
            # 更新设置
            self.settings.auto_save = self.auto_save_cb.isChecked()
            self.settings.auto_save_interval = self.save_interval_sb.value()
            self.settings.show_line_numbers = self.line_numbers_cb.isChecked()
            self.settings.theme = "light" if self.theme_cb.currentText() == "浅色" else "dark"
            self.settings.language = "zh_CN" if self.language_cb.currentText() == "简体中文" else "en_US"
            
            self.settings.auto_load_last_model = self.auto_load_cb.isChecked()
            self.settings.max_recent_models = self.recent_count_sb.value()
            
            self.settings.api_timeout = self.timeout_sb.value()
            self.settings.api_retry_count = self.retry_sb.value()
            self.settings.api_concurrent_limit = self.concurrent_sb.value()
            
            self.settings.enable_plugins = self.enable_plugins_cb.isChecked()
            self.settings.auto_update_plugins = self.auto_update_cb.isChecked()
            self.settings.plugin_safe_mode = self.safe_mode_cb.isChecked()
            
            logger.info("已应用新设置")
            
        except Exception as e:
            logger.error(f"应用设置失败: {str(e)}")
            raise
            
    def get_settings(self) -> AppSettings:
        """获取设置"""
        return self.settings

class SettingsMenu(BaseMenu):
    """设置菜单类"""
    
    def __init__(self, menu_bar, parent):
        super().__init__(menu_bar, parent, "设置")
        self.settings = AppSettings()
        
    def _setup_menu(self):
        """设置菜单项"""
        try:
            self.add_action(
                "preferences",
                "首选项",
                self.show_settings_dialog,
                "Ctrl+,"
            )
            logger.info("设置菜单初始化完成")
        except Exception as e:
            logger.error(f"设置菜单初始化失败: {str(e)}")
            raise
            
    @Slot()
    def show_settings_dialog(self):
        """显示设置对话框"""
        try:
            dialog = SettingsDialog(self.menu, self.settings)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.settings = dialog.get_settings()
                self._apply_settings()
                logger.info("已更新应用程序设置")
        except Exception as e:
            logger.error(f"显示设置对话框失败: {str(e)}")
            self.handle_error("显示设置对话框失败")
            
    def _apply_settings(self):
        """应用设置到应用程序"""
        try:
            # TODO: 实现设置应用逻辑
            pass
        except Exception as e:
            logger.error(f"应用设置失败: {str(e)}")
            self.handle_error("应用设置失败") 