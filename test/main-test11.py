from PySide6.QtCore import Signal, QObject, Slot

class Parent(QObject):
    # 定义一个名为 focusChanged 的信号
    focusChanged = Signal()

class Child(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        if isinstance(parent, Parent):
            # 通过父对象实例访问信号并进行连接
            parent.focusChanged.connect(self._on_focus_changed)

    @Slot()
    def _on_focus_changed(self):
        print("Focus changed!")

# 创建 Parent 实例
parent_instance = Parent()

# 创建 Child 实例并将 Parent 实例传递给它
child_instance = Child(parent_instance)

# 发射信号以测试连接
parent_instance.focusChanged.emit()  # 应该打印 "Focus changed!"