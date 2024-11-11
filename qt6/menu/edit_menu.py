from PyQt6.QtWidgets import QMenuBar


class edit_menu(QMenuBar):
    def __init__(self,menu_Bar=QMenuBar):
        super().__init__()
        edit_menu = menu_Bar.addMenu('编辑')
        edit_menu.addAction('Undo')
        edit_menu.addAction('Redo')
        edit_menu.addSeparator()
        edit_menu.addAction('Cut')
        edit_menu.addAction('Copy')
        edit_menu.addAction('Paste')
        edit_menu.addAction('Delete')
        edit_menu.addSeparator()
        edit_menu.addAction('Select All')
        edit_menu.addAction('Unselect All')
