import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QMovie, QIcon
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QMessageBox, QProgressBar, QVBoxLayout

# 导入日志和配置系统
from common.const.config import LoggerNames, get_logger, config_manager
from gui.MainWindow import MainWindow

# 获取根日志记录器
logger = get_logger(LoggerNames.ROOT)


@dataclass
class SplashConfig:
    """启动画面配置"""
    width: int = 600
    height: int = 400
    loading_steps: int = 5
    step_delay: float = 0.5
    final_delay: float = 1.0
    background_color: str = "#1a1a1a"
    text_color: str = "#ffffff"
    font_size: int = 16
    gif_path: str = ""  # 默认为空，后面会从配置中获取
    loading_tasks: List[Tuple[str, float]] = field(default_factory=lambda: [
        ("正在初始化基础组件...", 0.5),
        ("正在加载配置文件...", 0.5),
        ("正在初始化模型...", 0.5),
        ("正在加载用户界面...", 0.5),
        ("正在完成最终设置...", 0.5)
    ])
    timeout: int = 30000  # 30秒超时

    def __post_init__(self):
        """验证配置参数"""
        try:
            # 设置GIF路径
            if not self.gif_path and config_manager and config_manager.app_config:
                self.gif_path = config_manager.app_config.icon_paths.get("transition_gif", "")

            if self.gif_path and not Path(self.gif_path).exists():
                logger.warning(f"GIF文件不存在: {self.gif_path}")
                self.gif_path = ""

            if self.loading_steps < 1:
                raise ValueError("加载步骤数必须大于0")
            if self.step_delay < 0 or self.final_delay < 0:
                raise ValueError("延迟时间不能为负数")
            if self.timeout < 1000:  # 至少1秒
                raise ValueError("超时时间必须大于1秒")
            if len(self.loading_tasks) != self.loading_steps:
                raise ValueError("加载任务数量必须与步骤数相匹配")
        except Exception as e:
            logger.error(f"启动画面配置验证失败: {str(e)}")
            raise


class SplashScreen(QWidget):
    """启动画面"""

    def __init__(self, config: Optional[SplashConfig] = None):
        """初始化启动画面"""
        try:
            super().__init__()
            self.config = config or SplashConfig()
            self.progress_value = 0
            self._setup_ui()
            self._center_on_screen()
            self._setup_auto_close_timer()
            logger.info("启动画面初始化完成")
        except Exception as e:
            logger.error(f"启动画面初始化失败: {str(e)}")
            raise

    def _setup_ui(self):
        """初始化UI组件"""
        try:
            # 设置窗口属性
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setFixedSize(self.config.width, self.config.height)
            self.setStyleSheet(f"background-color: {self.config.background_color};")

            # 创建主布局
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # GIF 显示区域
            self.gif_label = QLabel()
            self.gif_label.setAlignment(Qt.AlignCenter)

            if self.config.gif_path and Path(self.config.gif_path).exists():
                self.movie = QMovie(self.config.gif_path)
                self.movie.setScaledSize(QSize(self.config.width, self.config.height - 80))
                self.gif_label.setMovie(self.movie)
                self.movie.start()
            else:
                # 如果没有GIF，显示文本
                self.gif_label.setText("正在启动应用程序...")
                self.gif_label.setStyleSheet(f"color: {self.config.text_color}; font-size: 24px;")
                self.movie = None

            layout.addWidget(self.gif_label)

            # 进度条
            self.progress_bar = QProgressBar()
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setStyleSheet(
                f"""
                QProgressBar {{
                    border: 2px solid {self.config.text_color};
                    border-radius: 5px;
                    background-color: {self.config.background_color};
                    height: 10px;
                    margin: 0 20px;
                }}
                QProgressBar::chunk {{
                    background-color: {self.config.text_color};
                    border-radius: 3px;
                }}
                """
            )
            layout.addWidget(self.progress_bar)

            # 进度信息
            self.progress_label = QLabel("正在启动...")
            self.progress_label.setAlignment(Qt.AlignCenter)
            self.progress_label.setStyleSheet(
                f"""
                color: {self.config.text_color}; 
                font-size: {self.config.font_size}px;
                margin: 10px;
                """
            )
            layout.addWidget(self.progress_label)

        except Exception as e:
            logger.error(f"UI初始化失败: {str(e)}\n{traceback.format_exc()}")
            raise

    def _center_on_screen(self):
        """将窗口居中显示"""
        try:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            self.move(x, y)
        except Exception as e:
            logger.error(f"窗口居中失败: {str(e)}")
            raise

    def _setup_auto_close_timer(self):
        """设置自动关闭定时器"""
        try:
            self.close_timer = QTimer(self)
            self.close_timer.setSingleShot(True)
            self.close_timer.timeout.connect(self._handle_timeout)
            self.close_timer.start(self.config.timeout)
        except Exception as e:
            logger.error(f"定时器设置失败: {str(e)}")
            raise

    def _handle_timeout(self):
        """处理加载超时"""
        logger.warning("启动画面加载超时")
        self.close_splash()
        QMessageBox.warning(
            None,
            "警告",
            "应用程序加载超时，请检查以下问题：\n"
            "1. 网络连接是否正常\n"
            "2. 系统资源是否充足\n"
            "3. 模型文件是否完整\n\n"
            "请解决问题后重试。"
        )

    def update_progress(self, value: int, message: str = ""):
        """更新进度显示"""
        try:
            self.progress_value = min(100, max(0, value))  # 确保值在0-100之间
            self.progress_bar.setValue(self.progress_value)

            if message:
                self.progress_label.setText(f"{message} ({self.progress_value}%)")
            else:
                self.progress_label.setText(f"加载进度：{self.progress_value}%")

            self.repaint()
            QApplication.processEvents()  # 确保UI更新
            logger.debug(f"更新进度: {self.progress_value}% - {message}")

        except Exception as e:
            logger.error(f"更新进度失败: {str(e)}")

    def close_splash(self):
        """关闭启动画面"""
        try:
            self.close_timer.stop()
            if self.movie:
                self.movie.stop()
            self.close()
            logger.info("启动画面已关闭")
        except Exception as e:
            logger.error(f"关闭启动画面失败: {str(e)}")

    def finish(self, widget):
        """完成启动画面并显示主窗口"""
        try:
            self.update_progress(100, "启动完成")
            QTimer.singleShot(int(self.config.final_delay * 1000), self.close_splash)
        except Exception as e:
            logger.error(f"完成启动画面失败: {str(e)}")
            self.close_splash()


class LoadingSteps:
    """加载步骤管理器"""
    def __init__(self, app_manager):
        self.app_manager = app_manager
        self.current_step = 0
        self.steps = [
            (20, "正在加载组件..."),
            (40, "正在初始化主窗口..."),
            (60, "正在准备资源..."),
            (80, "正在完成初始化..."),
            (100, "启动完成")
        ]

    def next_step(self):
        """执行下一个加载步骤"""
        if self.current_step >= len(self.steps):
            self.finish()
            return

        progress, message = self.steps[self.current_step]
        if self.app_manager.splash:
            self.app_manager.splash.update_progress(progress, message)
        
        if self.current_step == 2:  # 在适当的步骤创建主窗口
            self.app_manager.main_window = MainWindow()
        
        self.current_step += 1
        
        if self.current_step < len(self.steps):
            # 继续下一步
            QTimer.singleShot(300, self.next_step)
        else:
            # 完成所有步骤后，显示主窗口
            QTimer.singleShot(500, self.finish)

    def finish(self):
        """完成加载过程"""
        if self.app_manager.splash:
            self.app_manager.splash.close_splash()
        
        if self.app_manager.main_window:
            self.app_manager.main_window.show()
            logger.info("应用程序初始化完成")


class ApplicationManager:
    """应用程序管理器"""

    def __init__(self):
        """初始化应用程序管理器"""
        self.app = None
        self.splash = None
        self.progress_value = 0
        self.main_window = None
        self.config = None
        self.app_name = config_manager.app_config.project_name
        self.app_version = config_manager.app_config.version
        self.app_description = config_manager.app_config.description
        self.loading_steps = None
        logger.info(f"应用程序管理器初始化完成: {self.app_name} v{self.app_version}")

    def show_splash_screen(self):
        """显示启动画面"""
        try:
            # 创建启动画面配置
            splash_config = SplashConfig()

            # 获取gif路径
            if config_manager and config_manager.app_config:
                splash_config.gif_path = config_manager.app_config.icon_paths.get("transition_gif", "")

            # 创建启动画面
            self.splash = SplashScreen(splash_config)

            # 显示启动画面
            self.splash.show()

            # 处理事件，确保启动画面立即显示
            QApplication.processEvents()

            logger.info("启动画面已显示")
        except Exception as e:
            logger.error(f"显示启动画面失败: {str(e)}")
            self._show_error_message(f"显示启动画面失败: {str(e)}")

    def _show_error_message(self, message: str):
        """显示错误消息对话框"""
        try:
            # 如果QApplication已经初始化，则显示错误对话框
            if self.app and QApplication.instance():
                QMessageBox.critical(None, "错误", message)
            else:
                # 否则直接打印到控制台
                print(f"错误: {message}")

            logger.error(f"显示错误消息: {message}")
        except Exception as e:
            # 如果显示错误消息失败，则直接打印到控制台
            print(f"显示错误消息失败: {str(e)}")
            print(f"原始错误: {message}")
            logger.error(f"显示错误消息失败: {str(e)}")

    def start_loading(self):
        """开始加载过程"""
        try:
            self.loading_steps = LoadingSteps(self)
            # 延迟一点开始加载，让GIF动画先运行起来
            QTimer.singleShot(500, self.loading_steps.next_step)
        except Exception as e:
            logger.error(f"启动加载过程失败: {str(e)}")
            self._show_error_message(f"启动加载过程失败: {str(e)}")

    def run(self):
        """运行应用程序"""
        try:
            # 创建QApplication实例
            self.app = QApplication(sys.argv)
            self.app.setApplicationName(self.app_name)
            self.app.setApplicationVersion(self.app_version)

            # 设置应用程序图标
            if config_manager and config_manager.app_config:
                app_icon = config_manager.app_config.icon_paths.get("app_icon")
                if app_icon and Path(app_icon).exists():
                    self.app.setWindowIcon(QIcon(app_icon))

            # 创建启动画面
            self.show_splash_screen()

            # 开始加载过程
            self.start_loading()

            # 运行应用程序
            exit_code = self.app.exec()
            sys.exit(exit_code)

        except KeyboardInterrupt:
            logger.info("应用程序被用户中断")
            sys.exit(0)
        except Exception as e:
            logger.error(f"应用程序运行失败: {str(e)}\n{traceback.format_exc()}")
            self._show_error_message(f"应用程序运行失败: {str(e)}")
            sys.exit(1)


def main():
    """主函数"""
    try:
        # 创建应用程序管理器
        app_manager = ApplicationManager()

        # 运行应用程序
        app_manager.run()

    except Exception as e:
        logger.error(f"主函数执行失败: {str(e)}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
