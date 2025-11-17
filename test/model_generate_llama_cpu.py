import os
import re
import time
import gc
from functools import wraps
from llama_cpp import Llama

from common.const.common_const import common_const
from pytorch.base_generate import base_generate
from pytorch.webSearcher import WebSearcher

# 指定本地模型路径（请根据实际路径修改）
common_const.default_model_path = 'C:\\AppData\\ai\\ai_model\\stories15M_MOE'
model_name = "moe_shakespeare15M.gguf"  # 请替换为实际的模型文件名
MODEL_PATH = os.path.join(common_const.default_model_path, model_name)

# 强制使用 CPU
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # 隐藏所有 GPU
os.environ["HF_MODELS_HOME"] = common_const.default_model_path
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


def monitor_performance(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        start_time = time.time()
        try:
            return func(self, *args, **kwargs)
        finally:
            elapsed = time.time() - start_time
            print(f"生成耗时: {elapsed:.2f}s | Device: CPU | Threads: {getattr(self, 'n_threads', 'N/A')}")
    return wrapper


class model_generate(base_generate):
    """仅使用 llama_cpp (gguf) 的纯 CPU 推理封装"""

    def __init__(self,
                 model_path=MODEL_PATH,
                 n_ctx=2048,
                 n_threads=None,
                 max_new_tokens=512,
                 temperature=0.7,
                 top_k=50,
                 message_dict: dict = None,
                 is_deepSeek=False,
                 online_search=False):

        super().__init__()

        if not model_path.endswith('.gguf'):
            raise ValueError('model_path must be a .gguf file for llama_cpp-only mode')

        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads or max(1, min(8, (os.cpu_count() or 1)))

        # 生成参数
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_k = top_k
        self.is_running = True
        self.message_dict = [] if message_dict is None else message_dict
        self.is_deepSeek = is_deepSeek
        self.online_search = online_search

        self._load_llama_model()

    def _load_llama_model(self):
        try:
            print(f"加载 llama.cpp 模型: {self.model_path} | threads={self.n_threads} | n_ctx={self.n_ctx}")
            self.llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
            )
        except Exception as e:
            print(f"加载 llama_cpp 模型失败: {e}")
            self.is_running = False
            raise

    def pipeline_question(self):
        if not getattr(self, 'llm', None):
            print('模型未加载成功，无法运行对话')
            self.is_running = False
            return

        print("使用 llama_cpp (CPU) 进行推理，输入 'exit' 退出。")

    def pipeline_answer(self, question: str):
        if question.lower() == 'exit':
            print('结束对话')
            self.release_resources()
            self.is_running = False
            return

        if self.need_web_search(question) or self.online_search:
            search_results = WebSearcher.cached_search(question)
            search_context = "\n".join([f"• {item['title']}: {item['content']}" for item in search_results])
            question = f"{question}\n[相关网络信息]:\n{search_context}"

        self.message_dict.append({"role": "user", "content": question})

        # 构造对话历史（保留最近几轮，防止上下文过长）
        conversation = ''
        for msg in self.message_dict[-10:]:
            if msg['role'] == 'user':
                conversation += f"User: {msg['content']}\n"
            else:
                conversation += f"Assistant: {msg['content']}\n"
        conversation += 'Assistant:'

        try:
            response = self.generate_response(conversation)
        except RuntimeError as e:
            print(f"运行时错误: {e}")
            self.handle_memory_error()
            return '生成失败，已尝试回收内存并缩短长度，请重试。'
        except Exception as e:
            return f"意外错误：{e}"

        # 保存回答
        self.message_dict.append({"role": "assistant", "content": response})
        return response

    def format_response(self, text: str) -> str:
        text = re.sub(r"(\n{3,})", "\n\n", text)
        return text.strip()

    @monitor_performance
    def generate_response(self, prompt: str) -> str:
        """通过 llama_cpp 生成文本。对 n_ctx 长度做保护性截断"""
        if not getattr(self, 'llm', None):
            raise RuntimeError('llm 未加载')

        # 组合提示词
        if self.is_deepSeek:
            final_prompt = (
                "【深度思考模式】请分步分析：\n"
                "1. 问题本质\n2. 证据验证\n3. 结论\n"
                f"对话历史：\n{prompt}\n回答："
            )
        else:
            final_prompt = f"{prompt}\n"

        # 截断超长 prompt
        max_chars = max(256, int(self.n_ctx * 2.5))  # 粗略对应 n_ctx tokens
        if len(final_prompt) > max_chars:
            final_prompt = final_prompt[-max_chars:]
            final_prompt = '[截断]...' + final_prompt

        try:
            output = self.llm(
                prompt=final_prompt,
                max_tokens=self.max_new_tokens,
                temperature=self.temperature,
                top_k=self.top_k,
            )
        except Exception as e:
            raise RuntimeError(f"llama_cpp 推理失败: {e}")

        # 解析输出
        text = ''
        try:
            if isinstance(output, dict) and 'choices' in output and len(output['choices']) > 0:
                text = output['choices'][0].get('text', '')
            elif isinstance(output, str):
                text = output
            else:
                text = str(output)
        except Exception:
            text = str(output)

        return self.format_response(text)

    def need_web_search(self, question: str) -> bool:
        search_keywords = ["最新", "当前", "现在", "搜索", "过去", "推荐", "新闻", "实时", "怎么安装", "如何配置"]
        return any(k in question for k in search_keywords)

    def handle_memory_error(self):
        self.max_new_tokens = max(64, int(self.max_new_tokens * 0.5))
        gc.collect()
        print(f"已降低 max_new_tokens 至 {self.max_new_tokens} 并触发垃圾回收")

    def release_resources(self):
        try:
            if getattr(self, 'llm', None):
                try:
                    del self.llm
                except Exception:
                    pass
            gc.collect()
            print('已释放 llama_cpp 资源并回收内存')
        except Exception as e:
            print(f"释放资源时出错: {e}")


if __name__ == '__main__':
    gen = model_generate()
    gen.pipeline_question()

    while gen.is_running:
        try:
            user_input = input('你: ')
        except (KeyboardInterrupt, EOFError):
            print('\n退出')
            gen.release_resources()
            break
        resp = gen.pipeline_answer(user_input)
        print(f"助手: {resp}")
