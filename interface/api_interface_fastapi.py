import os
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional

from common.const.common_const import common_const
from pytorch.model_generate import model_generate


# 定义数据模型
class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    model: Optional[str] = "default-model"
    temperature: Optional[float] = 0.7


class FastAPIChatCompletionResource:
    def __init__(self, api_on_flag, text_area):
        self.app = FastAPI()
        self.model_name = None
        self.setup_routes()
        self.api_on_flag = api_on_flag
        self.model_instance = text_area.model if text_area is not None else None


    def setup_routes(self):
        # 添加一个用于控制开关的路由（请注意实际使用中应做鉴权）
        self.app.post("/admin/switch")(self.switch_api)
        # 注册业务路由，并在路由函数中检查开关状态
        self.app.add_api_route(
            "/v1/chat/completions",
            self.chat_completions,
            methods=["POST"]
        )

    async def switch_api(self, enable: bool):
        """
        通过调用此接口控制全局开关
        例如：POST /admin/switch?enable=false 将关闭接口
        """
        return {"API_ENABLED": self.api_on_flag}

    def merge_messages(self, messages_dict: list, messages_temp: list) -> list:
        existing_messages = {tuple(msg.items()) for msg in messages_dict}
        for msg in messages_temp:
            if tuple(msg.items()) not in existing_messages:
                messages_dict.append(msg)
        return messages_dict

    async def chat_completions(self, request_data: ChatCompletionRequest, authorization: Optional[str] = Header(None)):
        # 首先检查全局开关状态
        if not self.api_on_flag:
            raise HTTPException(status_code=503, detail="API is disabled")

        # 认证检查
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authentication")
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != "valid_api_key":
            raise HTTPException(status_code=401, detail="Invalid authentication")

        if not request_data.messages or request_data.messages[-1].role != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")

        self.model_name = request_data.model

        if self.model_instance is None:
            local_model_path = common_const.default_model_path
            self.model_instance = model_generate(model_path=os.path.join(local_model_path, self.model_name))
            self.model_instance.pipeline_question()

        messages_as_dicts = [msg.dict() for msg in request_data.messages]
        self.merge_messages(self.model_instance.message_dict, messages_as_dicts)
        try:
            self.model_instance.message_dict.remove(request_data.messages[-1].dict())
        except ValueError:
            pass

        try:
            response_text = self.model_instance.pipeline_answer(request_data.messages[-1].content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        user_message = request_data.messages[-1]
        result = {
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
                "prompt_tokens": len(user_message.content.split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(user_message.content.split()) + len(response_text.split())
            }
        }
        return result

    def run(self):
        uvicorn.run("interface.api_interface_fastapi:app", host="0.0.0.0", port=7783, reload=False)

    def thread_run(self):
        # 使用导入字符串启动以支持 reload 功能
        threading.Thread(target=self.run).start()


# 在模块级别实例化并暴露应用
resource = FastAPIChatCompletionResource(True, None)
app = resource.app
