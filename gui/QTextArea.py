from typing import Optional, Union, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import (
    QKeyEvent, QTextCursor, QPainter, QColor, 
    QTextCharFormat, QSyntaxHighlighter, QFont
)
from PySide6.QtWidgets import QTextEdit

from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.UI)

class SyntaxHighlighter(QSyntaxHighlighter):
    """语法高亮器"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._formats = {}
        self._init_formats()
        
    def _init_formats(self) -> None:
        """初始化格式"""
        try:
            # 代码块格式
            code_format = QTextCharFormat()
            code_format.setBackground(QColor("#f8f8f8"))
            code_format.setForeground(QColor("#333333"))
            code_format.setFontFamily("Consolas")
            self._formats["code"] = code_format
            
            # 关键字格式
            keyword_format = QTextCharFormat()
            keyword_format.setForeground(QColor("#0000FF"))
            keyword_format.setFontWeight(QFont.Weight.Bold)
            self._formats["keyword"] = keyword_format
            
            # 字符串格式
            string_format = QTextCharFormat()
            string_format.setForeground(QColor("#008000"))
            self._formats["string"] = string_format
            
        except Exception as e:
            logger.error(f"初始化格式失败: {str(e)}")
            
    def highlightBlock(self, text: str) -> None:
        """高亮文本块"""
        try:
            # 简单的代码块检测
            if text.strip().startswith("```") or text.strip().startswith("'''"):
                self.setFormat(0, len(text), self._formats["code"])
                return
                
            # 简单的关键字检测
            keywords = ["def", "class", "import", "from", "return", "if", "else", "try", "except"]
            for keyword in keywords:
                index = text.find(keyword)
                while index >= 0:
                    self.setFormat(index, len(keyword), self._formats["keyword"])
                    index = text.find(keyword, index + 1)
                    
            # 简单的字符串检测
            in_string = False
            start = 0
            for i, char in enumerate(text):
                if char in ['"', "'"]:
                    if not in_string:
                        start = i
                        in_string = True
                    else:
                        self.setFormat(start, i - start + 1, self._formats["string"])
                        in_string = False
                        
        except Exception as e:
            logger.error(f"高亮文本块失败: {str(e)}")

class QTextArea(QTextEdit):
    """自定义文本编辑器"""
    
    # 定义信号
    submitTextSignal = Signal(str)
    textChanged = Signal()
    cursorPositionChanged = Signal(int, int)  # 行号，列号

    def __init__(self, *args, **kwargs):
        """初始化文本编辑器"""
        try:
            super().__init__(*args, **kwargs)
            
            # 设置基本属性
            self.setAcceptRichText(True)
            self.setUndoRedoEnabled(True)
            self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            
            # 设置默认字体
            font = QFont("Microsoft YaHei", 10)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            self.setFont(font)
            
            # 添加语法高亮
            self.highlighter = SyntaxHighlighter(self.document())
            
            # 连接信号
            self.textChanged.connect(self._on_text_changed)
            self.cursorPositionChanged.connect(self._on_cursor_position_changed)
            
            logger.info("文本编辑器初始化完成")
            
        except Exception as e:
            logger.error(f"文本编辑器初始化失败: {str(e)}")
            raise

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """处理按键事件"""
        try:
            # 处理回车键
            if event.key() in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
                if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                    # Shift + Enter: 插入换行
                    self.insertPlainText("\n")
                else:
                    # Enter: 提交文本
                    self.submit_text()
                event.accept()
                return
                
            # 处理Tab键
            if event.key() == Qt.Key.Key_Tab:
                if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                    # Shift + Tab: 减少缩进
                    self._unindent()
                else:
                    # Tab: 增加缩进
                    self._indent()
                event.accept()
                return
                
            # 其他按键：调用父类处理
            super().keyPressEvent(event)
            
        except Exception as e:
            logger.error(f"处理按键事件失败: {str(e)}")
            event.accept()

    def submit_text(self) -> None:
        """提交文本"""
        try:
            text = self.toPlainText().strip()
            if text:
                self.submitTextSignal.emit(text)
                logger.debug(f"提交文本: {text[:100]}...")
        except Exception as e:
            logger.error(f"提交文本失败: {str(e)}")

    def _indent(self) -> None:
        """增加缩进"""
        try:
            cursor = self.textCursor()
            if cursor.hasSelection():
                # 选中多行时，对每行进行缩进
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                text = cursor.selectedText()
                indented_text = "    " + text.replace("\n", "\n    ")
                cursor.insertText(indented_text)
            else:
                # 未选中文本时，插入4个空格
                cursor.insertText("    ")
        except Exception as e:
            logger.error(f"增加缩进失败: {str(e)}")

    def _unindent(self) -> None:
        """减少缩进"""
        try:
            cursor = self.textCursor()
            if cursor.hasSelection():
                # 选中多行时，对每行减少缩进
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                text = cursor.selectedText()
                unindented_text = text.replace("\n    ", "\n").replace("    ", "", 1)
                cursor.insertText(unindented_text)
            else:
                # 未选中文本时，删除当前行开头的空格（最多4个）
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                for _ in range(4):
                    cursor.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor
                    )
                if cursor.selectedText().strip() == "":
                    cursor.removeSelectedText()
        except Exception as e:
            logger.error(f"减少缩进失败: {str(e)}")

    def _on_text_changed(self) -> None:
        """处理文本变化事件"""
        try:
            # 更新语法高亮
            self.highlighter.rehighlight()
            
            # 发出文本变化信号
            self.textChanged.emit()
            
        except Exception as e:
            logger.error(f"处理文本变化事件失败: {str(e)}")

    def _on_cursor_position_changed(self) -> None:
        """处理光标位置变化事件"""
        try:
            cursor = self.textCursor()
            block_number = cursor.blockNumber() + 1  # 行号从1开始
            column = cursor.columnNumber() + 1  # 列号从1开始
            self.cursorPositionChanged.emit(block_number, column)
        except Exception as e:
            logger.error(f"处理光标位置变化事件失败: {str(e)}")

    def set_text_color(self, color: Union[QColor, str, Qt.GlobalColor]) -> None:
        """设置文本颜色"""
        try:
            if isinstance(color, str):
                color = QColor(color)
            
            cursor = self.textCursor()
            format = cursor.charFormat()
            format.setForeground(color)
            cursor.mergeCharFormat(format)
            self.setTextCursor(cursor)
        except Exception as e:
            logger.error(f"设置文本颜色失败: {str(e)}")

    def set_background_color(self, color: Union[QColor, str, Qt.GlobalColor]) -> None:
        """设置背景颜色"""
        try:
            if isinstance(color, str):
                color = QColor(color)
                
            cursor = self.textCursor()
            format = cursor.charFormat()
            format.setBackground(color)
            cursor.mergeCharFormat(format)
            self.setTextCursor(cursor)
        except Exception as e:
            logger.error(f"设置背景颜色失败: {str(e)}")

    def get_current_line(self) -> str:
        """获取当前行文本"""
        try:
            cursor = self.textCursor()
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            return cursor.selectedText()
        except Exception as e:
            logger.error(f"获取当前行文本失败: {str(e)}")
            return ""

    def get_selected_text(self) -> str:
        """获取选中的文本"""
        try:
            cursor = self.textCursor()
            return cursor.selectedText()
        except Exception as e:
            logger.error(f"获取选中文本失败: {str(e)}")
            return ""

    def insert_text(self, text: str, color: Optional[Union[QColor, str, Qt.GlobalColor]] = None) -> None:
        """插入文本"""
        try:
            cursor = self.textCursor()
            if color:
                format = QTextCharFormat()
                if isinstance(color, str):
                    color = QColor(color)
                format.setForeground(color)
                cursor.mergeCharFormat(format)
            cursor.insertText(text)
            self.setTextCursor(cursor)
        except Exception as e:
            logger.error(f"插入文本失败: {str(e)}")

    def clear_format(self) -> None:
        """清除格式"""
        try:
            cursor = self.textCursor()
            cursor.setCharFormat(QTextCharFormat())
            self.setTextCursor(cursor)
        except Exception as e:
            logger.error(f"清除格式失败: {str(e)}")

    def get_line_count(self) -> int:
        """获取总行数"""
        try:
            return self.document().lineCount()
        except Exception as e:
            logger.error(f"获取总行数失败: {str(e)}")
            return 0

    def get_char_count(self) -> int:
        """获取字符总数"""
        try:
            return len(self.toPlainText())
        except Exception as e:
            logger.error(f"获取字符总数失败: {str(e)}")
            return 0

    def get_cursor_position(self) -> tuple[int, int]:
        """获取光标位置"""
        try:
            cursor = self.textCursor()
            return (cursor.blockNumber() + 1, cursor.columnNumber() + 1)
        except Exception as e:
            logger.error(f"获取光标位置失败: {str(e)}")
            return (1, 1)

    def move_cursor(self, operation: QTextCursor.MoveOperation, mode: QTextCursor.MoveMode = QTextCursor.MoveMode.MoveAnchor) -> None:
        """移动光标"""
        try:
            cursor = self.textCursor()
            cursor.movePosition(operation, mode)
            self.setTextCursor(cursor)
        except Exception as e:
            logger.error(f"移动光标失败: {str(e)}")

    def set_read_only(self, read_only: bool = True) -> None:
        """设置只读模式"""
        try:
            super().setReadOnly(read_only)
            logger.debug(f"设置只读模式: {read_only}")
        except Exception as e:
            logger.error(f"设置只读模式失败: {str(e)}")

    def set_font(self, font: QFont) -> None:
        """设置字体"""
        try:
            super().setFont(font)
            logger.debug(f"设置字体: {font.family()}, {font.pointSize()}")
        except Exception as e:
            logger.error(f"设置字体失败: {str(e)}")
