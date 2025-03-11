import logging
from typing import Optional, Dict, Any, NoReturn
from dataclasses import dataclass, field
from PySide6.QtCore import QRunnable, Slot

from common.const.common_const import Constants, ModelType, LoggerNames, get_logger
from pytorch.interface_generate import InterfaceGenerate
from pytorch.model_generate import ModelGenerate

logger = get_logger(LoggerNames.UI)

@dataclass
class ModelRunConfig:
    """模型运行配置"""
    text: str
    model: Any  # 模型实例
    text_area: Any  # TextArea实例
    
    def __post_init__(self):
        """验证配置参数"""
        if not self.text:
            raise ValueError("输入文本不能为空")
        if not self.model:
            raise ValueError("模型不能为空")
        if not self.text_area:
            raise ValueError("文本区域不能为空")

@dataclass
class ModelLaunchConfig:
    """模型启动配置"""
    parameters: Dict[str, Any]
    text_area: Any  # TextArea实例
    
    def __post_init__(self):
        """验证配置参数"""
        required_keys = [
            Constants.Keys.MODEL_TYPE,
            Constants.Keys.MODEL_NAME
        ]
        for key in required_keys:
            if key not in self.parameters:
                raise ValueError(f"缺少必需的参数: {key}")
        if not self.text_area:
            raise ValueError("文本区域不能为空")

class BaseRunnable(QRunnable):
    """基础运行类，所有运行任务的基类"""
    
    def __init__(self, text_area: Any):
        """初始化基础运行类"""
        super().__init__()
        self.text_area = text_area
        self._stop_flag = False
        logger.debug("BaseRunnable初始化完成")
        
    def run(self) -> None:
        """运行任务"""
        try:
            self._run()
        except Exception as e:
            logger.error(f"任务运行失败: {str(e)}")
            self._handle_error(str(e))
            
    def _run(self) -> None:
        """实际运行逻辑，子类需要重写此方法"""
        raise NotImplementedError("子类必须实现_run方法")
        
    def _handle_error(self, error_msg: str) -> None:
        """处理错误"""
        if hasattr(self.text_area, "print"):
            self.text_area.print(f"错误: {error_msg}")
            
    def stop(self) -> None:
        """停止任务"""
        self._stop_flag = True
        logger.info("任务停止标志已设置")

class ModelLauncher(BaseRunnable):
    """模型启动器，用于加载和初始化模型"""
    
    def __init__(self, config: ModelLaunchConfig):
        """初始化模型启动器"""
        super().__init__(config.text_area)
        self.config = config
        self.parameters = config.parameters
        logger.debug(f"ModelLauncher初始化完成，模型名称: {self.parameters.get(Constants.Keys.MODEL_NAME)}")
        
    def _run(self) -> None:
        """运行模型启动任务"""
        try:
            if self._stop_flag:
                return
                
            if self.parameters[Constants.Keys.MODEL_TYPE] == ModelType.LOCAL.value:
                self._launch_local_model()
            else:
                self._launch_interface()
                
            self._setup_model()
            logger.info(f"模型 {self.parameters[Constants.Keys.MODEL_NAME]} 启动成功")
            
        except Exception as e:
            logger.error(f"模型启动失败: {str(e)}")
            self._handle_error(f"模型启动失败: {str(e)}")
            
    def _launch_local_model(self) -> None:
        """启动本地模型"""
        try:
            self.text_area.model = ModelGenerate(
                self.parameters[Constants.Keys.MODEL_PATH],
                self.parameters[Constants.Keys.MAX_TOKENS],
                self.parameters[Constants.Keys.DO_SAMPLE],
                self.parameters[Constants.Keys.TEMPERATURE],
                self.parameters[Constants.Keys.TOP_K],
                self.parameters[Constants.Keys.INPUT_MAX_LENGTH],
                self.parameters[Constants.Keys.INTERFACE_MESSAGES],
                self.parameters[Constants.Keys.REPETITION_PENALTY],
                self.parameters[Constants.Keys.IS_DEEPSEEK],
                self.parameters[Constants.Keys.ONLINE_SEARCH]
            )
            logger.info("本地模型加载成功")
        except Exception as e:
            logger.error(f"本地模型加载失败: {str(e)}")
            raise
            
    def _launch_interface(self) -> None:
        """启动接口模型"""
        try:
            self.text_area.model = InterfaceGenerate(
                self.parameters[Constants.Keys.INTERFACE_API_KEY],
                self.parameters[Constants.Keys.INTERFACE_BASE_URL],
                self.parameters[Constants.Keys.MODEL_TYPE_NAME],
                self.parameters[Constants.Keys.INTERFACE_TYPE],
                self.parameters[Constants.Keys.INTERFACE_ROLE],
                self.parameters[Constants.Keys.TEMPERATURE],
                self.parameters[Constants.Keys.TOP_P],
                self.parameters[Constants.Keys.TOP_N],
                self.parameters[Constants.Keys.MAX_TOKENS],
                self.parameters[Constants.Keys.PRESENCE_PENALTY],
                self.parameters[Constants.Keys.FREQUENCY_PENALTY],
                self.parameters[Constants.Keys.TIMEOUT],
                self.parameters[Constants.Keys.INTERFACE_MESSAGES]
            )
            logger.info("接口模型加载成功")
        except Exception as e:
            logger.error(f"接口模型加载失败: {str(e)}")
            raise
            
    def _setup_model(self) -> None:
        """设置模型参数"""
        try:
            if self._stop_flag:
                return
                
            self.text_area.model.pipeline_question()
            self.text_area.set_model_name(self.parameters[Constants.Keys.MODEL_NAME])
            logger.debug("模型参数设置完成")
        except Exception as e:
            logger.error(f"模型参数设置失败: {str(e)}")
            raise
            
    def stop_model(self) -> None:
        """停止模型"""
        try:
            if self.text_area.model:
                self.text_area.model.release_resources()
                self.text_area.progress_bar.setVisible(False)
                logger.info("模型已停止")
        except Exception as e:
            logger.error(f"停止模型失败: {str(e)}")
            self._handle_error("停止模型失败")

class ModelRunner(BaseRunnable):
    """模型运行器，用于执行模型推理"""
    
    def __init__(self, config: ModelRunConfig):
        """初始化模型运行器"""
        super().__init__(config.text_area)
        self.config = config
        logger.debug("ModelRunner初始化完成")
        
    def _run(self) -> None:
        """运行模型"""
        try:
            if self._stop_flag:
                return
                
            result = self.config.model.pipeline_answer(self.config.text)
            self.text_area.append_model(
                self.config.model.model_name,
                result
            )
            self.text_area.progress_bar.setVisible(False)
            logger.info("模型运行完成")
        except Exception as e:
            logger.error(f"模型运行失败: {str(e)}")
            self._handle_error(f"模型运行失败: {str(e)}")
            self.text_area.progress_bar.setVisible(False)
