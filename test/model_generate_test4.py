import os

from transformers import AutoTokenizer, AutoModelForCausalLM
import torch


# 设置环境变量
os.environ["HF_MODELS_HOME"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# 指定本地模型路径
local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
model_name = "DeepSeek-R1-Distill-Qwen-1.5B"  # 请替换为实际的模型名称
defeat_model_path = os.path.join(local_model_path, model_name)

class DeepSeekModel:
    def __init__(self, model_path=defeat_model_path):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")

        # 加载tokenizer和模型
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            trust_remote_code=True,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
        ).to(self.device)

        # 设置模型为评估模式
        self.model.eval()

    def generate_response(self, prompt, max_length=2048, temperature=0.7):
        try:
            # 对输入进行编码
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

            # 生成回答
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_length=max_length,
                    temperature=temperature,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )

            # 解码输出
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return response

        except Exception as e:
            print(f"生成回答时发生错误: {str(e)}")
            return None


def main():
    # 初始化模型
    model = DeepSeekModel()

    # 测试对话
    while True:
        user_input = input("\n请输入您的问题 (输入 'quit' 退出): ")
        if user_input.lower() == 'quit':
            break

        response = model.generate_response(user_input)
        if response:
            print("\nDeepSeek:", response)


if __name__ == "__main__":
    main()


