"""
ModelForge 主程序入口（支持会话管理和记忆系统）
"""
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from common.const.common_const import common_const
from gui.SessionMainWindow import SessionMainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置应用图标
    app.setWindowIcon(QIcon(common_const.icon_main_view))
    
    # 创建 Splash Screen
    splash_pixmap = QPixmap(common_const.transition_main_view)
    splash = QSplashScreen(splash_pixmap)
    splash.showMessage("正在初始化数据库...", Qt.AlignBottom | Qt.AlignHCenter, Qt.black)
    splash.show()
    
    # 处理事件循环
    app.processEvents()
    
    # 模拟加载过程
    loading_steps = [
        "初始化数据库...",
        "加载用户配置...",
        "准备模型环境...",
        "启动会话管理...",
        "完成初始化..."
    ]
    
    for i, step in enumerate(loading_steps):
        time.sleep(0.3)
        splash.showMessage(step, Qt.AlignBottom | Qt.AlignHCenter, Qt.black)
        app.processEvents()
    
    # 创建主窗口
    window = SessionMainWindow()
    
    # 关闭 Splash Screen，显示主窗口
    splash.finish(window)
    window.show()
    
    sys.exit(app.exec())
