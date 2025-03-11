import os
import time
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from wsgiref import simple_server

import falcon
from falcon import Request, Response

from common.const.common_const import LoggerNames, get_logger, Constants
from pytorch.model_generate import model_generate

logger = get_logger(LoggerNames.INTERFACE)

@dataclass
class ChatCompletionConfig:
    """聊天完成配置"""
    host: str = "localhost"
    port: int = 7783
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

class FalconOpenAIChatCompletionResource:
    """Falcon OpenAI 聊天完成资源"""
    
    def __init__(self, config: Optional[ChatCompletionConfig] = None):
        """初始化聊天完成资源"""
        try:
            self.config = config or ChatCompletionConfig()
            self.model = None
            self.app = falcon.App()
            self.app.add_route('/v1/chat/completions', self)
            logger.info("Falcon OpenAI 聊天完成资源初始化完成")
        except Exception as e:
            logger.error(f"初始化失败: {str(e)}")
            raise

    def run(self) -> None:
        """运行服务器"""
        try:
            httpd = simple_server.make_server(
                self.config.host,
                self.config.port,
                self.app
            )
            logger.info(f"OpenAI兼容API服务运行在端口 {self.config.port}...")
            httpd.serve_forever()
        except Exception as e:
            logger.error(f"服务器运行失败: {str(e)}")
            raise

    def validate_api_key(self, auth_header: Optional[str]) -> bool:
        """验证API密钥"""
        try:
            if not auth_header:
                logger.warning("缺少认证头")
                return False
                
            parts = auth_header.split()
            is_valid = (
                len(parts) == 2 and
                parts[0].lower() == 'bearer' and
                parts[1] == self.config.api_key
            )
            
            if not is_valid:
                logger.warning("无效的API密钥")
            return is_valid
            
        except Exception as e:
            logger.error(f"API密钥验证失败: {str(e)}")
            return False

    def on_post(self, req: Request, resp: Response) -> None:
        """处理POST请求"""
        try:
            # 身份验证
            auth_header = req.get_header('Authorization')
            if not self.validate_api_key(auth_header):
                resp.status = falcon.HTTP_401
                resp.media = {"error": "无效的认证"}
                return

            # 解析请求
            try:
                request_data = req.get_media()
                messages = request_data['messages']
                self.model_name = request_data.get('model', 'default-model')
                
                # 初始化模型
                if self.model is None:
                    self._initialize_model()
                    
                temperature = request_data.get(
                    'temperature',
                    self.config.default_temperature
                )
                
            except KeyError as e:
                logger.error(f"缺少必需参数: {str(e)}")
                resp.status = falcon.HTTP_400
                resp.media = {"error": "缺少必需参数: messages"}
                return

            # 验证消息
            if not self._validate_messages(messages):
                resp.status = falcon.HTTP_400
                resp.media = {"error": "最后一条消息必须来自用户"}
                return

            # 生成响应
            response_text = self._generate_response(messages)
            if not response_text:
                resp.status = falcon.HTTP_500
                resp.media = {"error": "生成响应失败"}
                return

            # 构建OpenAI风格的响应
            resp.media = self._build_response(messages[-1], response_text)
            resp.status = falcon.HTTP_200
            logger.info(f"成功生成响应，长度: {len(response_text)}")
            
        except Exception as e:
            logger.error(f"处理请求失败: {str(e)}")
            resp.status = falcon.HTTP_500
            resp.media = {"error": str(e)}

    def _initialize_model(self) -> None:
        """初始化模型"""
        try:
            local_model_path = Constants.APP_CONFIG.paths.model_dir
            model_path = os.path.join(local_model_path, self.model_name)
            
            self.model = model_generate(model_path=model_path)
            self.model.pipeline_question()
            logger.info(f"模型 {self.model_name} 初始化完成")
        except Exception as e:
            logger.error(f"模型初始化失败: {str(e)}")
            raise

    def _validate_messages(self, messages: List[Dict[str, str]]) -> bool:
        """验证消息列表"""
        return bool(messages and messages[-1]['role'] == 'user')

    def _generate_response(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """生成响应"""
        try:
            user_message = messages[-1]
            self.merge_messages(self.model.message_dict, messages)
            self.model.message_dict.remove(messages[-1])
            
            response = self.model.pipeline_answer(messages[-1]['content'])
            logger.debug(f"生成响应成功，输入长度: {len(user_message['content'])}")
            return response
            
        except Exception as e:
            logger.error(f"生成响应失败: {str(e)}")
            return None

    def _build_response(self, user_message: Dict[str, str], response_text: str) -> Dict[str, Any]:
        """构建响应"""
        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": len(user_message['content'].split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(user_message['content'].split()) + len(response_text.split())
            }
        }

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
