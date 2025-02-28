from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtCore import QUrl, Qt
import sys
import time

from gui.MainWindow import MainWindow
from common.const.common_const import common_const

class VideoSplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(800, 450)  # 设定窗口大小
        self.setStyleSheet("background-color: black;")  # 背景颜色

        # 创建视频播放器
        self.media_player = QMediaPlayer()
        self.video_widget = QVideoWidget(self)
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)

        layout = QVBoxLayout()
        layout.addWidget(self.video_widget)
        self.setLayout(layout)

        # 加载视频
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.setSource(QUrl.fromLocalFile(common_const.transition_main_video))  # MP4 视频路径
        self.media_player.play()

        # 监听视频播放结束
        self.media_player.mediaStatusChanged.connect(self.video_finished)

    def video_finished(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.close_splash()

    def close_splash(self):
        self.media_player.stop()
        self.close()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 创建视频过渡页
    splash = VideoSplashScreen()
    splash.show()
    app.processEvents()

    # 模拟加载过程
    for i in range(1, 6):
        time.sleep(0.5)
        app.processEvents()

    # 加载主窗口
    main_window = MainWindow()
    splash.close_splash()  # 关闭 SplashScreen
    main_window.show()

    sys.exit(app.exec())
