from abc import ABC, abstractmethod
from typing import Any, Optional, List, Dict

from common.const.common_const import LoggerNames, get_logger

logger = get_logger(LoggerNames.MODEL)

class BaseGenerate(ABC):
    """生成模型的抽象基类"""
    
    def __init__(self):
        """初始化基类"""
        self.model: Optional[Any] = None
        self.model_name: Optional[str] = None
        self.message_dict: List[Dict[str, str]] = []
        logger.debug("BaseGenerate初始化完成")
        
    @abstractmethod
    def pipeline_question(self) -> None:
        """准备模型管道"""
        pass
        
    @abstractmethod
    def pipeline_answer(self, text: str) -> str:
        """生成回答"""
        pass
        
    @abstractmethod
    def release_resources(self) -> None:
        """释放资源"""
        pass
        
    def __str__(self) -> str:
        """字符串表示"""
        return f"{self.__class__.__name__}(model_name={self.model_name})"
        
    def __repr__(self) -> str:
        """详细表示"""
        return f"{self.__class__.__name__}(model={self.model}, model_name={self.model_name})"
