from PyQt6.QtWidgets import QMenuBar


class file_menu(QMenuBar):
    def __init__(self,menu_Bar=QMenuBar):
        super().__init__()
        file_menu = menu_Bar.addMenu('文件')
        file_menu.addAction("新建")
        file_menu.addAction('打开文件')
        file_menu.addMenu('最近文件')
        file_menu.addSeparator()
        # file_menu.addAction(QAction('清空', self))
        # file_menu.addAction(QAction('保存', self))
        # file_menu.addAction(QAction('另存为', self))
        file_menu.addAction('刷新')
        file_menu.addSeparator()
        # script_menu = QMenu('自动化脚本', self)
        # script_menu.addAction(QAction('脚本执行', self))
        # script_menu.addAction(QAction('录制脚本', self))
        # file_menu.addMenu(script_menu)
        file_menu.addSeparator()
        file_menu.addAction('退出')
