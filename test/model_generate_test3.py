from transformers import AutoTokenizer, AutoModelForCausalLM
import torch


class ChatBot:
    def __init__(self, model_path="./DeepSeek-R1-Distill-Qwen-1.5B"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        # 加载 tokenizer 和模型（注意 trust_remote_code 参数，根据需要设定）
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            trust_remote_code=True,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
        ).to(self.device)
        self.model.eval()
        # 初始化对话历史（可根据需求预先设定初始提示词）
        self.history = ""

    def generate_response(self, prompt, max_length=2048, temperature=0.7):
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_length=max_length,
                temperature=temperature,
                top_p=0.9,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id
            )
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return self.release_result(response)

    def release_result(self, full_output):
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

    def chat(self):
        print("开始对话（输入 'quit' 退出）")
        while True:
            user_input = input("User: ").strip()
            if user_input.lower() == "quit":
                break
            # 更新对话历史：加入用户输入
            self.history += f"User: {user_input}\n"
            # 构造当前 prompt：包括历史和一个角色提示
            current_prompt = self.history + "Assistant: "
            response = self.generate_response(current_prompt)
            # 简单处理返回结果（可以根据需要调整，或提取回复中 Assistant 部分）
            # 将模型输出追加到历史中
            self.history += f"Assistant: {response}\n"
            print("Assistant:", response)
            # 如果历史太长，需要做截断处理，确保不超过模型的最大输入长度


if __name__ == "__main__":
    chatbot = ChatBot(model_path="E:\workspace\pythonDownloads\ModelForge\model/DeepSeek-R1-Distill-Qwen-1.5B")
    chatbot.chat()
