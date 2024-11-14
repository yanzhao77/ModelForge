import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from common.const.common_const import common_const
from qt6.MainWindow import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # 设置应用图标
    app.setWindowIcon(QIcon(common_const.icon_main_view))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
