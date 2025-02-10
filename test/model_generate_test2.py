import os
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
from pytorch.base_generate import base_generate

# 设置环境变量
os.environ["HF_MODELS_HOME"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# 指定本地模型路径
local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
model_name = "DeepSeek-R1-Distill-Qwen-1.5B"  # 请替换为实际的模型名称
defeat_model_path = os.path.join(local_model_path, model_name)


class model_generate(base_generate):
    def __init__(self,
                 model_path=defeat_model_path,
                 max_new_tokens=500,
                 do_sample=True,
                 temperature=0.9,
                 top_k=50,
                 input_max_length=2048,
                 interface_message_dict: dict = None):
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
            self.interface_message_dict = interface_message_dict
            self.history = []  # 维护对话历史
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            self.is_running = False
            return

    def pipeline_question(self):
        try:
            # 确保pad_token设置正确
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
        except Exception as e:
            print(f"Error during model inference: {e}")
            self.is_running = False

    def pipeline_answer(self, value):
        if value.lower() == 'exit':
            print("结束对话。")
            self.release_resources()
            self.is_running = False
            return

        try:
            # 添加用户输入到历史
            self.history.append({"role": "user", "content": value})

            # 动态维护历史长度
            while True:
                prompt = self._build_prompt()
                # 计算当前prompt的token长度（不进行实际编码）
                token_count = len(self.tokenizer.tokenize(prompt))
                if token_count <= self.input_max_length:
                    break
                # 删除最早的一对对话（用户+助手）
                if len(self.history) >= 2:
                    del self.history[0:2]
                else:
                    del self.history[0]

            # 编码并截断长文本
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,  # 保持自动截断
                max_length=self.input_max_length
            ).to(self.device)

            # 生成回复
            outputs = self.model.generate(
                inputs.input_ids,
                attention_mask=inputs.attention_mask,
                max_new_tokens=self.max_new_tokens,  # 生成的新 tokens 数量，可以根据需要调整
                pad_token_id=self.tokenizer.pad_token_id,
                do_sample=self.do_sample,  # 启用基于温度的采样
                temperature=self.temperature,  # 控制生成文本的多样性
                top_k=self.top_k,  # 控制生成文本的质量
                eos_token_id=self.tokenizer.eos_token_id,
            )

            # 提取新生成的回复内容
            new_tokens = outputs[0, inputs.input_ids.size(1):]
            response = self.tokenizer.decode(new_tokens, skip_special_tokens=True)

            # 将回复添加到历史
            self.history.append({"role": "assistant", "content": response.strip()})

            return response.strip()

        except Exception as e:
            print(f"生成错误: {e}")
            return "生成回复时出现错误，请稍后再试。"

    def _build_prompt(self):
        """构建符合Qwen格式的对话prompt"""
        prompt = ""
        for msg in self.history:
            if msg["role"] == "user":
                prompt += f"<|im_start|>user\n{msg['content']}<|im_end|>\n"
            elif msg["role"] == "assistant":
                prompt += f"<|im_start|>assistant\n{msg['content']}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        return prompt

    def release_resources(self):
        if hasattr(self, 'model'):
            self.model.to("cpu")
            del self.model
        if hasattr(self, 'tokenizer'):
            del self.tokenizer
        torch.cuda.empty_cache()

if __name__ == '__main__':
    generator = model_generate()
    generator.pipeline_question()

    while generator.is_running:
        user_input = input("你: ")
        response = generator.pipeline_answer(user_input)
        print(f"助手: {response}")