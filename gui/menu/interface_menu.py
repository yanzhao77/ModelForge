import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Dict, Any, Tuple, TYPE_CHECKING

import aiohttp
from PySide6.QtCore import Slot, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog, QMessageBox,
    QFileDialog, QProgressDialog, QMenu
)

from common.const.common_const import LoggerNames, get_logger, ModelType
from gui.dialog.interface_manager_dialog import InterfaceManagerDialog
from gui.menu.resource_menu import ResourceParameters

# 避免循环导入，使用TYPE_CHECKING条件导入
if TYPE_CHECKING:
    pass

logger = get_logger(LoggerNames.UI)


class InterfaceType(Enum):
    """接口类型枚举"""
    LOCAL = auto()
    OPENAI = auto()
    AZURE = auto()
    ANTHROPIC = auto()
    XINGHUO = auto()
    CUSTOM = auto()


class InterfaceStatus(Enum):
    """接口状态枚举"""
    UNKNOWN = auto()
    ONLINE = auto()
    OFFLINE = auto()
    ERROR = auto()
    TESTING = auto()


@dataclass
class InterfaceAction:
    """接口动作配置类"""
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
class InterfaceMenuConfig:
    """接口菜单配置"""
    actions: Dict[str, InterfaceAction] = field(default_factory=lambda: {
        "add": InterfaceAction(
            name="add",
            text="添加接口",
            shortcut="Ctrl+N",
            tooltip="添加新接口",
            status_tip="添加新的API接口",
            icon=":/icons/add.png"
        ),
        "edit": InterfaceAction(
            name="edit",
            text="编辑接口",
            shortcut="Ctrl+E",
            tooltip="编辑选中接口",
            status_tip="编辑当前选中的接口",
            icon=":/icons/edit.png"
        ),
        "remove": InterfaceAction(
            name="remove",
            text="删除接口",
            shortcut="Delete",
            tooltip="删除选中接口",
            status_tip="删除当前选中的接口",
            icon=":/icons/delete.png"
        ),
        "test": InterfaceAction(
            name="test",
            text="测试接口",
            shortcut="Ctrl+T",
            tooltip="测试接口连接",
            status_tip="测试当前选中接口的连接",
            icon=":/icons/test.png"
        ),
        "monitor": InterfaceAction(
            name="monitor",
            text="监控",
            shortcut="Ctrl+M",
            tooltip="监控接口状态",
            status_tip="监控所有接口的状态",
            icon=":/icons/monitor.png",
            checkable=True
        ),
        "refresh": InterfaceAction(
            name="refresh",
            text="刷新",
            shortcut="F5",
            tooltip="刷新接口列表",
            status_tip="刷新当前接口列表",
            icon=":/icons/refresh.png"
        ),
        "import": InterfaceAction(
            name="import",
            text="导入配置",
            tooltip="导入接口配置",
            status_tip="从文件导入接口配置",
            icon=":/icons/import.png"
        ),
        "export": InterfaceAction(
            name="export",
            text="导出配置",
            tooltip="导出接口配置",
            status_tip="将接口配置导出到文件",
            icon=":/icons/export.png"
        )
    })

    max_recent_interfaces: int = 5
    config_file_path: str = os.path.join(os.path.dirname(__file__), "interface_config.json")
    monitor_interval: int = 300  # 监控间隔（秒）
    test_timeout: int = 10  # 测试超时时间（秒）


@dataclass
class InterfaceParameters(ResourceParameters):
    """接口参数数据类"""
    model_name: str = "gpt-3.5-turbo"
    model_type: str = ModelType.INTERFACE.value # 非默认参数应放在最前面
    parameters_editable: bool = True
    api_key: str = ""
    api_base: str = ""
    api_type: str = InterfaceType.OPENAI.name

    timeout: int = 30
    proxy: str = ""
    max_tokens: int = 500
    temperature: float = 0.7
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    status: str = InterfaceStatus.UNKNOWN.name
    last_test_time: str = ""
    last_test_result: str = ""


    def __post_init__(self):
        """验证参数"""
        try:
            if not self.api_key and self.api_type != InterfaceType.LOCAL.name:
                raise ValueError("API密钥不能为空")
            if not self.api_base and self.api_type != InterfaceType.LOCAL.name:
                raise ValueError("API基础URL不能为空")
            if self.timeout <= 0:
                raise ValueError("超时时间必须大于0")
            if not 0 <= self.temperature <= 2:
                raise ValueError("temperature必须在0-2之间")
            if not 0 <= self.top_p <= 1:
                raise ValueError("top_p必须在0-1之间")
            if not -2 <= self.presence_penalty <= 2:
                raise ValueError("presence_penalty必须在-2到2之间")
            if not -2 <= self.frequency_penalty <= 2:
                raise ValueError("frequency_penalty必须在-2到2之间")

            # 验证接口类型
            try:
                InterfaceType[self.api_type]
            except KeyError:
                raise ValueError(f"不支持的接口类型: {self.api_type}")

            # 验证接口状态
            try:
                InterfaceStatus[self.status]
            except KeyError:
                self.status = InterfaceStatus.UNKNOWN.name
        except Exception as e:
            logger.error(f"接口参数验证失败: {str(e)}")
            raise

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        try:
            return {
                "api_key": self.api_key,
                "api_base": self.api_base,
                "api_type": self.api_type,
                "model_name": self.model_name,
                "timeout": self.timeout,
                "proxy": self.proxy,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "status": self.status,
                "last_test_time": self.last_test_time,
                "last_test_result": self.last_test_result
            }
        except Exception as e:
            logger.error(f"转换参数字典失败: {str(e)}")
            raise

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InterfaceParameters':
        """从字典创建实例"""
        try:
            return cls(
                api_key=data.get("api_key", ""),
                api_base=data.get("api_base", ""),
                api_type=data.get("api_type", InterfaceType.OPENAI.name),
                model_name=data.get("model_name", "gpt-3.5-turbo"),
                timeout=data.get("timeout", 30),
                proxy=data.get("proxy", ""),
                max_tokens=data.get("max_tokens", 500),
                temperature=data.get("temperature", 0.7),
                top_p=data.get("top_p", 1.0),
                presence_penalty=data.get("presence_penalty", 0.0),
                frequency_penalty=data.get("frequency_penalty", 0.0),
                status=data.get("status", InterfaceStatus.UNKNOWN.name),
                last_test_time=data.get("last_test_time", ""),
                last_test_result=data.get("last_test_result", "")
            )
        except Exception as e:
            logger.error(f"从字典创建参数实例失败: {str(e)}")
            raise


class InterfaceMenu(QMenu):
    """接口菜单"""
    
    interface_changed = Signal()
    
    def __init__(self, parent=None):
        """初始化接口菜单"""
        super().__init__("接口(&I)", parent)
        self.parent_window = parent  # 使用parent而不是直接引用MainWindow
        self.parameters = {}  # 添加参数字典
        self._setup_actions()
        
    def _setup_actions(self):
        """设置菜单动作"""
        try:
            # 管理接口
            self.manage_action = QAction("管理接口(&M)", self)
            self.manage_action.setShortcut("Ctrl+I")
            self.manage_action.triggered.connect(self._show_interface_manager)
            self.addAction(self.manage_action)
            
            # 分隔线
            self.addSeparator()
            
            # 添加接口
            self.add_action = QAction("添加接口(&A)", self)
            self.add_action.triggered.connect(self._add_interface)
            self.addAction(self.add_action)
            
            # 修改接口
            self.edit_action = QAction("修改接口(&E)", self)
            self.edit_action.triggered.connect(self._edit_interface)
            self.addAction(self.edit_action)
            
            # 删除接口
            self.delete_action = QAction("删除接口(&D)", self)
            self.delete_action.triggered.connect(self._delete_interface)
            self.addAction(self.delete_action)
            
            # 分隔线
            self.addSeparator()
            
            # 刷新接口列表
            self.refresh_action = QAction("刷新接口列表(&R)", self)
            self.refresh_action.triggered.connect(self._refresh_interfaces)
            self.addAction(self.refresh_action)
            
            logger.debug("接口菜单初始化完成")
            
        except Exception as e:
            logger.error(f"接口菜单初始化失败: {str(e)}")
            raise

    def _show_interface_manager(self):
        """显示接口管理器"""
        try:
            # 这里导入InterfaceManagerDialog以避免循环导入
            try:
                from gui.dialog.interface_manager_dialog import InterfaceManagerDialog
                dialog = InterfaceManagerDialog(self)
                dialog.exec()
            except ImportError:
                QMessageBox.warning(self, "提示", "接口管理器模块未找到")
        except Exception as e:
            logger.error(f"显示接口管理器失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"显示接口管理器失败: {str(e)}")

    def _add_interface(self):
        """添加接口"""
        try:
            QMessageBox.information(self, "提示", "添加接口功能正在开发中")
        except Exception as e:
            logger.error(f"添加接口失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"添加接口失败: {str(e)}")

    def _edit_interface(self):
        """编辑接口"""
        try:
            QMessageBox.information(self, "提示", "编辑接口功能正在开发中")
        except Exception as e:
            logger.error(f"编辑接口失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"编辑接口失败: {str(e)}")

    def _delete_interface(self):
        """删除接口"""
        try:
            QMessageBox.information(self, "提示", "删除接口功能正在开发中")
        except Exception as e:
            logger.error(f"删除接口失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"删除接口失败: {str(e)}")

    def _refresh_interfaces(self):
        """刷新接口列表"""
        try:
            QMessageBox.information(self, "提示", "刷新接口列表功能正在开发中")
        except Exception as e:
            logger.error(f"刷新接口列表失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"刷新接口列表失败: {str(e)}")
            
    def _init_menu_state(self):
        """初始化菜单状态"""
        try:
            # 更新动作状态
            self._update_action_states()
            logger.debug("菜单状态初始化完成")
        except Exception as e:
            logger.error(f"菜单状态初始化失败: {str(e)}")
            
    def _update_action_states(self):
        """更新动作状态"""
        try:
            has_interface = hasattr(self.parent_window, 'select_interface_name') and bool(self.parent_window.select_interface_name)
            
            # 更新操作按钮的启用状态
            self.manage_action.setEnabled(True)  # 管理接口始终可用
            self.add_action.setEnabled(True)     # 添加接口始终可用
            self.edit_action.setEnabled(has_interface)
            self.delete_action.setEnabled(has_interface)
            self.refresh_action.setEnabled(True) # 刷新接口始终可用
            
            logger.debug(f"动作状态已更新: 接口选中状态={has_interface}")
        except Exception as e:
            logger.error(f"更新动作状态失败: {str(e)}")
            raise

    def _show_status_message(self, message: str, timeout: int = 3000):
        """显示状态栏消息"""
        try:
            self.parent_window.statusBar().showMessage(message, timeout)
            logger.debug(f"显示状态消息: {message}")
        except Exception as e:
            logger.error(f"显示状态消息失败: {str(e)}")

    def handle_error(self, message: str, detail: str = ""):
        """统一错误处理"""
        try:
            error_msg = f"{message}\n{detail}" if detail else message
            QMessageBox.critical(self, "错误", error_msg)
            self._show_status_message(f"错误: {message}")
            logger.error(f"错误处理: {error_msg}")
        except Exception as e:
            logger.error(f"错误处理失败: {str(e)}")

    def _add_basic_actions(self):
        """添加基本操作"""
        try:
            # 添加基本动作
            for action_key in ["add", "edit", "remove"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    action.shortcut,
                    tooltip=action.tooltip,
                    status_tip=action.status_tip,
                    icon=action.icon
                )

            self.add_separator()

            # 添加测试和监控动作
            for action_key in ["test", "monitor"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    action.shortcut,
                    tooltip=action.tooltip,
                    status_tip=action.status_tip,
                    icon=action.icon,
                    checkable=action.checkable
                )

            self.add_separator()

            # 添加刷新动作
            action = self.config.actions["refresh"]
            self.add_action(
                action.name,
                action.text,
                self._handle_refresh,
                action.shortcut,
                tooltip=action.tooltip,
                status_tip=action.status_tip,
                icon=action.icon
            )

            logger.debug("添加基本操作完成")
        except Exception as e:
            logger.error(f"添加基本操作失败: {str(e)}")
            raise

    def _add_additional_actions(self):
        """添加额外操作"""
        try:
            self.add_separator()

            # 添加导入导出动作
            for action_key in ["import", "export"]:
                action = self.config.actions[action_key]
                self.add_action(
                    action.name,
                    action.text,
                    getattr(self, f"_handle_{action.name}"),
                    tooltip=action.tooltip,
                    status_tip=action.status_tip,
                    icon=action.icon
                )

            logger.debug("添加额外操作完成")
        except Exception as e:
            logger.error(f"添加额外操作失败: {str(e)}")
            raise

    async def _test_interface(self, name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
        """测试接口连接"""
        try:
            api_type = InterfaceType[params["api_type"]]

            # 根据接口类型选择测试方法
            if api_type == InterfaceType.LOCAL:
                return True, "本地接口无需测试"

            # 设置代理
            proxy = params.get("proxy")
            if proxy:
                os.environ["http_proxy"] = proxy
                os.environ["https_proxy"] = proxy

            # 准备请求头
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {params['api_key']}"
            }

            # 准备测试URL
            test_urls = {
                InterfaceType.OPENAI: f"{params['api_base']}/models",
                InterfaceType.AZURE: f"{params['api_base']}/openai/deployments?api-version=2023-05-15",
                InterfaceType.ANTHROPIC: f"{params['api_base']}/v1/models",
                InterfaceType.XINGHUO: f"{params['api_base']}/v1/models",
                InterfaceType.CUSTOM: params['api_base']
            }

            test_url = test_urls.get(api_type)
            if not test_url:
                return False, f"不支持的接口类型: {api_type}"

            # 发送测试请求
            timeout = aiohttp.ClientTimeout(total=params.get("timeout", 30))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(test_url, headers=headers) as response:
                    if response.status == 200:
                        return True, "连接成功"
                    else:
                        return False, f"HTTP错误: {response.status}"

        except asyncio.TimeoutError:
            return False, "连接超时"
        except Exception as e:
            return False, f"测试失败: {str(e)}"
        finally:
            # 清除代理设置
            if proxy:
                os.environ.pop("http_proxy", None)
                os.environ.pop("https_proxy", None)

    def _update_interface_status(self, name: str, success: bool, message: str):
        """更新接口状态"""
        try:
            if name not in self.parameters:
                return

            params = self.parameters[name]
            params["status"] = InterfaceStatus.ONLINE.name if success else InterfaceStatus.ERROR.name
            params["last_test_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            params["last_test_result"] = message

            self._save_config()
            self._update_action_states()

            status_text = "在线" if success else "离线"
            self._show_status_message(f"接口 {name} {status_text}: {message}")
            logger.info(f"接口 {name} 状态更新: {status_text} ({message})")
        except Exception as e:
            logger.error(f"更新接口状态失败: {str(e)}")
            raise

    @Slot()
    def _handle_add(self):
        """处理添加接口动作"""
        try:
            dialog = InterfaceManagerDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                params = dialog.get_parameters()
                name = params.pop("name")
                self.parameters[name] = InterfaceParameters(**params).to_dict()
                self._save_config()
                self._show_status_message(f"已添加接口: {name}")
                logger.info(f"已添加接口: {name}")
        except Exception as e:
            logger.error(f"添加接口失败: {str(e)}")
            self.handle_error("添加接口失败", str(e))

    @Slot()
    def _handle_edit(self):
        """处理编辑接口动作"""
        try:
            if not self.parent_window.select_interface_name:
                QMessageBox.warning(self, "提示", "请先选择接口")
                return

            name = self.parent_window.select_interface_name
            params = self.parameters.get(name)
            if not params:
                return

            dialog = InterfaceManagerDialog(self, params)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_params = dialog.get_parameters()
                self.parameters[name].update(new_params)
                self._save_config()
                self._show_status_message(f"已更新接口: {name}")
                logger.info(f"已更新接口: {name}")
        except Exception as e:
            logger.error(f"编辑接口失败: {str(e)}")
            self.handle_error("编辑接口失败", str(e))

    @Slot()
    def _handle_remove(self):
        """处理删除接口动作"""
        try:
            if not self.parent_window.select_interface_name:
                QMessageBox.warning(self, "提示", "请先选择接口")
                return

            name = self.parent_window.select_interface_name
            reply = QMessageBox.question(
                self,
                "确认",
                f"确定要删除接口 {name} 吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                del self.parameters[name]
                self._save_config()
                self._show_status_message(f"已删除接口: {name}")
                logger.info(f"已删除接口: {name}")
        except Exception as e:
            logger.error(f"删除接口失败: {str(e)}")
            self.handle_error("删除接口失败", str(e))

    @Slot()
    def _handle_test(self):
        """处理测试接口动作"""
        try:
            if not self.parent_window.select_interface_name:
                QMessageBox.warning(self, "提示", "请先选择接口")
                return

            name = self.parent_window.select_interface_name
            params = self.parameters.get(name)
            if not params:
                return

            # 更新状态为测试中
            params["status"] = InterfaceStatus.TESTING.name
            self._update_action_states()
            self._show_status_message(f"正在测试接口: {name}")

            # 创建进度对话框
            progress = QProgressDialog("正在测试接口...", "取消", 0, 0, self)
            progress.setWindowTitle("测试接口")
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            # 执行测试
            loop = asyncio.get_event_loop()
            success, message = loop.run_until_complete(self._test_interface(name, params))

            # 更新状态
            self._update_interface_status(name, success, message)

            # 关闭进度对话框
            progress.close()

            # 显示测试结果
            icon = QMessageBox.Information if success else QMessageBox.Critical
            QMessageBox.information(self, "测试结果", message, icon)

        except Exception as e:
            logger.error(f"测试接口失败: {str(e)}")
            self.handle_error("测试接口失败", str(e))

    @Slot()
    def _handle_monitor(self, checked: bool):
        """处理监控动作"""
        try:
            if checked:
                interval = self.config.monitor_interval * 1000  # 转换为毫秒
                self.monitor_timer.start(interval)
                self._show_status_message("已启动接口监控")
                logger.info("接口监控已启动")
            else:
                self.monitor_timer.stop()
                self._show_status_message("已停止接口监控")
                logger.info("接口监控已停止")
        except Exception as e:
            logger.error(f"切换监控状态失败: {str(e)}")
            self.handle_error("切换监控状态失败", str(e))

    @Slot()
    def _monitor_interfaces(self):
        """监控所有接口"""
        try:
            for name, params in self.parameters.items():
                # 跳过本地接口
                if params["api_type"] == InterfaceType.LOCAL.name:
                    continue

                # 执行测试
                loop = asyncio.get_event_loop()
                success, message = loop.run_until_complete(self._test_interface(name, params))

                # 更新状态
                self._update_interface_status(name, success, message)

            logger.debug("接口监控完成")
        except Exception as e:
            logger.error(f"接口监控失败: {str(e)}")
            self.handle_error("接口监控失败", str(e))

    def _load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config.config_file_path):
                with open(self.config.config_file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    for name, params in config_data.items():
                        self.parameters[name] = InterfaceParameters.from_dict(params).to_dict()
            logger.debug("配置加载完成")
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")
            self.handle_error("加载配置失败", str(e))

    def _save_config(self):
        """保存配置"""
        try:
            with open(self.config.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.parameters, f, indent=4, ensure_ascii=False)
            logger.debug("配置保存完成")
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            self.handle_error("保存配置失败", str(e))

    @Slot()
    def _handle_refresh(self):
        """处理刷新动作"""
        try:
            self._load_config()
            self._show_status_message("接口列表已刷新")
            logger.info("已刷新接口列表")
        except Exception as e:
            logger.error(f"刷新列表失败: {str(e)}")
            self.handle_error("刷新列表失败", str(e))

    @Slot()
    def _handle_import(self):
        """处理导入配置动作"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "导入配置",
                "",
                "JSON文件 (*.json)"
            )

            if file_path:
                with open(file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    for name, params in config_data.items():
                        self.parameters[name] = InterfaceParameters.from_dict(params).to_dict()
                self._save_config()
                self._show_status_message("配置导入完成")
                logger.info(f"已导入配置: {file_path}")
        except Exception as e:
            logger.error(f"导入配置失败: {str(e)}")
            self.handle_error("导入配置失败", str(e))

    @Slot()
    def _handle_export(self):
        """处理导出配置动作"""
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出配置",
                "",
                "JSON文件 (*.json)"
            )

            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.parameters, f, indent=4, ensure_ascii=False)
                self._show_status_message("配置导出完成")
                logger.info(f"已导出配置: {file_path}")
        except Exception as e:
            logger.error(f"导出配置失败: {str(e)}")
            self.handle_error("导出配置失败", str(e))

    def load_default_resource(self) -> Dict[str, Any]:
        """加载默认资源"""
        try:
            return InterfaceParameters(
                api_type=InterfaceType.LOCAL.name,
                model_name="默认接口",
                status=InterfaceStatus.ONLINE.name
            ).to_dict()
        except Exception as e:
            logger.error(f"加载默认资源失败: {str(e)}")
            raise
