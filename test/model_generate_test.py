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
                 input_max_length=4096,
                 message_dict: dict = None):
        super().__init__()
        try:
            # 加载预训练模型和分词器
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
            self.model_path = model_path
            self.command = []
            self.max_new_tokens = max_new_tokens  # 生成的新 tokens 数量，可以根据需要调整
            self.do_sample = do_sample  # 启用基于温度的采样
            self.temperature = temperature  # 控制生成文本的多样性
            self.top_k = top_k  # 控制生成文本的质量
            self.input_max_length = input_max_length  # 指定序列的最大长度。如果序列超过这个长度，将会被截断；如果序列短于这个长度，将会被填充
            self.is_running = True  # 标志变量，控制对话是否继续
            self.message_dict = [] if message_dict is None else message_dict  # 维护对话历史
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            self.is_running = False
            return

    def pipeline_question(self):
        try:
            # 如果模型没有设置 pad_token_id，手动设置
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            # 确保模型和数据都在 CPU 上
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
            ).to(self.device)
            print(f"Using device: {self.device}")
            self.model.eval()
            # 开始持续对话
            print("开始对话，输入 'exit' 退出。")
            # prompt = input("你: ")
        except Exception as e:
            print(f"Error during model inference: {e}")
            self.is_running = False

    def pipeline_answer(self, value):
        if value.lower() == 'exit':
            print("结束对话。")
            self.release_resources()
            self.is_running = False
            return
        # 添加用户输入到历史
        self.message_dict.append({"role": "user", "content": value})

        # 构造包含历史对话的完整提示
        conversation = ""
        for msg in self.message_dict:
            if msg["role"] == "user":
                conversation += f"User: {msg['content']}\n"
            else:
                conversation += f"Assistant: {msg['content']}\n"
        conversation += "Assistant: "
        response = self.generate_response(conversation)
        # 将助手的回答也添加到对话历史中
        self.message_dict.append({"role": "assistant", "content": response})
        # 打印模型的响应
        return response

    def generate_response(self, prompt):
        # 对整段对话进行编码
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self.input_max_length
        ).to(self.device)
        # 生成响应
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_length=self.input_max_length,
                temperature=self.temperature,
                top_k=self.top_k,
                top_p=0.9,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id
            )
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return self.release_response(response)


    def release_response(self, full_output):
        # 假设prompt中最后一个角色是'User:'，我们需要找到它之后的部分作为助手的回答
        user_marker = "User:"
        assistant_marker = "Assistant:"
        if user_marker in full_output:
            # 找到最后一个'user'标记后的部分
            last_user_index = full_output.rfind(user_marker)
            if last_user_index != -1:
                # 检查是否有assistant的回答
                assistant_start = full_output.find(assistant_marker, last_user_index)
                if assistant_start != -1:
                    # 返回assistant的回答部分
                    response = full_output[assistant_start + len(assistant_marker):].strip()
                else:
                    response = ""
            else:
                # 如果没有找到user标记，则可能是只有assistant的回答
                response = full_output.strip()
        else:
            # 如果prompt中没有'user'标记，则直接返回解码后的输出
            response = full_output.strip()
        return response


    def release_resources(self):
        # 释放资源
        self.model.to("cpu")  # 将模型移回 CPU
        del self.model
        del self.tokenizer
        torch.cuda.empty_cache()  # 清理 GPU 缓存（如果有使用 GPU）


if __name__ == '__main__':
    generator = model_generate()
    generator.pipeline_question()

    while generator.is_running:
        user_input = input("你: ")
        response = generator.pipeline_answer(user_input)
        print(f"助手: {response}")


