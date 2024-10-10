import os
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import random
from http import HTTPStatus
import dashscope
from openai import OpenAI
import requests
dashscope.api_key = "sk-3f2d7473809f4f0492976b33f3146299"
# 设置环境变量
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# 指定本地模型路径





class interface_generate():
    def __init__(self, model_path=defeat_model_path):
        try:
            # 加载预训练模型和分词器
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                local_files_only=True
            )
            self.command = []
            self.max_new_tokens = 500,  # 生成的新 tokens 数量，可以根据需要调整
            self.do_sample = True,  # 启用基于温度的采样
            self.temperature = 0.9,  # 控制生成文本的多样性
            self.top_k = 50,  # 控制生成文本的质量
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            return

    def pipeline_question(self):
        try:
            # 如果模型没有设置 pad_token_id，手动设置
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            if self.model.config.pad_token_id is None:
                self.model.config.pad_token_id = self.model.config.eos_token_id
            # 确保模型和数据都在 CPU 上
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model.to(self.device)
            # 开始持续对话
            print("开始对话，输入 'exit' 退出。")
            # prompt = input("你: ")
        except Exception as e:
            print(f"Error during model inference: {e}")

    def pipeline_answer(self, value):
        if value.lower() == 'exit':
            print("结束对话。")
            return

        # 对输入进行编码
        inputs = self.tokenizer(value, return_tensors="pt", padding=True, truncation=True, max_length=2048).to(
            self.device)
        self.command.append(value)
        # 生成响应
        outputs = self.model.generate(
            inputs.input_ids,
            attention_mask=inputs.attention_mask,
            max_new_tokens=500,  # 生成的新 tokens 数量，可以根据需要调整
            pad_token_id=self.tokenizer.pad_token_id,
            do_sample=True,  # 启用基于温度的采样
            temperature=0.9,  # 控制生成文本的多样性
            top_k=50,  # 控制生成文本的质量
        )
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        self.command.append(response)
        # 打印模型的响应
        return response


if __name__ == '__main__':
    model = model_generate("")
    model.pipeline_question()
    print("开始对话，输入 'exit' 退出。")
    prompt = input("你: ")
    while True:
        response = model.pipeline_answer(prompt)
        print(f"模型: {response}")
