import os

import dashscope

dashscope.api_key = "sk-3f2d7473809f4f0492976b33f3146299"
# 设置环境变量
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


# 指定本地模型路径


class interface_generate():
    def __init__(self):
        try:
            # 加载预训练模型和分词器

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
            pass
            # 开始持续对话
            print("开始对话，输入 'exit' 退出。")
            # prompt = input("你: ")
        except Exception as e:
            print(f"Error during model inference: {e}")

    def pipeline_answer(self, value):
        if value.lower() == 'exit':
            print("结束对话。")
            return
        self.command.append(value)
        # 对输入进行编码

        pass
        result = ""
        self.command.append(result)
        # 打印模型的响应
        return result


if __name__ == '__main__':
    model = interface_generate()
    model.pipeline_question()
    print("开始对话，输入 'exit' 退出。")
    prompt = input("你: ")
    while True:
        response = model.pipeline_answer(prompt)
        print(f"模型: {response}")
