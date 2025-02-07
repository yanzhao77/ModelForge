import os
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

from pytorch.base_generate import base_generate

# 设置环境变量
os.environ["HF_MODELS_HOME"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# 指定本地模型路径
local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
model_name = "Qwen2.5-0.5B"  # 请替换为实际的模型名称
defeat_model_path = os.path.join(local_model_path, model_name)


class model_generate(base_generate):
    def __init__(self, model_path=defeat_model_path, max_new_tokens=500, do_sample=True, temperature=0.9, top_k=50,
                 input_max_length=2048):
        super().__init__()
        try:
            # 加载预训练模型和分词器
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                local_files_only=True
            )
            self.command = []
            self.max_new_tokens = max_new_tokens  # 生成的新 tokens 数量，可以根据需要调整
            self.do_sample = do_sample  # 启用基于温度的采样
            self.temperature = temperature  # 控制生成文本的多样性
            self.top_k = top_k  # 控制生成文本的质量
            self.input_max_length = input_max_length  # 指定序列的最大长度。如果序列超过这个长度，将会被截断；如果序列短于这个长度，将会被填充
            self.is_running = True  # 标志变量，控制对话是否继续
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            self.is_running = False
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
            self.release_resources()
            self.is_running = False
            return

        # 对输入进行编码
        inputs = self.tokenizer(value, return_tensors="pt",  # 返回 PyTorch 张量
                                padding=True,  # 对输入序列进行填充
                                truncation=True,  # 对超过 max_length 的序列进行截断
                                max_length=self.input_max_length
                                ).to(
            self.device)
        self.command.append(value)
        # 生成响应
        outputs = self.model.generate(
            inputs.input_ids,
            attention_mask=inputs.attention_mask,
            max_new_tokens=self.max_new_tokens,  # 生成的新 tokens 数量，可以根据需要调整
            pad_token_id=self.tokenizer.pad_token_id,
            do_sample=self.do_sample,  # 启用基于温度的采样
            temperature=self.temperature,  # 控制生成文本的多样性
            top_k=self.top_k,  # 控制生成文本的质量
        )
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        self.command.append(response)
        # 打印模型的响应
        return response

    def release_resources(self):
        # 释放资源
        self.model.to("cpu")  # 将模型移回 CPU
        del self.model
        del self.tokenizer
        torch.cuda.empty_cache()  # 清理 GPU 缓存（如果有使用 GPU）


if __name__ == '__main__':
    model_generate = model_generate()
    model_generate.pipeline_question()
    while model_generate.is_running:
        value = input("你: ")
        result = model_generate.pipeline_answer(value)
        print("我: ", result)