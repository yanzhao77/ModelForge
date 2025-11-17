import os
from llama_cpp import Llama


def load_gguf_model(model_file_path, n_ctx=2048, n_threads=8, n_gpu_layers=35):
    """
    加载本地 GGUF 模型文件。

    参数：
        model_file_path: GGUF 模型文件的完整路径（例如 ".../model.gguf"）
        n_ctx: 上下文窗口大小
        n_threads: 使用的 CPU 线程数
        n_gpu_layers: 启用 GPU 加速的层数（无 GPU 可设为 0）
    返回：
        llama_cpp.Llama 实例
    """
    model = Llama(
        model_path=model_file_path,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers
    )
    return model


if __name__ == '__main__':
    # 模型所在文件夹和模型文件名（请根据实际情况修改）
    model_dir = r"C:\AppData\ai\ai_model\lmstudio-community\DeepSeek-R1-Distill-Qwen-1.5B-GGUF"
    gguf_model_filename = "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf"
    model_file = os.path.join(model_dir, gguf_model_filename)

    # 加载模型
    print("正在加载 GGUF 模型，请稍候...")
    model = load_gguf_model(model_file, n_ctx=2048, n_threads=8, n_gpu_layers=35)
    print("模型加载完成！")

    # 定义提示词（prompt）
    prompt = "你好，请讲一个智障的小伙。"
    print("Prompt:", prompt)

    # 生成文本（生成参数可根据需求调整）
    result = model(
        prompt=prompt,
        max_tokens=100,  # 输出 token 数量上限
        temperature=0.7,  # 温度控制采样多样性
        top_k=40  # top_k 采样策略
    )
    output_text = result["choices"][0]["text"]
    print("模型输出：", output_text)
