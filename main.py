import sys

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen
from PySide6.QtCore import Qt, QTimer

from common.const.common_const import common_const
from gui.MainWindow import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(common_const.icon_main_view))

    splash_pix = QPixmap(common_const.transition_main_view)
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # 用全局变量保存主窗口
    def start_main():
        global main_window
        main_window = MainWindow()
        main_window.show()
        splash.finish(main_window)

    timer = QTimer()
    timer.timeout.connect(start_main)
    timer.setSingleShot(True)
    timer.start(2000)

    sys.exit(app.exec())

