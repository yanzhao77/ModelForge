import json
import os

from openai import OpenAI

from common.const.common_const import interface_type_enum

# 设置环境变量
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


class interface_generate():
    def __init__(self, api_key=str, base_url=str, model_name=str, model_type=interface_type_enum.openai.value,
                 role=str):
        try:
            # 加载预训练模型和分词器
            self.command = []
            self.api_key = api_key
            self.base_url = base_url
            self.model_name = model_name
            self.model_type = model_type
            self.role = role
            self.client = None
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            return

    def pipeline_question(self):
        try:
            self.client = OpenAI(
                api_key=self.api_key,  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
                base_url=self.base_url,  # 填写DashScope SDK的base_url
            )
            # 开始持续对话
            print("开始对话，输入 'exit' 退出。")
        except Exception as e:
            print(f"Error during model inference: {e}")

    def pipeline_answer(self, value):
        if value.lower() == 'exit':
            print("结束对话。")
            return
        self.command.append(value)
        # 对输入进行编码

        completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{'role': f'{self.role}', 'content': f'{value}'}]
        )
        result = completion.model_dump_json()
        result_dict = json.loads(result)['choices'][0]['message']
        result_content = result_dict['content']
        self.command.append(result_content)
        # 打印模型的响应
        return result_content
