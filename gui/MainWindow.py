import os
import sys

from PySide6.QtCore import Qt, Slot, SLOT, Signal
from PySide6.QtGui import QIcon, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QApplication, QStatusBar, QMessageBox, QToolBar
)

# 自定义模块导入
from common.const.config import get_logger, LoggerNames, config_manager
from common.const.common_const import Constants

logger = get_logger(LoggerNames.UI)

# 使用延迟导入，在MainWindow类初始化后导入菜单
# 这样可以避免循环导入

class MainWindow(QMainWindow):
    """主窗口"""
    focusChanged = Signal()  # 添加信号

    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        logger.info("开始初始化主窗口")

        # 初始化常量
        self.constants = Constants()
        
        # 初始化属性
        self.select_interface_name = ""


        # 初始化菜单和状态栏
        self._init_ui()

        # 设置窗口属性
        self._set_window_properties()

        # 创建主布局
        self._create_main_layout()

        # 创建中心组件
        self._create_central_widget()

        # 创建菜单栏
        self._create_menu_bar()

        # 创建状态栏
        self._create_status_bar()

        # 加载配置
        self._load_config()

        # 连接信号槽
        self._connect_signals()

        # 初始化完成
        logger.info("主窗口初始化完成")

    def _init_ui(self):
        """初始化UI"""
        # 在这里初始化UI组件

        pass

    def focusInEvent(self, event):
        super(MainWindow, self).focusInEvent(event)
        self.focusChanged.emit()  # 当窗口获得焦点时发出信号

    def focusOutEvent(self, event):
        super(MainWindow, self).focusOutEvent(event)
        self.focusChanged.emit()  # 当窗口失去焦点时发出信号

    def _set_window_properties(self):
        """设置窗口属性"""
        # 设置窗口标题
        self.setWindowTitle(config_manager.app_config.window_title)

        # 设置窗口图标
        if config_manager and hasattr(config_manager, 'app_config'):
            icon_path = config_manager.app_config.icon_paths.get("app_icon")
            if icon_path and os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        
        # 设置窗口大小
        self.resize(1200, 800)
        
        # 设置窗口最小大小
        self.setMinimumSize(800, 600)
        
        # 设置窗口居中
        self.center()
        
    def center(self):
        """使窗口居中显示"""
        frame_geometry = self.frameGeometry()
        screen_center = self.screen().availableGeometry().center()
        frame_geometry.moveCenter(screen_center)
        self.move(frame_geometry.topLeft())
    
    def _create_main_layout(self):
        """创建主布局"""
        # 创建主布局
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(5)
        
    def _create_central_widget(self):
        """创建中心组件"""
        # 创建中心组件
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.main_layout)
        
        # 设置中心组件
        self.setCentralWidget(self.central_widget)
        
    def _create_menu_bar(self):
        """创建菜单栏"""
        self.menu_bar = self.menuBar()

        try:
            # 导入各个菜单模块
            # from gui.menu.edit_menu import EditMenu
            # from gui.menu.view_menu import ViewMenu
            from gui.menu.model_menu import ModelMenu
            from gui.menu.interface_menu import InterfaceMenu
            # from gui.menu.tools_menu import ToolsMenu
            from gui.menu.help_menu import HelpMenu

            # 创建各个菜单
            # self.edit_menu = EditMenu(self.menu_bar, self)
            self.model_menu = ModelMenu(self.menu_bar, self)
            self.interface_menu = InterfaceMenu(self)
            self.help_menu = HelpMenu(self.menu_bar, self)

            # 添加各个菜单到菜单栏
            # self.menu_bar.addMenu(self.edit_menu)
            # self.menu_bar.addMenu(self.model_menu)
            self.menu_bar.addMenu(self.interface_menu)
            self.menu_bar.addMenu(self.help_menu)
            
            logger.debug("菜单栏创建完成")
        except Exception as e:
            logger.error(f"创建菜单栏失败: {str(e)}")
            raise

    def _create_status_bar(self):
        """创建状态栏"""
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 设置状态栏消息
        self.status_bar.showMessage("就绪")

        logger.debug("状态栏创建完成")

    def _load_config(self):
        """加载配置"""
        try:
            # 在这里加载配置
            pass
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")

    def _connect_signals(self):
        """连接信号槽"""
        try:

            # 在这里连接信号槽
            pass
        except Exception as e:
            logger.error(f"连接信号槽失败: {str(e)}")

    def _load_saved_state(self) -> None:
        """加载保存的状态"""
        try:
            if hasattr(self, 'settings') and (state_data := self.settings.value("windowState")):
                if hasattr(self, 'state'):
                    self.state = self.state.from_dict(state_data)

                    if hasattr(self.state, 'window_geometry'):
                        self.resize(self.state.window_geometry)
                    if hasattr(self.state, 'window_position'):
                        self.move(self.state.window_position)
                    if hasattr(self, 'splitter') and hasattr(self.state, 'splitter_sizes'):
                        self.splitter.setSizes(self.state.splitter_sizes)

            logger.info("窗口状态加载成功")
        except Exception as e:
            logger.warning(f"加载窗口状态失败: {str(e)}")

    def _save_state(self) -> None:
        """保存当前状态"""
        try:
            if hasattr(self, 'state'):
                self.state.window_geometry = self.size()
                self.state.window_position = self.pos()
                if hasattr(self, 'splitter'):
                    self.state.splitter_sizes = self.splitter.sizes()

                if hasattr(self, 'settings'):
                    self.settings.setValue("windowState", self.state.to_dict())
                logger.info("窗口状态保存成功")
        except Exception as e:
            logger.error(f"保存窗口状态失败: {str(e)}")

    def closeEvent(self, event: QCloseEvent) -> None:
        """重写关闭事件，保存窗口状态"""
        try:
            self._save_state()
            super().closeEvent(event)
        except Exception as e:
            logger.error(f"关闭事件处理失败: {str(e)}")
            event.accept()

    @Slot()
    def print(self, text: str) -> None:
        """打印文本到文本区域"""
        try:
            if hasattr(self, 'text_area'):
                self.text_area.print(text)
                self.status_bar.showMessage(f"已打印: {text[:30]}...")
        except Exception as e:
            logger.error(f"打印文本失败: {str(e)}")
            self.status_bar.showMessage("打印失败")

    @Slot()
    def input(self, text: str) -> None:
        """输入文本到文本区域"""
        try:
            if hasattr(self, 'text_area'):
                self.text_area.input(text)
                self.status_bar.showMessage(f"已输入: {text[:30]}...")
        except Exception as e:
            logger.error(f"输入文本失败: {str(e)}")
            self.status_bar.showMessage("输入失败")

    @Slot()
    def tree_clear(self) -> None:
        """清空树视图"""
        try:
            if hasattr(self, 'tree_view'):
                self.tree_view.tree_clear()
                self.status_bar.showMessage("树视图已清空")
        except Exception as e:
            logger.error(f"清空树视图失败: {str(e)}")
            self.status_bar.showMessage("清空树视图失败")

    def load_model_ui(self) -> None:
        """加载模型UI"""
        try:
            if hasattr(self, 'model_menu'):
                self.model_menu.open_model()
                self.status_bar.showMessage("正在加载模型...")
        except Exception as e:
            logger.error(f"加载模型失败: {str(e)}")
            self.status_bar.showMessage("加载模型失败")
            QMessageBox.critical(self, "错误", f"加载模型失败: {str(e)}")

    def stop_model(self) -> None:
        """停止模型"""
        try:
            if hasattr(self, 'text_area'):
                self.text_area.stop_model()
                self.status_bar.showMessage("模型已停止")
        except Exception as e:
            logger.error(f"停止模型失败: {str(e)}")
            self.status_bar.showMessage("停止模型失败")

    def clear_ui(self) -> None:
        """清空UI"""
        try:
            self.tree_clear()
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setVisible(False)
                self.progress_bar.setValue(0)
            if hasattr(self, 'text_area'):
                self.text_area.clear()
            self.status_bar.showMessage("界面已清空")
        except Exception as e:
            logger.error(f"清空界面失败: {str(e)}")
            self.status_bar.showMessage("清空界面失败")

    def exit_ui(self) -> None:
        """退出应用程序"""
        try:
            self._save_state()
            QApplication.instance().quit()
        except Exception as e:
            logger.error(f"退出程序失败: {str(e)}")
            sys.exit(1)

    def restart(self) -> None:
        """重启应用程序"""
        try:
            self._save_state()
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
            logger.error(f"重启程序失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"重启程序失败: {str(e)}")
