import os
import json
from llama_cpp import Llama
from transformers import AutoTokenizer

# 定义模型所在的本地文件夹和 gguf 模型文件名称
model_dir = r"C:\AppData\ai\ai_model\lmstudio-community\DeepSeek-R1-Distill-Qwen-1.5B-GGUF"
gguf_model_file = "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf"
model_path = os.path.join(model_dir, gguf_model_file)

# 加载 gguf 模型（仅模型权重，用 llama_cpp 加载）
llm = Llama(
    model_path=model_path,
    n_ctx=2048,      # 上下文长度，根据模型能力调整
    n_threads=8,     # 使用 CPU 线程数
    n_gpu_layers=35  # 如果有 GPU，可启用 GPU 加速的层数
)

# 尝试从本地模型文件夹加载 tokenizer 配置
# 要求该文件夹中存在有效的 tokenizer 配置文件（例如 tokenizer_config.json）
try:
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
except Exception as e:
    print("从本地加载 tokenizer 失败：", e)
    # 如果本地没有 tokenizer 配置文件，可尝试创建一个最简配置文件
    tokenizer_config_path = os.path.join(model_dir, "tokenizer_config.json")
    if not os.path.exists(tokenizer_config_path):
        minimal_config = {
            "model_type": "gpt2",
            "tokenizer_class": "GPT2Tokenizer"
        }
        with open(tokenizer_config_path, "w", encoding="utf-8") as f:
            json.dump(minimal_config, f, indent=4)
        print("已在模型目录下创建 minimal tokenizer_config.json")
        tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    else:
        raise

# 测试模型生成
prompt = "你好，请简单介绍一下人工智能。"
print("Prompt:", prompt)
result = llm(prompt=prompt, max_tokens=100, temperature=0.7, top_k=40)
print("模型输出：", result["choices"][0]["text"])

# 测试 tokenizer 对 prompt 的分词效果
tokens = tokenizer.encode(prompt)
print("分词结果：", tokens)
