from transformers import AutoModelForCausalLM, AutoTokenizer

# 加载模型和分词器
model_path = "E:\\workspace\\pythonDownloads\\ModelForge\\model\\"  # 替换为你的模型路径
model_name = model_path + "Janus-Pro-1B"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForCausalLM.from_pretrained(model_path)

# 将模型设置为评估模式
model.eval()


def chat_with_model():
    print("开始与 Janus-Pro-1B 对话！输入 'exit' 结束对话。")
    chat_history = []

    while True:
        # 获取用户输入
        user_input = input("你: ")
        if user_input.lower() == "exit":
            print("对话结束。")
            break

        # 将用户输入添加到对话历史
        chat_history.append(f"用户: {user_input}")

        # 将对话历史拼接为模型输入
        input_text = " ".join(chat_history)

        # 分词并生成回复
        inputs = tokenizer(input_text, return_tensors="pt")
        reply_ids = model.generate(**inputs, max_length=200, num_return_sequences=1)
        reply = tokenizer.decode(reply_ids[0], skip_special_tokens=True)

        # 提取模型的最新回复
        model_reply = reply[len(input_text):].strip()
        print(f"Janus-Pro-1B: {model_reply}")

        # 将模型回复添加到对话历史
        chat_history.append(f"模型: {model_reply}")


if __name__ == '__main__':
    # 启动对话
    chat_with_model()
