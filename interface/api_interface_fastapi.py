import os
import threading
import time
import uuid
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator

from common.const.common_const import LoggerNames, get_logger, Constants
from common.const.config import config_manager
from pytorch.model_generate import ModelGenerate

logger = get_logger(LoggerNames.INTERFACE)

# 安全认证
security = HTTPBearer()

@dataclass
class FastAPIConfig:
    """FastAPI配置"""
    host: str = "0.0.0.0"
    port: int = 7783
    reload: bool = False
    api_key: str = "valid_api_key"
    default_temperature: float = 0.7
    
    def __post_init__(self):
        """验证配置参数"""
        if not self.host:
            raise ValueError("主机地址不能为空")
        if not 0 < self.port < 65536:
            raise ValueError("端口号必须在1-65535之间")
        if not self.api_key:
            raise ValueError("API密钥不能为空")
        if not 0 <= self.default_temperature <= 1:
            raise ValueError("temperature必须在0到1之间")

class Message(BaseModel):
    """消息模型"""
    role: str = Field(..., description="消息角色，如'user'或'assistant'")
    content: str = Field(..., description="消息内容")
    
    @validator('role')
    def validate_role(cls, v):
        """验证角色"""
        if v not in ['user', 'assistant', 'system']:
            raise ValueError("角色必须是'user'、'assistant'或'system'")
        return v
        
    @validator('content')
    def validate_content(cls, v):
        """验证内容"""
        if not v.strip():
            raise ValueError("消息内容不能为空")
        return v

class ChatCompletionRequest(BaseModel):
    """聊天完成请求模型"""
    messages: List[Message] = Field(..., description="消息列表")
    model: str = Field(default="default-model", description="模型名称")
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="采样温度"
    )
    
    @validator('messages')
    def validate_messages(cls, v):
        """验证消息列表"""
        if not v:
            raise ValueError("消息列表不能为空")
        if v[-1].role != "user":
            raise ValueError("最后一条消息必须来自用户")
        return v

class ChatCompletionResponse(BaseModel):
    """聊天完成响应模型"""
    id: str = Field(..., description="响应ID")
    object: str = Field(default="chat.completion", description="对象类型")
    created: int = Field(..., description="创建时间戳")
    model: str = Field(..., description="模型名称")
    choices: List[Dict[str, Any]] = Field(..., description="生成的选项")
    usage: Dict[str, int] = Field(..., description="token使用统计")

class FastAPIChatCompletionResource:
    """FastAPI聊天完成资源"""
    
    def __init__(self, api_on_flag: bool = True, text_area: Any = None, config: Optional[FastAPIConfig] = None):
        """初始化FastAPI资源"""
        try:
            self.config = config or FastAPIConfig()
            self.app = FastAPI(
                title="ModelForge API",
                description="ModelForge的OpenAI兼容API",
                version="1.0.0"
            )
            self.model_name = None
            self.api_on_flag = api_on_flag
            self.model_instance = text_area.model if text_area is not None else None
            
            self.setup_routes()
            logger.info("FastAPI聊天完成资源初始化完成")
        except Exception as e:
            logger.error(f"初始化失败: {str(e)}")
            raise

    def setup_routes(self):
        """设置路由"""
        try:
            # 添加路由
            self.app.post("/admin/switch")(self.switch_api)
            self.app.add_api_route(
                "/v1/chat/completions",
                self.chat_completions,
                methods=["POST"],
                response_model=ChatCompletionResponse,
                dependencies=[Depends(self.verify_api_key)]
            )
            logger.debug("路由设置完成")
        except Exception as e:
            logger.error(f"路由设置失败: {str(e)}")
            raise

    async def verify_api_key(self, auth: HTTPAuthorizationCredentials = Security(security)) -> bool:
        """验证API密钥"""
        try:
            if auth.scheme.lower() != "bearer" or auth.credentials != self.config.api_key:
                logger.warning("无效的API密钥")
                raise HTTPException(
                    status_code=401,
                    detail="无效的认证"
                )
            return True
        except Exception as e:
            logger.error(f"API密钥验证失败: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail="认证失败"
            )

    async def switch_api(self, enable: bool) -> Dict[str, bool]:
        """切换API开关"""
        try:
            self.api_on_flag = enable
            logger.info(f"API状态已切换为: {'启用' if enable else '禁用'}")
            return {"API_ENABLED": self.api_on_flag}
        except Exception as e:
            logger.error(f"切换API状态失败: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="切换API状态失败"
            )

    def merge_messages(self, messages_dict: List[Dict[str, str]], messages_temp: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """合并消息列表"""
        try:
            existing_messages = {tuple(msg.items()) for msg in messages_dict}
            for msg in messages_temp:
                if tuple(msg.items()) not in existing_messages:
                    messages_dict.append(msg)
            logger.debug(f"消息合并完成，总数: {len(messages_dict)}")
            return messages_dict
        except Exception as e:
            logger.error(f"消息合并失败: {str(e)}")
            return messages_dict

    async def chat_completions(self, request_data: ChatCompletionRequest) -> ChatCompletionResponse:
        """处理聊天完成请求"""
        try:
            # 检查API状态
            if not self.api_on_flag:
                raise HTTPException(
                    status_code=503,
                    detail="API已禁用"
                )

            # 初始化模型
            if self.model_instance is None:
                await self._initialize_model(request_data.model)

            # 处理消息
            messages_as_dicts = [msg.dict() for msg in request_data.messages]
            self.merge_messages(self.model_instance.message_dict, messages_as_dicts)
            
            try:
                self.model_instance.message_dict.remove(request_data.messages[-1].dict())
            except ValueError:
                pass

            # 生成响应
            response_text = await self._generate_response(request_data.messages[-1].content)
            
            # 构建响应
            result = self._build_response(request_data.messages[-1], response_text)
            logger.info(f"成功生成响应，长度: {len(response_text)}")
            return result
            
        except Exception as e:
            logger.error(f"处理请求失败: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=str(e)
            )

    async def _initialize_model(self, model_name: str) -> None:
        """初始化模型"""
        try:
            self.model_name = model_name
            local_model_path = config_manager.app_config.default_model_path
            model_path = os.path.join(local_model_path, model_name)
            
            self.model_instance = ModelGenerate(model_path=model_path)
            self.model_instance.pipeline_question()
            logger.info(f"模型 {model_name} 初始化完成")
        except Exception as e:
            logger.error(f"模型初始化失败: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"模型初始化失败: {str(e)}"
            )

    async def _generate_response(self, content: str) -> str:
        """生成响应"""
        try:
            response = self.model_instance.pipeline_answer(content)
            logger.debug(f"生成响应成功，输入长度: {len(content)}")
            return response
        except Exception as e:
            logger.error(f"生成响应失败: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"生成响应失败: {str(e)}"
            )

    def _build_response(self, user_message: Message, response_text: str) -> ChatCompletionResponse:
        """构建响应"""
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            created=int(time.time()),
            model=self.model_name,
            choices=[{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "finish_reason": "stop"
            }],
            usage={
                "prompt_tokens": len(user_message.content.split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(user_message.content.split()) + len(response_text.split())
            }
        )

    def run(self) -> None:
        """运行服务器"""
        try:
            uvicorn.run(
                self.app,
                host=self.config.host,
                port=self.config.port,
                reload=self.config.reload
            )
            logger.info(f"服务器运行在 {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"服务器运行失败: {str(e)}")
            raise

    def thread_run(self) -> None:
        """在线程中运行服务器"""
        try:
            threading.Thread(target=self.run).start()
            logger.info("服务器在新线程中启动")
        except Exception as e:
            logger.error(f"线程启动失败: {str(e)}")
            raise

# 实例化并暴露应用
resource = FastAPIChatCompletionResource(True, None)
app = resource.app
