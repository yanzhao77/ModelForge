from PySide6.QtWidgets import QMenuBar, QAction
from PySide6.QtCore import Slot

from common.const.common_const import LoggerNames, get_logger
from .base_menu import BaseMenu

logger = get_logger(LoggerNames.UI)

@dataclass
class PluginInfo:
    """插件信息数据类"""
    name: str
    version: str
    description: str
    author: str
    enabled: bool = True

@dataclass
class PluginMenuConfig:
    """插件菜单配置数据类"""
    plugins: Dict[str, PluginInfo] = field(default_factory=dict)
    plugin_dir: str = "plugins"
    auto_load: bool = True

class PluginMenu(BaseMenu):
    """插件菜单类"""
    
    def __init__(self, menu_bar, main_window):
        super().__init__(menu_bar, main_window, "插件")
        self.main_window = main_window
        self.config = PluginMenuConfig()
        self._load_plugins()
        
    def _setup_menu(self):
        """设置菜单项"""
        try:
            # 基本操作
            self.add_action("add", "添加", self.insert_plugin)
            self.add_action("load", "加载插件", self.load_plugin)
            self.add_action("manage", "插件管理", self.plugins_management)
            
            # 添加插件列表子菜单
            self.plugins_list_menu = self.add_submenu("InstalledPlugins","已安装插件")
            self.add_separator()
            
            # 添加刷新动作
            self.add_action("refresh", "刷新", self.refresh_plugins)
            
            logger.info("插件菜单初始化完成")
        except Exception as e:
            logger.error(f"设置插件菜单失败: {str(e)}")
            raise

    def _load_plugins(self):
        """加载插件配置"""
        try:
            # TODO: 实现插件配置加载逻辑
            logger.info("插件配置加载完成")
        except Exception as e:
            logger.error(f"加载插件配置失败: {str(e)}")
            self.handle_error("加载插件配置失败")

    @Slot()
    def insert_plugin(self):
        """添加新插件"""
        try:
            # TODO: 实现插件添加逻辑
            logger.info("开始添加新插件")
            QMessageBox.information(
                self.menu,
                "提示",
                "插件添加功能正在开发中..."
            )
        except Exception as e:
            logger.error(f"添加插件失败: {str(e)}")
            self.handle_error("添加插件失败")

    @Slot()
    def load_plugin(self):
        """加载插件"""
        try:
            # TODO: 实现插件加载逻辑
            logger.info("开始加载插件")
            QMessageBox.information(
                self.menu,
                "提示",
                "插件加载功能正在开发中..."
            )
        except Exception as e:
            logger.error(f"加载插件失败: {str(e)}")
            self.handle_error("加载插件失败")

    @Slot()
    def plugins_management(self):
        """管理插件"""
        try:
            # TODO: 实现插件管理逻辑
            logger.info("打开插件管理界面")
            QMessageBox.information(
                self.menu,
                "提示",
                "插件管理功能正在开发中..."
            )
        except Exception as e:
            logger.error(f"打开插件管理失败: {str(e)}")
            self.handle_error("打开插件管理失败")

    def clear_plugin_list(self):
        """清空插件列表"""
        try:
            self.main_window.clear_ui()
            self.plugins_list_menu.clear()
            self.config.plugins.clear()
            logger.info("已清空插件列表")
        except Exception as e:
            logger.error(f"清空插件列表失败: {str(e)}")
            self.handle_error("清空插件列表失败")

    def update_plugin_list(self):
        """更新插件列表"""
        try:
            self.plugins_list_menu.clear()
            
            if not self.config.plugins:
                self.add_action(
                    "no_plugins",
                    "无已安装插件",
                    enabled=False
                )
                return
                
            for name, info in self.config.plugins.items():
                self.add_action(
                    f"plugin_{name}",
                    f"{name} v{info.version}",
                    lambda checked, n=name: self._toggle_plugin(n),
                    checkable=True,
                    checked=info.enabled
                )
                
            logger.info("已更新插件列表")
        except Exception as e:
            logger.error(f"更新插件列表失败: {str(e)}")
            self.handle_error("更新插件列表失败")

    def _toggle_plugin(self, plugin_name: str):
        """切换插件启用状态"""
        try:
            if plugin := self.config.plugins.get(plugin_name):
                plugin.enabled = not plugin.enabled
                logger.info(f"插件 {plugin_name} 已{'启用' if plugin.enabled else '禁用'}")
        except Exception as e:
            logger.error(f"切换插件状态失败: {str(e)}")
            self.handle_error("切换插件状态失败")

    @Slot()
    def refresh_plugins(self):
        """刷新插件"""
        try:
            self._load_plugins()
            self.update_plugin_list()
            logger.info("插件已刷新")
        except Exception as e:
            logger.error(f"刷新插件失败: {str(e)}")
            self.handle_error("刷新插件失败")
