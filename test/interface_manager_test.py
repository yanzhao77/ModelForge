import json
import os

from openai import OpenAI

from common.const.common_const import interface_type_enum
from pytorch.base_generate import base_generate

# 设置环境变量
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


class interface_generate(base_generate):
    def __init__(self, api_key: str, base_url: str, interface_model_name: str,
                 model_type: str = interface_type_enum.openai.value,
                 role: str = "user", interface_temperature: int = None, interface_top_p: float = None,
                 interface_n: int = None, interface_max_tokens: int = None,
                 interface_presence_penalty: float = None, interface_frequency_penalty: float = None,
                 interface_timeout: int = None):
        super().__init__()
        try:
            # 加载预训练模型和分词器
            self.command = []
            self.api_key = api_key
            self.base_url = base_url
            self.interface_model_name = interface_model_name
            self.model_type = model_type
            self.role = role
            self.client = None

            self.interface_temperature = interface_temperature
            self.interface_top_p = interface_top_p
            self.interface_n = interface_n
            self.interface_max_tokens = interface_max_tokens
            self.interface_presence_penalty = interface_presence_penalty
            self.interface_frequency_penalty = interface_frequency_penalty
            self.interface_timeout = interface_timeout
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            return

    def _create_client(self):
        return OpenAI(
            api_key=self.api_key,  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
            base_url=self.base_url,  # 填写DashScope SDK的base_url
        )

    def pipeline_question(self):
        try:
            self.client = self._create_client()
            # 开始持续对话
            print("开始对话，输入 'exit' 退出。")
        except Exception as e:
            print(f"Error during model inference: {e}")
            raise  # 抛出异常以便调用者可以捕获

    def pipeline_answer(self, value):
        if value.lower() == 'exit':
            print("结束对话。")
            return

        self.command.append(value)

        # 构建参数字典
        kwargs = {
            'model': self.interface_model_name,
            'messages': [{'role': self.role, 'content': value}]
        }

        # 检查并添加其他参数
        if self.interface_temperature is not None:
            kwargs['temperature'] = self.interface_temperature
        if self.interface_top_p is not None:
            kwargs['top_p'] = self.interface_top_p
        if self.interface_n is not None:
            kwargs['n'] = self.interface_n
        if self.interface_max_tokens is not None:
            kwargs['max_tokens'] = self.interface_max_tokens
        if self.interface_presence_penalty is not None:
            kwargs['presence_penalty'] = self.interface_presence_penalty
        if self.interface_frequency_penalty is not None:
            kwargs['frequency_penalty'] = self.interface_frequency_penalty
        if self.interface_timeout is not None:
            kwargs['timeout'] = self.interface_timeout

        # 调用 API
        try:
            completion = self.client.chat.completions.create(**kwargs)
            result = completion.model_dump_json()
            result_dict = json.loads(result)['choices'][0]['message']
            self.command.append(result_dict['content'])
            return result_dict['content']
        except Exception as e:
            print(f"Error during model inference: {e}")
            return ""


if __name__ == '__main__':
    api_key = 'sk-3f2d7473809f4f0492976b33f3146299'  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"  # 填写DashScope SDK的base_url
    interface_model_name = "qwen1.5-0.5b-chat"
    role = 'user'
    model_type = "OpenAI"
    model = interface_generate(api_key, base_url, interface_model_name, model_type, role)

    model.pipeline_question()
    value = model.pipeline_answer("你好啊")
    print(value)
