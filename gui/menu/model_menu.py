import os
from dataclasses import dataclass, field
from typing import Dict, Any, List

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QMenuBar, QDialog, QMessageBox
)

from common.const.common_const import common_const, LoggerNames, get_logger, ModelType
from common.const.config import config_manager
from gui.dialog.download_model_dialog import DownloadModelMainWindow
from gui.dialog.model_open_dialog import ModelOpenDialog
from gui.dialog.model_parameters_dialog import ModelParametersDialog
from .resource_menu import ResourceMenu, ResourceParameters

logger = get_logger(LoggerNames.UI)

@dataclass
class MenuAction:
    """菜单动作配置类"""
    name: str
    text: str
    shortcut: str = ""
    tooltip: str = ""
    status_tip: str = ""
    icon: str = ""
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    visible: bool = True

@dataclass
class ModelMenuConfig:
    """模型菜单配置"""
    actions: Dict[str, MenuAction] = field(default_factory=lambda: {
        "reset": MenuAction(
            name="reset",
            text="重置列表",
            tooltip="重置模型列表",
            status_tip="重置为默认模型列表"
        ),
        "open": MenuAction(
            name="open",
            text="打开模型",
            shortcut="Ctrl+O",
            tooltip="打开本地模型",
            status_tip="从本地加载模型"
        ),
        "refresh": MenuAction(
            name="refresh",
            text="刷新",
            shortcut="F5",
            tooltip="刷新模型列表",
            status_tip="刷新当前模型列表"
        ),
        "clear": MenuAction(
            name="clear",
            text="清空",
            tooltip="清空模型列表",
            status_tip="清空当前模型列表"
        ),
        "parameters": MenuAction(
            name="parameters",
            text="模型参数",
            shortcut="Ctrl+P",
            tooltip="设置模型参数",
            status_tip="设置当前模型的参数"
        ),
        "download": MenuAction(
            name="download",
            text="下载模型",
            tooltip="下载新模型",
            status_tip="从网络下载新模型"
        ),
        "restart": MenuAction(
            name="restart",
            text="重启",
            tooltip="重启应用",
            status_tip="重新启动应用程序"
        ),
        "exit": MenuAction(
            name="exit",
            text="退出",
            shortcut="Alt+F4",
            tooltip="退出应用",
            status_tip="退出应用程序"
        )
    })
    
    max_recent_models: int = 10
    default_model_path: str = os.path.join(os.path.dirname(__file__), "models")

@dataclass
class LocalModelParameters(ResourceParameters):
    """模型参数数据类"""
    model_name: str = "gpt-3.5-turbo"
    model_path: str = config_manager.app_config.default_model_path # 非默认参数应放在最前面
    model_type: str = ModelType.LOCAL.value  # 默认参数
    max_tokens: int = 500
    do_sample: bool = True
    temperature: float = 0.9
    top_k: int = 50
    input_max_length: int = 2048
    parameters_editable: bool = True
    interface_message_dict: List[Dict[str, Any]] = field(default_factory=list)
    repetition_penalty: float = 1.2
    is_deepSeek: bool = False
    online_search: bool = False
    
    def __post_init__(self):
        """验证参数"""
        try:
            if not self.model_path:
                raise ValueError("模型路径不能为空")
            if not os.path.exists(self.model_path):
                raise ValueError(f"模型路径不存在: {self.model_path}")
            if self.max_tokens <= 0:
                raise ValueError("max_tokens必须大于0")
            if not 0 <= self.temperature <= 2:
                raise ValueError("temperature必须在0-2之间")
            if self.top_k <= 0:
                raise ValueError("top_k必须大于0")
            if self.input_max_length <= 0:
                raise ValueError("input_max_length必须大于0")
            if self.repetition_penalty < 1:
                raise ValueError("repetition_penalty必须大于等于1")
        except Exception as e:
            logger.error(f"模型参数验证失败: {str(e)}")
            raise

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        try:
            return {
                common_const.model_name: self.model_name,
                common_const.model_path: self.model_path,
                common_const.model_type: self.model_type,
                common_const.max_tokens: self.max_tokens,
                common_const.do_sample: self.do_sample,
                common_const.temperature: self.temperature,
                common_const.top_k: self.top_k,
                common_const.input_max_length: self.input_max_length,
                common_const.parameters_editable: self.parameters_editable,
                common_const.interface_message_dict: self.interface_message_dict,
                common_const.repetition_penalty: self.repetition_penalty,
                common_const.is_deepSeek: self.is_deepSeek,
                common_const.online_search: self.online_search
            }
        except Exception as e:
            logger.error(f"转换参数字典失败: {str(e)}")
            raise
            
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LocalModelParameters':
        """从字典创建实例"""
        try:
            return cls(
                model_name=data.get(common_const.model_name),
                model_path=data.get(common_const.model_path),
                model_type=data.get(common_const.model_type, ModelType.LOCAL.value),
                max_tokens=data.get(common_const.max_tokens, 500),
                do_sample=data.get(common_const.do_sample, True),
                temperature=data.get(common_const.temperature, 0.9),
                top_k=data.get(common_const.top_k, 50),
                input_max_length=data.get(common_const.input_max_length, 2048),
                parameters_editable=data.get(common_const.parameters_editable, True),
                interface_message_dict=data.get(common_const.interface_message_dict, []),
                repetition_penalty=data.get(common_const.repetition_penalty, 1.2),
                is_deepSeek=data.get(common_const.is_deepSeek, False),
                online_search=data.get(common_const.online_search, False)
            )
        except Exception as e:
            logger.error(f"从字典创建参数实例失败: {str(e)}")
            raise

class ModelMenu(ResourceMenu):
    """模型菜单类"""
    
    def __init__(self, menu_bar: QMenuBar, mainWindow):
        """
        初始化模型菜单
        
        Args:
            menu_bar: 菜单栏
            mainWindow: 主窗口
        """
        try:
            self.config = ModelMenuConfig()
            super().__init__(menu_bar, mainWindow, "模型")
            self.main_window = mainWindow
            self.api = None
            self.api_on_flag = False
            self.status_bar = mainWindow.statusBar() if hasattr(mainWindow, 'statusBar') else None
            
            # 初始化状态
            self._init_api_state()
            self._init_menu_state()
            
            logger.debug("模型菜单初始化完成")
        except Exception as e:
            logger.error(f"模型菜单初始化失败: {str(e)}")
            raise

    def _init_menu_state(self):
        """初始化菜单状态"""
        try:
            self._update_action_states()
            logger.debug("菜单状态初始化完成")
        except Exception as e:
            logger.error(f"菜单状态初始化失败: {str(e)}")
            raise

    def _update_action_states(self):
        """更新动作状态"""
        try:
            has_model = hasattr(self.main_window, 'select_model_name') and bool(self.main_window.select_model_name)
            if "parameters" in self.actions:
                self.actions["parameters"].setEnabled(has_model)
            if "clear" in self.actions:
                self.actions["clear"].setEnabled(has_model)
            logger.debug(f"动作状态已更新: 模型选中状态={has_model}")
        except Exception as e:
            logger.error(f"更新动作状态失败: {str(e)}")
            raise

    def _show_status_message(self, message: str, timeout: int = 3000):
        """显示状态栏消息"""
        try:
            if self.status_bar:
                self.status_bar.showMessage(message, timeout)
                logger.debug(f"显示状态消息: {message}")
        except Exception as e:
            logger.error(f"显示状态消息失败: {str(e)}")

    def handle_error(self, message: str, detail: str = ""):
        """统一错误处理"""
        try:
            error_msg = f"{message}\n{detail}" if detail else message
            QMessageBox.critical(self.menu, "错误", error_msg)
            self._show_status_message(f"错误: {message}")
            logger.error(f"错误处理: {error_msg}")
        except Exception as e:
            logger.error(f"错误处理失败: {str(e)}")

    def _add_basic_actions(self):
        """添加基本操作"""
        try:
            # 添加基本动作
            for action_key in ["reset", "open"]:
                action = self.config.actions[action_key]
                action_handler = getattr(self, f"_handle_{action.name}", None)
                if callable(action_handler):  # 确认处理函数是可调用的
                    self.add_action(
                        action.name,
                        action.text,
                        action_handler,
                        action.shortcut,
                        tooltip=action.tooltip,
                        status_tip=action.status_tip
                    )
            
            # 最近模型子菜单
            self.recent_menu = self.add_submenu("recent", "最近使用")
            self.recent_menu.aboutToShow.connect(self._handle_recent_menu_show)
            
            self.add_separator()
            
            # 添加刷新动作
            action = self.config.actions["refresh"]
            self.add_action(
                action.name,
                action.text,
                self._handle_refresh,
                action.shortcut,
                tooltip=action.tooltip,
                status_tip=action.status_tip
            )
            
            self.add_separator()
            
            # 添加清空动作
            action = self.config.actions["clear"]
            self.add_action(
                action.name,
                action.text,
                self._handle_clear,
                tooltip=action.tooltip,
                status_tip=action.status_tip
            )
            
            self.add_separator()
            
            # 添加参数设置动作
            action = self.config.actions["parameters"]
            self.add_action(
                action.name,
                action.text,
                self._handle_parameters,
                action.shortcut,
                tooltip=action.tooltip,
                status_tip=action.status_tip
            )
            
            self.add_separator()
            
            # 添加下载模型动作
            action = self.config.actions["download"]
            self.add_action(
                action.name,
                action.text,
                self._handle_download,
                tooltip=action.tooltip,
                status_tip=action.status_tip
            )
            
            logger.debug("添加基本操作完成")
        except Exception as e:
            logger.error(f"添加基本操作失败: {str(e)}")
            raise

    def _add_additional_actions(self):
        """添加额外操作"""
        try:
            # API选项子菜单
            api_menu = self.add_submenu("api", "API选项")
            self.action_group = QActionGroup(self.menu)
            self.action_group.setExclusive(True)
            
            # 添加API开关动作
            self.api_on_action = self.add_action(
                "api_on",
                "开放API",
                tooltip="启用API服务",
                status_tip="启用API服务，允许外部访问",
                checkable=True,
                checked=False,
                menu=api_menu,
            )
            
            self.api_off_action = self.add_action(
                "api_off",
                "关闭API",
                tooltip="关闭API服务",
                status_tip="关闭API服务，禁止外部访问",
                checkable=True,
                checked=True,
                menu = api_menu,
            )
            
            self.action_group.addAction(self.api_on_action)
            self.action_group.addAction(self.api_off_action)
            
            # 确保传递的是可调用对象
            self.action_group.triggered.connect(self._handle_api_toggle)
            
            self.add_separator()
            
            # 添加重启和退出动作
            for action_key in ["restart", "exit"]:
                action = self.config.actions[action_key]
                action_handler = getattr(self, f"_handle_{action.name}", None)
                if callable(action_handler):  # 确认处理函数是可调用的
                    self.add_action(
                        action.name,
                        action.text,
                        action_handler,
                        action.shortcut,
                        tooltip=action.tooltip,
                        status_tip=action.status_tip
                    )
                
            logger.debug("添加额外操作完成")
        except Exception as e:
            logger.error(f"添加额外操作失败: {str(e)}")
            raise

    def _init_api_state(self):
        """初始化API状态"""
        try:
            # 从配置文件或其他地方加载API状态
            self.api_on_flag = False  # 默认关闭
            logger.debug("API状态初始化完成")
        except Exception as e:
            logger.error(f"API状态初始化失败: {str(e)}")
            raise

    @Slot()
    def _handle_reset(self):
        """处理重置动作"""
        try:
            reply = QMessageBox.question(
                self.menu,
                "确认",
                "确定要重置模型列表吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes and hasattr(self.main_window, 'tree_clear') and hasattr(self.main_window, 'tree_view'):
                self.main_window.tree_clear()
                self.main_window.tree_view.load_default_model_for_treeview()
                self._show_status_message("模型列表已重置")
                logger.info("已重置模型列表")
        except Exception as e:
            logger.error(f"重置列表失败: {str(e)}")
            self.handle_error("重置列表失败", str(e))

    @Slot()
    def _handle_open(self):
        """处理打开模型动作"""
        try:
            dialog = ModelOpenDialog(self.menu)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if dialog.model_name and dialog.model_path:
                    self.setting_model_default_parameters(dialog.model_name, dialog.model_path)
                    if hasattr(self.main_window, 'tree_view'):
                        self.main_window.tree_view.load_model(dialog.model_name, dialog.model_path)
                        logger.info(f"已加载模型: {dialog.model_name}")
        except Exception as e:
            logger.error(f"打开模型失败: {str(e)}")
            self.handle_error("打开模型失败")

    @Slot()
    def _handle_refresh(self):
        """处理刷新动作"""
        try:
            if hasattr(self.main_window, 'tree_view') and hasattr(self.main_window.tree_view, 'refresh'):
                self.main_window.tree_view.refresh()
                logger.info("已刷新模型列表")
        except Exception as e:
            logger.error(f"刷新列表失败: {str(e)}")
            self.handle_error("刷新列表失败")

    @Slot()
    def _handle_clear(self):
        """处理清空动作"""
        try:
            self.clear_resource_list()
            logger.info("已清空模型列表")
        except Exception as e:
            logger.error(f"清空列表失败: {str(e)}")
            self.handle_error("清空列表失败")

    @Slot()
    def _handle_parameters(self):
        """处理参数设置动作"""
        try:
            if not hasattr(self.main_window, 'select_model_name') or not self.main_window.select_model_name:
                QMessageBox.warning(self.menu, "提示", "请先选择模型")
                return

            parameters = self.parameters.get(self.main_window.select_model_name)
            if parameters is None or parameters[common_const.model_type] == ModelType.INTERFACE.value:
                return

            dialog = ModelParametersDialog(
                self.menu,
                parameters,
                self.main_window.select_model_name
            )
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.parameters[self.main_window.select_model_name].update(dialog.get_parameters())
                logger.info(f"已更新模型参数: {self.main_window.select_model_name}")
                
        except Exception as e:
            logger.error(f"设置参数失败: {str(e)}")
            self.handle_error("设置参数失败")

    @Slot()
    def _handle_download(self):
        """处理下载模型动作"""
        try:
            dialog = DownloadModelMainWindow()
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_model = dialog.selected_models
                logger.info(f"已选择下载模型: {selected_model}")
        except Exception as e:
            logger.error(f"下载模型失败: {str(e)}")
            self.handle_error("下载模型失败")

    @Slot(QAction)
    def _handle_api_toggle(self, action: QAction):
        """处理API开关切换"""
        try:
            self.api_on_flag = self.api_on_action.isChecked()
            # 避免在模块导入时可能出现的循环导入问题
            if self.api is None and hasattr(self.main_window, 'text_area'):
                from interface.api_interface_fastapi import FastAPIChatCompletionResource
                self.api = FastAPIChatCompletionResource(
                    self.api_on_flag,
                    self.main_window.text_area
                )
                if hasattr(self.api, 'thread_run') and callable(self.api.thread_run):
                    self.api.thread_run()
                    logger.info(f"API状态已切换: {'开启' if self.api_on_flag else '关闭'}")
        except Exception as e:
            logger.error(f"切换API状态失败: {str(e)}")
            self.handle_error("切换API状态失败")

    @Slot()
    def _handle_restart(self):
        """处理重启动作"""
        try:
            if hasattr(self.main_window, 'restart') and callable(self.main_window.restart):
                self.main_window.restart()
                logger.info("程序正在重启")
        except Exception as e:
            logger.error(f"重启程序失败: {str(e)}")
            self.handle_error("重启程序失败")

    @Slot()
    def _handle_exit(self):
        """处理退出动作"""
        try:
            if hasattr(self.main_window, 'exit_ui') and callable(self.main_window.exit_ui):
                self.main_window.exit_ui()
                logger.info("程序正常退出")
        except Exception as e:
            logger.error(f"退出程序失败: {str(e)}")
            self.handle_error("退出程序失败")

    @Slot()
    def _handle_recent_menu_show(self):
        """处理显示最近模型菜单"""
        try:
            if hasattr(self, 'update_recent_list') and callable(self.update_recent_list):
                self.update_recent_list()
                logger.debug("已更新最近模型列表")
        except Exception as e:
            logger.error(f"更新最近模型列表失败: {str(e)}")
            self.handle_error("更新最近模型列表失败")

    def _populate_recent_list(self):
        """填充最近模型列表"""
        try:
            self.recent_menu.clear()
            if hasattr(self.main_window, 'recent_models'):
                for model_name in self.main_window.recent_models[:self.config.max_recent_models]:
                    # 使用lambda创建回调函数，确保它是可调用对象
                    action = self.add_action(
                        f"recent_{model_name}",
                        model_name,
                        lambda checked=False, name=model_name: self._load_recent_model(name)
                    )
                    self.recent_menu.addAction(action)
                logger.debug("已填充最近模型列表")
        except Exception as e:
            logger.error(f"填充最近模型列表失败: {str(e)}")
            raise

    def _load_recent_model(self, model_name: str):
        """加载最近使用的模型"""
        try:
            if model_name not in self.parameters:
                logger.error(f"模型参数不存在: {model_name}")
                self.handle_error("加载失败", f"模型参数不存在: {model_name}")
                return
                
            model_path = self.parameters[model_name][common_const.model_path]
            if not os.path.exists(model_path):
                self.handle_error(
                    "加载失败",
                    f"模型文件不存在: {model_path}"
                )
                return
            
            if hasattr(self.main_window, 'tree_view') and hasattr(self.main_window.tree_view, 'load_model'):
                self.main_window.tree_view.load_model(model_name, model_path)
                self._show_status_message(f"已加载模型: {model_name}")
                self._update_action_states()
                logger.info(f"已加载最近模型: {model_name}")
        except Exception as e:
            logger.error(f"加载最近模型失败: {str(e)}")
            self.handle_error("加载最近模型失败", str(e))

    def load_default_resource(self) -> Dict[str, Any]:
        """加载默认资源"""
        try:
            return self.setting_model_default_parameters(
                "默认模型",
                os.path.join(self.config.default_model_path, "default_model")
            )
        except Exception as e:
            logger.error(f"加载默认资源失败: {str(e)}")
            raise

    def setting_model_default_parameters(self, model_name: str, folder_path: str) -> Dict[str, Any]:
        """设置模型默认参数"""
        try:
            parameters = LocalModelParameters(
                model_name=model_name,
                model_path=folder_path
            )
            self.parameters[model_name] = parameters.to_dict()
            self._update_action_states()
            self._show_status_message(f"已设置模型参数: {model_name}")
            logger.debug(f"已设置模型默认参数: {model_name}")
            return self.parameters[model_name]
        except Exception as e:
            logger.error(f"设置模型默认参数失败: {str(e)}")
            raise
