import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from common.const.common_const import common_const
from common.const.config import config_manager
from gui.MainWindow import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 设置应用图标
    app_icon = config_manager.app_config.icon_paths.get("app_icon")
    app.setWindowIcon(QIcon(app_icon))

    # 创建 Splash Screen（可以换成你的启动图片）
    splash_pixmap = QPixmap(config_manager.app_config.icon_paths.get("transition"))
    splash = QSplashScreen(splash_pixmap)
    splash.showMessage("正在加载，请稍候...", Qt.AlignBottom | Qt.AlignHCenter, Qt.black)
    splash.show()

    # 处理事件循环，避免卡顿
    app.processEvents()

    # 模拟加载过程
    for i in range(1, 6):
        time.sleep(0.5)  # 这里可以替换为实际的初始化逻辑
        splash.showMessage(f"加载进度：{i * 20}%", Qt.AlignBottom | Qt.AlignHCenter, Qt.black)
        app.processEvents()

    # 创建主窗口
    window = MainWindow()

    # 关闭 Splash Screen，显示主窗口
    splash.finish(window)
    window.show()

    sys.exit(app.exec())
