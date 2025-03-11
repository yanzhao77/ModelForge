import json
import os
import logging
import logging.config
from enum import Enum
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, List, Union
from datetime import datetime

# ==================== 日志系统 ====================

class LoggerNames(Enum):
    """日志记录器名称"""
    ROOT = "modelforge"
    CONFIG = "modelforge.config"
    MODEL = "modelforge.model"
    INTERFACE = "modelforge.interface"
    UI = "modelforge.ui"
    CUSTOM = "modelforge.custom"
    UTILS = "modelforge.utils"
    DATABASE = "modelforge.database"


def get_logger(name: Union[str, LoggerNames]) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 记录器名称或枚举值
        
    Returns:
        日志记录器实例
    """
    if isinstance(name, LoggerNames):
        name = name.value
    return logging.getLogger(name)


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


class LogPaths:
    """日志路径管理"""
    
    @classmethod
    def get_log_dir(cls, workspace_root: Path) -> Path:
        """获取日志目录"""
        return workspace_root / "logs"
    
    @classmethod
    def get_log_file(cls, workspace_root: Path) -> Path:
        """获取日志文件路径"""
        return cls.get_log_dir(workspace_root) / f"modelforge_{datetime.now().strftime('%Y%m%d')}.log"
    
    @classmethod
    def get_error_file(cls, workspace_root: Path) -> Path:
        """获取错误日志文件路径"""
        return cls.get_log_dir(workspace_root) / f"modelforge_error_{datetime.now().strftime('%Y%m%d')}.log"

    @classmethod
    def ensure_log_dir(cls, workspace_root: Path) -> None:
        """确保日志目录存在"""
        try:
            log_dir = cls.get_log_dir(workspace_root)
            log_dir.mkdir(parents=True, exist_ok=True)
            # 更新日志配置中的文件路径
            LogConfig.HANDLERS["file"]["filename"] = str(cls.get_log_file(workspace_root))
            LogConfig.HANDLERS["error_file"]["filename"] = str(cls.get_error_file(workspace_root))
        except Exception as e:
            print(f"创建日志目录失败: {str(e)}")  # 在日志系统启动前使用print
            raise


def init_logging(workspace_root: Path) -> None:
    """初始化日志系统"""
    LogPaths.ensure_log_dir(workspace_root)
    logging.config.dictConfig(LogConfig.get_config())
    print("日志系统初始化完成")  # 使用print，因为日志系统还未完全初始化


# ==================== 配置系统 ====================

@dataclass
class PathConfig:
    """路径配置"""
    workspace_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)

    def __post_init__(self):
        """验证并创建必要的目录"""
        try:
            # 创建所有必要的目录
            for dir_path in self.required_dirs:
                dir_path.mkdir(parents=True, exist_ok=True)
            logger.info("路径配置初始化完成")
        except Exception as e:
            logger.error(f"路径配置初始化失败: {str(e)}")
            raise

    @property
    def required_dirs(self) -> List[Path]:
        """获取所有必要的目录"""
        return [
            self.icon_dir,
            self.model_dir,
            self.config_dir,
            self.cache_dir,
            self.log_dir,
            self.temp_dir,
            self.data_dir,
            self.plugin_dir
        ]

    @property
    def icon_dir(self) -> Path:
        """图标目录"""
        return self.workspace_root / "icon"

    @property
    def model_dir(self) -> Path:
        """模型目录"""
        return self.workspace_root / "model"

    @property
    def config_dir(self) -> Path:
        """配置目录"""
        return self.workspace_root / "config"

    @property
    def cache_dir(self) -> Path:
        """缓存目录"""
        return self.workspace_root / "cache"

    @property
    def log_dir(self) -> Path:
        """日志目录"""
        return self.workspace_root / "logs"

    @property
    def temp_dir(self) -> Path:
        """临时目录"""
        return self.workspace_root / "temp"

    @property
    def data_dir(self) -> Path:
        """数据目录"""
        return self.workspace_root / "data"

    @property
    def plugin_dir(self) -> Path:
        """插件目录"""
        return self.workspace_root / "plugins"

    def get_path(self, category: str, name: str) -> Path:
        """获取特定类别的文件路径"""
        try:
            category_map = {
                "icon": self.icon_dir,
                "model": self.model_dir,
                "config": self.config_dir,
                "cache": self.cache_dir,
                "log": self.log_dir,
                "temp": self.temp_dir,
                "data": self.data_dir,
                "plugin": self.plugin_dir
            }

            if category not in category_map:
                raise ValueError(f"无效的类别: {category}")

            path = category_map[category] / name
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

            return path

        except Exception as e:
            logger.error(f"获取路径失败: {str(e)}")
            raise

    def get_icon_path(self, name: str) -> str:
        """获取图标路径"""
        path = self.get_path("icon", name)
        if not path.exists():
            logger.warning(f"图标文件不存在: {path}")
        return str(path)

    def get_model_path(self, name: str) -> str:
        """获取模型路径"""
        path = self.get_path("model", name)
        if not path.exists():
            logger.warning(f"模型文件不存在: {path}")
        return str(path)

    def get_config_path(self, name: str) -> str:
        """获取配置文件路径"""
        return str(self.get_path("config", name))

    def get_cache_path(self, name: str) -> str:
        """获取缓存文件路径"""
        return str(self.get_path("cache", name))

    def get_log_path(self, name: str) -> str:
        """获取日志文件路径"""
        return str(self.get_path("log", name))

    def get_temp_path(self, name: str) -> str:
        """获取临时文件路径"""
        return str(self.get_path("temp", name))

    def get_data_path(self, name: str) -> str:
        """获取数据文件路径"""
        return str(self.get_path("data", name))

    def get_plugin_path(self, name: str) -> str:
        """获取插件文件路径"""
        return str(self.get_path("plugin", name))


@dataclass
class ThemeConfig:
    """主题配置"""
    name: str = "default"
    dark_mode: bool = False
    primary_color: str = "#1a73e8"
    secondary_color: str = "#5f6368"
    background_color: str = "#ffffff"
    text_color: str = "#202124"
    font_family: str = "Microsoft YaHei"
    font_size: int = 14


@dataclass
class LocaleConfig:
    """本地化配置"""
    language: str = "zh_CN"
    timezone: str = "Asia/Shanghai"
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H:%M:%S"
    datetime_format: str = "%Y-%m-%d %H:%M:%S"


@dataclass
class AppConfig:
    """应用程序配置"""
    # 基本信息
    project_name: str = "lifeChat"
    version: str = "峨眉峰_1.0.0"
    description: str = "lifeChat - 一个强大的AI模型应用平台"
    author: str = "azir"
    url: str = "https://github.com/yan34177/lifeChat"

    # 路径配置
    paths: Dict[str, Any] = field(default_factory=dict)

    # 默认设置
    default_model_name: str = "DeepSeek-R1-Distill-Qwen-1.5B"
    default_model_path: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                           'model')

    icon_main_view: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                       'icon/logo.ico')
    transition_main_view: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/logo-512x512.png')
    transition_main_gif: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/guys/神经网络编织.gif')
    icon_clouds_view: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                         'icon/treeview/clouds.ico')
    icon_model_view: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                        'icon/treeview/model.ico')
    icon_tree_model_view: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/treeview/tree_model.ico')

    default_language: str = "zh_CN"
    default_theme: str = "light"

    # 界面设置
    window_title: str = ""  # 从field(init=False)修改为默认空字符串
    window_size: Dict[str, int] = field(default_factory=lambda: {"width": 1280, "height": 720})
    window_position: Dict[str, int] = field(default_factory=lambda: {"x": 100, "y": 100})
    icon_paths: Dict[str, str] = field(default_factory=dict)

    # 主题设置
    theme: Dict[str, Any] = field(default_factory=dict)

    # 本地化设置
    locale: Dict[str, Any] = field(default_factory=dict)

    # 系统设置
    debug_mode: bool = False
    auto_save: bool = True
    save_interval: int = 300  # 5分钟
    max_history: int = 100

    def __post_init__(self):
        """初始化后处理"""
        try:
            self.window_title = f"{self.project_name} v{self.version}"
            
            # 初始化路径配置(如果为空)
            if not self.paths:
                self.paths = asdict(PathConfig())
                
            # 初始化主题配置(如果为空)
            if not self.theme:
                self.theme = asdict(ThemeConfig())
                
            # 初始化本地化配置(如果为空)
            if not self.locale:
                self.locale = asdict(LocaleConfig())
                
            self._init_icon_paths()
            logger.info("应用程序配置初始化完成")
        except Exception as e:
            logger.error(f"应用程序配置初始化失败: {str(e)}")
            raise
            
    def _init_icon_paths(self):
        """初始化图标路径"""
        try:
            path_config = PathConfig() if not isinstance(self.paths, PathConfig) else self.paths
            
            self.icon_paths.update({
                "app_icon": self.icon_main_view,
                "transition": self.transition_main_view,
                "transition_gif": self.transition_main_gif,
                "clouds": self.icon_clouds_view,
                "model": self.icon_model_view,
                "tree_model": self.icon_tree_model_view
            })
            logger.debug("图标路径初始化完成")
        except Exception as e:
            logger.error(f"图标路径初始化失败: {str(e)}")
            raise

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            k: v if not isinstance(v, Path) else str(v)
            for k, v in asdict(self).items()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """从字典创建实例"""
        # 移除window_title以避免意外传递到__init__
        if "window_title" in data:
            data.pop("window_title")
            
        # 确保paths, theme和locale是字典
        for field_name in ["paths", "theme", "locale"]:
            if field_name in data and not isinstance(data[field_name], dict):
                data[field_name] = asdict(data[field_name])
                
        return cls(**data)


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        """初始化配置管理器"""
        try:
            self.path_config = PathConfig()
            self.app_config = None
            
            # 加载配置
            self._load_config()
            
            # 如果加载失败，使用默认配置
            if not self.app_config:
                self.app_config = AppConfig()
                self._save_config()
            self.is_initialized = True
            logger.info("配置管理器初始化完成")
        except Exception as e:
            self.is_initialized = False
            logger.error(f"配置管理器初始化失败: {str(e)}")
            self.app_config = AppConfig()  # 使用默认配置

    def get_config(self):
        print(111)
        return self.app_config
    
    def _load_config(self):
        """加载配置"""
        try:
            config_file = self.path_config.config_dir / "app_config.json"
            
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                    
                # 转换路径字符串为Path对象
                if "paths" in config_data:
                    for key, value in config_data["paths"].items():
                        if isinstance(value, str) and key != "workspace_root":
                            config_data["paths"][key] = Path(value)
                            
                # 转换图标路径
                if "icon_paths" in config_data:
                    for key, value in config_data["icon_paths"].items():
                        if isinstance(value, str):
                            config_data["icon_paths"][key] = value
                
                self.app_config = AppConfig(**config_data)
                logger.info("配置加载成功")
            else:
                logger.warning("配置文件不存在，将使用默认配置")
                self.app_config = None
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")
            self.app_config = None
    
    def _save_config(self):
        """保存配置"""
        try:
            config_file = self.path_config.config_dir / "app_config.json"
            
            # 确保配置目录存在
            config_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 将配置转换为字典
            config_dict = asdict(self.app_config)
            
            # 处理Path对象，转换为字符串
            self._convert_paths_to_str(config_dict)
            
            # 保存配置
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=4)
                
            logger.info("配置保存成功")
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            raise
    
    def _convert_paths_to_str(self, config_dict: Dict[str, Any]) -> None:
        """将配置字典中的Path对象转换为字符串"""
        # 处理paths字典
        if "paths" in config_dict:
            for key, value in config_dict["paths"].items():
                if isinstance(value, Path):
                    config_dict["paths"][key] = str(value)
                    
        # 处理icon_paths字典
        if "icon_paths" in config_dict:
            for key, value in config_dict["icon_paths"].items():
                if isinstance(value, Path):
                    config_dict["icon_paths"][key] = str(value)
        
        # 处理其他可能的Path对象
        for key, value in config_dict.items():
            if isinstance(value, Path):
                config_dict[key] = str(value)
            elif isinstance(value, dict):
                self._convert_paths_to_str(value)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, Path):
                        value[i] = str(item)
                    elif isinstance(item, dict):
                        self._convert_paths_to_str(item)


# 初始化日志系统
workspace_root = Path(__file__).parent.parent.parent
init_logging(workspace_root)

# 创建logger
logger = get_logger(LoggerNames.CONFIG)

# 全局配置管理器实例
config_manager = ConfigManager()
