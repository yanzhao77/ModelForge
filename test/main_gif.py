import sys
import time
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from common.const.common_const import common_const
from gui.MainWindow import MainWindow

class LoadMainWindowThread(QThread):
    """ 负责加载 MainWindow 的线程 """
    progress = Signal(int)  # 进度信号
    finished = Signal()  # 加载完成信号

    def run(self):
        """ 模拟主窗口加载 """
        for i in range(1, 6):  # 进度 0% → 100%
            time.sleep(0.5)  # 模拟加载
            self.progress.emit(i * 20)  # 发送进度信号
        time.sleep(1)  # 100% 时停顿 1 秒
        self.main_window = MainWindow()  # 加载主窗口
        self.finished.emit()  # 发送加载完成信号

class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(600, 400)
        self.setStyleSheet("background-color: black;")

        # GIF 显示
        self.label = QLabel(self)
        self.label.setGeometry(0, 0, 600, 350)
        self.label.setAlignment(Qt.AlignCenter)
        self.movie = QMovie(common_const.transition_main_gif)
        self.label.setMovie(self.movie)
        self.movie.start()  # 播放 GIF

        # 进度信息
        self.progress_label = QLabel("加载进度：0%", self)
        self.progress_label.setGeometry(0, 350, 600, 50)
        self.progress_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.progress_label.setStyleSheet("color: white; font-size: 16px;")

    def update_progress(self, value):
        """ 更新进度显示 """
        self.progress_label.setText(f"加载进度：{value}%")
        self.repaint()

    def close_splash(self):
        self.movie.stop()
        self.close()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 创建 GIF 过渡页
    splash = SplashScreen()
    splash.show()
    app.processEvents()  # 确保 GIF 和进度信息流畅更新

    # 创建并启动加载主窗口的线程
    load_thread = LoadMainWindowThread()

    def on_load_finished():
        main_window = load_thread.main_window  # 获取主窗口实例
        main_window.show()  # 显示主窗口
        splash.close_splash()  # 关闭过渡页

    load_thread.progress.connect(splash.update_progress)  # 连接进度信号
    load_thread.finished.connect(lambda: QTimer.singleShot(100, on_load_finished))  # 100% 后延迟 1 秒
    load_thread.start()  # 开始加载主窗口

    sys.exit(app.exec())
