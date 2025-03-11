from dataclasses import dataclass, field
from queue import Queue
from typing import List, Any

from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.CUSTOM)


@dataclass
class TextAreaConfig:
    """文本区域配置"""
    text_area: Any  # QTextEdit 或其子类
    buffer_size: int = 1000
    auto_flush: bool = True

    def __post_init__(self):
        """验证配置参数"""
        if self.buffer_size <= 0:
            raise ValueError("缓冲区大小必须大于0")


@dataclass
class InputConfig:
    """输入配置"""
    input_line_edit: Any  # QLineEdit 或其子类
    buffer: List[str] = field(default_factory=list)
    max_buffer: int = 100

    def __post_init__(self):
        """验证配置参数"""
        if self.max_buffer <= 0:
            raise ValueError("最大缓冲区大小必须大于0")


class CustomOutput:
    """自定义输出类，用于重定向输出到文本区域"""

    def __init__(self, config: TextAreaConfig):
        """初始化输出类"""
        self.config = config
        self.text_area = config.text_area
        self._buffer = Queue(maxsize=config.buffer_size)
        logger.debug(f"CustomOutput初始化完成，缓冲区大小: {config.buffer_size}")

    def write(self, text: str) -> None:
        """写入文本到输出区域"""
        try:
            if not text:  # 忽略空字符串
                return

            self.text_area.print(text)
            if self.config.auto_flush:
                self.flush()
            logger.debug(f"写入文本成功，长度: {len(text)}")
        except Exception as e:
            logger.error(f"写入文本失败: {str(e)}")

    def print(self, text: str) -> None:
        """打印文本到输出区域"""
        try:
            self.write(text)
        except Exception as e:
            logger.error(f"打印文本失败: {str(e)}")

    def flush(self) -> None:
        """刷新输出缓冲区"""
        try:
            while not self._buffer.empty():
                if text := self._buffer.get_nowait():
                    self.text_area.print(text)
            logger.debug("缓冲区刷新完成")
        except Exception as e:
            logger.error(f"刷新缓冲区失败: {str(e)}")

    def isatty(self) -> bool:
        """检查是否是终端设备"""
        return False


class CustomInput:
    """自定义输入类，用于从文本框获取输入"""

    def __init__(self, config: InputConfig):
        """初始化输入类"""
        self.config = config
        self.input_line_edit = config.input_line_edit
        self.buffer = config.buffer
        logger.debug(f"CustomInput初始化完成，最大缓冲区大小: {config.max_buffer}")

    def readline(self) -> str:
        """读取一行输入"""
        try:
            # 如果缓冲区为空且输入框有内容
            if not self.buffer and (text := self.input_line_edit.text().strip()):
                # 如果缓冲区已满，移除最旧的输入
                if len(self.buffer) >= self.config.max_buffer:
                    self.buffer.pop(0)
                self.buffer.append(text)
                self.input_line_edit.clear()
                logger.debug(f"读取新输入: {text}")
                return text + "\n"

            # 如果缓冲区有内容，返回第一个元素
            if self.buffer:
                text = self.buffer.pop(0)
                logger.debug(f"从缓冲区读取: {text}")
                return text + "\n"

            return ""
        except Exception as e:
            logger.error(f"读取输入失败: {str(e)}")
            return ""

    def clear(self) -> None:
        """清空输入缓冲区和输入框"""
        try:
            self.buffer.clear()
            self.input_line_edit.clear()
            logger.debug("输入缓冲区已清空")
        except Exception as e:
            logger.error(f"清空缓冲区失败: {str(e)}")

    def available(self) -> bool:
        """检查是否有可用输入"""
        return bool(self.buffer) or bool(self.input_line_edit.text().strip())
