import os
import logging
import logging.handlers
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union, TypeVar, Generic
from pathlib import Path
from datetime import datetime

from common.const.config import config_manager, LoggerNames, get_logger

T = TypeVar('T')


class Singleton(type):
    """单例元类"""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class LogConfig:
    """日志配置管理器"""

    FORMATTERS = {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "simple": {
            "format": "%(message)s"
        }
    }

    HANDLERS = {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "simple",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "default",
            "filename": "",  # 运行时设置
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8"
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "default",
            "filename": "",  # 运行时设置
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8"
        }
    }

    LOGGERS = {
        "": {  # root logger
            "handlers": ["console", "file", "error_file"],
            "level": "DEBUG",
            "propagate": True
        }
    }

    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        """获取日志配置"""
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": cls.FORMATTERS,
            "handlers": cls.HANDLERS,
            "loggers": cls.LOGGERS
        }


class LogLevels(Enum):
    """日志级别"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LogPaths:
    """日志路径管理"""
    LOG_DIR = config_manager.path_config.log_dir
    LOG_FILE = LOG_DIR / f"modelforge_{datetime.now().strftime('%Y%m%d')}.log"
    ERROR_FILE = LOG_DIR / f"modelforge_error_{datetime.now().strftime('%Y%m%d')}.log"
    @classmethod
    def ensure_log_dir(cls) -> None:
        """确保日志目录存在"""
        try:
            cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
            # 更新日志配置中的文件路径
            LogConfig.HANDLERS["file"]["filename"] = str(cls.LOG_FILE)
            LogConfig.HANDLERS["error_file"]["filename"] = str(cls.ERROR_FILE)
        except Exception as e:
            print(f"创建日志目录失败: {str(e)}")  # 在日志系统启动前使用print
            raise


class ModelType(Enum):
    """模型类型"""
    LOCAL = "local"  # 本地模型
    INTERFACE = "interface"  # 接口模型
    CUSTOM = "custom"  # 自定义模型


class InterfaceType(Enum):
    """接口类型"""
    OPENAI = "openai"
    SPARK = "spark"
    AZURE = "azure"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"


@dataclass
class BaseConfig(Generic[T]):
    """基础配置类"""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> T:
        """从字典创建实例"""
        return cls(**{k: v for k, v in data.items() if not k.startswith('_')})


@dataclass
class ModelConfig(BaseConfig["ModelConfig"]):
    """模型配置"""
    # 基本信息
    name: str
    type_name: str = ""
    model_type: ModelType = ModelType.LOCAL
    path: str = ""
    description: str = ""

    # 模型参数
    max_tokens: int = field(default=500, metadata={"min": 1, "max": 4096})
    do_sample: bool = True
    temperature: float = field(default=0.9, metadata={"min": 0.0, "max": 2.0})
    top_k: int = field(default=50, metadata={"min": 1, "max": 100})
    top_p: float = field(default=1.0, metadata={"min": 0.0, "max": 1.0})
    top_n: int = field(default=1, metadata={"min": 1, "max": 5})
    input_max_length: int = field(default=2048, metadata={"min": 1, "max": 8192})
    repetition_penalty: float = field(default=1.2, metadata={"min": 1.0, "max": 2.0})
    presence_penalty: float = field(default=0.0, metadata={"min": -2.0, "max": 2.0})
    frequency_penalty: float = field(default=0.0, metadata={"min": -2.0, "max": 2.0})

    # 特殊功能
    is_deepseek: bool = False
    online_search: bool = False
    stream_output: bool = True
    use_cache: bool = True

    # 接口参数
    interface_type: Optional[str] = None
    api_key: str = ""
    base_url: str = ""
    timeout: int = field(default=60, metadata={"min": 1, "max": 300})

    # 其他设置
    parameters_editable: bool = True
    interface_role: str = "user"
    interface_messages: List[Dict[str, str]] = field(default_factory=lambda: [
        {"role": "system", "content": "你是一个AI助手"}
    ])

    def __post_init__(self):
        """验证参数"""
        self._validate_params()

    def _validate_params(self):
        """验证参数范围"""
        for field_name, field_value in self.__dataclass_fields__.items():
            if "metadata" in field_value.metadata:
                value = getattr(self, field_name)
                meta = field_value.metadata["metadata"]
                if "min" in meta and value < meta["min"]:
                    raise ValueError(f"{field_name}的值不能小于{meta['min']}")
                if "max" in meta and value > meta["max"]:
                    raise ValueError(f"{field_name}的值不能大于{meta['max']}")


@dataclass
class SparkConfig(ModelConfig):
    """星火配置"""

    def __init__(self):
        super().__init__(
            name="Spark",
            type_name="general",
            model_type=ModelType.INTERFACE,
            interface_type=InterfaceType.SPARK.value,
            description="讯飞星火认知大模型",
            api_key="lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll",
            base_url="https://spark-api.xf-yun.com/v1"
        )


class Constants(metaclass=Singleton):
    """常量类"""

    def __init__(self):
        """初始化常量"""
        try:
            # 设置应用程序路径
            self.app_path = Path(__file__).parent.parent.parent
            
            # 导入配置管理器，避免循环导入
            # 不要直接访问配置对象，而是通过安全的方式
            if hasattr(config_manager, 'app_config'):
                # 设置默认模型
                self.default_model = config_manager.app_config.default_model_name
                self.default_model_path = config_manager.app_config.default_model_path
                
                # 设置默认接口
                self.default_interface = "Offline"
                
                # 设置默认语言
                self.default_language = config_manager.app_config.default_language
                
                # 设置默认主题
                self.default_theme = config_manager.app_config.default_theme
                
                # 设置图标路径
                self.icon_paths = config_manager.app_config.icon_paths
            else:
                # 设置默认值
                self.default_model = "DeepSeek-R1-Distill-Qwen-1.5B"
                self.default_model_path = os.path.join(str(self.app_path), "model")
                self.default_interface = "Offline"
                self.default_language = "zh_CN"
                self.default_theme = "light"
                self.icon_paths = {}
            
            # 初始化模型配置
            self.model_config = ModelConfig(
                name=self.default_model,
                path=self.default_model_path
            )
            
            # 初始化接口配置
            self.interface_config = {}
            
            logger.info("常量初始化完成")
        except Exception as e:
            logger.error(f"常量初始化失败: {str(e)}")
            # 设置默认值
            self.app_path = Path(__file__).parent.parent.parent
            self.default_model = "DeepSeek-R1-Distill-Qwen-1.5B"
            self.default_model_path = os.path.join(str(self.app_path), "model")
            self.default_interface = "Offline"
            self.default_language = "zh_CN"
            self.default_theme = "light"
            self.icon_paths = {}
            self.model_config = ModelConfig(
                name=self.default_model,
                path=self.default_model_path
            )
            self.interface_config = {}


# 常量
class common_const():
    # model_parameters_setting
    max_tokens = 'max_tokens'
    do_sample = 'do_sample'
    temperature = 'temperature'
    top_k = 'top_k'
    top_p = 'top_p'
    top_n = 'top_n'
    timeout = "timeout"
    input_max_length = 'input_max_length'
    parameters_editable = 'parameters_editable'
    repetition_penalty = "repetition_penalty"
    presence_penalty = "presence_penalty"
    frequency_penalty = "frequency_penalty"

    is_deepSeek = "is_deepSeek"
    online_search = "online_search"

    # model
    model_name = "model_name"
    model_type_name = "model_type_name"
    model_path = "model_path"
    model_type = "model_type"

    interface_type = "interface_type"
    interface_api_key = "interface_api_key"
    interface_base_url = "interface_base_url"

    interface_COLUMN_HEADERS = ["接口名称", "接口类型", "模型名称", "API Key", "Base URL"]

    interface_role = "interface_role",
    interface_message_dict = "interface_message_dict"

    interface_type_dict = [InterfaceType.OPENAI.value]
    
    # 版本信息
    version = "1.0.0"
    build_time = "2024-01-01"


# 初始化日志系统
LogPaths.ensure_log_dir()
logging.config.dictConfig(LogConfig.get_config())

# 获取根日志记录器
logger = get_logger(LoggerNames.ROOT)
