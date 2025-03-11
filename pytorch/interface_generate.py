import json
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from openai import OpenAI
from openai.types.chat import ChatCompletion

from common.const.common_const import InterfaceType, LoggerNames, get_logger
from pytorch.base_generate import BaseGenerate

logger = get_logger(LoggerNames.MODEL)

# 设置环境变量
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

@dataclass
class InterfaceConfig:
    """接口配置"""
    api_key: str
    base_url: str
    model_name: str
    model_type: str = InterfaceType.OPENAI.value
    role: str = "user"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    timeout: Optional[int] = None
    message_dict: List[Dict[str, str]] = field(default_factory=list)
    
    def __post_init__(self):
        """验证配置参数"""
        if not self.api_key:
            raise ValueError("API密钥不能为空")
        if not self.base_url:
            raise ValueError("基础URL不能为空")
        if not self.model_name:
            raise ValueError("模型名称不能为空")
            
        # 验证参数范围
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature必须在0到2之间")
        if self.top_p is not None and not 0 <= self.top_p <= 1:
            raise ValueError("top_p必须在0到1之间")
        if self.n is not None and self.n < 1:
            raise ValueError("n必须大于0")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens必须大于0")
        if self.timeout is not None and self.timeout < 1:
            raise ValueError("timeout必须大于0")

class InterfaceGenerate(BaseGenerate):
    """接口生成类"""
    
    def __init__(self, config: InterfaceConfig):
        """初始化接口生成器"""
        super().__init__()
        try:
            self.config = config
            self.command: List[str] = []
            self.client: Optional[OpenAI] = None
            logger.info(f"接口生成器初始化完成，模型: {config.model_name}")
        except Exception as e:
            logger.error(f"初始化失败: {str(e)}")
            raise

    def pipeline_question(self) -> None:
        """准备模型管道"""
        try:
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url
            )
            logger.info("开始对话，输入 'exit' 退出")
        except Exception as e:
            logger.error(f"模型管道准备失败: {str(e)}")
            raise

    def pipeline_answer(self, text: str) -> str:
        """生成回答"""
        try:
            if text.lower() == 'exit':
                logger.info("结束对话")
                return "对话已结束"

            # 更新消息历史
            self.command.append(text)
            self.config.message_dict.append({
                'role': self.config.role,
                'content': text
            })

            # 构建API参数
            kwargs = self._build_api_kwargs()
            
            # 调用API
            completion = self._call_api(kwargs)
            if not completion:
                return ""
                
            # 处理响应
            response = self._process_response(completion)
            logger.debug(f"生成回答成功，长度: {len(response)}")
            return response
            
        except Exception as e:
            logger.error(f"生成回答失败: {str(e)}")
            return ""

    def _build_api_kwargs(self) -> Dict[str, Any]:
        """构建API参数"""
        try:
            kwargs = {
                'model': self.config.model_name,
                'messages': self.config.message_dict
            }

            # 添加可选参数
            optional_params = {
                'temperature': self.config.temperature,
                'top_p': self.config.top_p,
                'n': self.config.n,
                'max_tokens': self.config.max_tokens,
                'timeout': self.config.timeout
            }

            kwargs.update({
                k: v for k, v in optional_params.items()
                if v is not None
            })
            
            logger.debug(f"API参数构建完成: {kwargs}")
            return kwargs
            
        except Exception as e:
            logger.error(f"构建API参数失败: {str(e)}")
            raise

    def _call_api(self, kwargs: Dict[str, Any]) -> Optional[ChatCompletion]:
        """调用API"""
        try:
            if not self.client:
                raise ValueError("客户端未初始化")
                
            completion = self.client.chat.completions.create(**kwargs)
            logger.debug("API调用成功")
            return completion
            
        except Exception as e:
            logger.error(f"API调用失败: {str(e)}")
            return None

    def _process_response(self, completion: ChatCompletion) -> str:
        """处理API响应"""
        try:
            result = completion.model_dump_json()
            result_dict = json.loads(result)['choices'][0]['message']
            
            # 更新消息历史
            response = result_dict['content']
            self.command.append(response)
            self.config.message_dict.append({
                'role': "assistant",
                'content': response
            })
            
            return response
            
        except Exception as e:
            logger.error(f"处理响应失败: {str(e)}")
            raise

    def release_resources(self) -> None:
        """释放资源"""
        try:
            self.client = None
            self.command.clear()
            self.config.message_dict.clear()
            logger.info("资源已释放")
        except Exception as e:
            logger.error(f"释放资源失败: {str(e)}")
            raise
