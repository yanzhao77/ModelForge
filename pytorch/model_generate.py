import os
import re
import time

from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

from common.const.common_const import common_const
from pytorch.base_generate import base_generate
from pytorch.webSearcher import WebSearcher

# 新增：导入llama-cpp-python
try:
    from llama_cpp import Llama
    llama_cpp_available = True
except ImportError:
    llama_cpp_available = False

os.environ["HF_MODELS_HOME"] = common_const.default_model_path
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["ENABLE_FLASH_ATTENTION"] = "ON"
local_model_path = common_const.default_model_path
model_name = "DeepSeek-R1-Distill-Qwen-1.5B"
defeat_model_path = os.path.join(local_model_path, model_name)

def is_gguf_model(model_path):
    # 判断是否为gguf文件
    if os.path.isfile(model_path) and model_path.lower().endswith(".gguf"):
        return True
    # 目录下是否有gguf文件
    if os.path.isdir(model_path):
        for f in os.listdir(model_path):
            if f.lower().endswith(".gguf"):
                return True
    return False

def monitor_performance(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"{func.__name__} 执行耗时: {time.time() - start:.2f}s")
        return result
    return wrapper

class model_generate(base_generate):
    def __init__(self,
                 model_path=defeat_model_path,
                 max_new_tokens=2048,
                 do_sample=True,
                 temperature=0.7,
                 top_k=50,
                 input_max_length=4096,
                 message_dict: dict = None,
                 repetition_penalty=1.2,
                 is_deepSeek=False,
                 online_search=False,
                 ):
        super().__init__()
        self.model_path = model_path
        self.max_new_tokens = max_new_tokens
        self.do_sample = do_sample
        self.temperature = temperature
        self.top_k = top_k
        self.input_max_length = input_max_length
        self.is_running = True
        self.message_dict = [] if message_dict is None else message_dict
        self.repetition_penalty = repetition_penalty
        self.is_deepSeek = is_deepSeek
        self.online_search = online_search
        self.generation_priority = {
            "normal": {"num_beams": 3, "max_new_tokens": 500},
            "speed": {"num_beams": 1, "max_new_tokens": 300},
            "quality": {"num_beams": 5, "max_new_tokens": 800}
        }
        self.is_gguf = is_gguf_model(model_path)
        self.llama_cpp_model = None
        try:
            if self.is_gguf:
                if not llama_cpp_available:
                    raise ImportError("llama-cpp-python未安装，无法加载gguf模型")
                # 查找gguf文件路径
                if os.path.isfile(model_path):
                    gguf_path = model_path
                else:
                    gguf_files = [os.path.join(model_path, f) for f in os.listdir(model_path) if f.lower().endswith(".gguf")]
                    if not gguf_files:
                        raise FileNotFoundError("未找到gguf模型文件")
                    gguf_path = gguf_files[0]
                self.llama_cpp_model = Llama(model_path=gguf_path, n_ctx=self.input_max_length)
                self.tokenizer = None  # llama-cpp自带tokenizer
                print(f"已使用llama-cpp-python加载gguf模型: {gguf_path}")
            else:
                self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            self.is_running = False
            return

    def pipeline_question(self):
        try:
            if self.is_gguf:
                print("已加载gguf模型，准备推理。")
                self.device = "cpu"
                self.model = self.llama_cpp_model
                print("输入 'exit' 退出")
            else:
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_path,
                    trust_remote_code=True,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
                ).to(self.device)
                print(f"Using device: {self.device}")
                self.model.eval()
                print("模型加载完成，输入 'exit' 退出")
        except Exception as e:
            print(f"Error during model inference: {e}")
            self.is_running = False

    def pipeline_answer(self, question):
        if question.lower() == 'exit':
            print("退出对话")
            self.release_resources()
            self.is_running = False
            return

        if self.need_web_search(question) or self.online_search:
            search_results = WebSearcher.cached_search(question)
            search_context = "\n".join([f"• {item['title']}: {item['content']}" for item in search_results])
            question = f"{question}\n[网络搜索结果]:\n{search_context}"
        self.message_dict.append({
            "role": "user",
            "content": f"{question}\n请用中文回答"
        })
        conversation = ""
        for msg in self.message_dict:
            if msg["role"] == "user":
                conversation += f"User: {msg['content']}\n"
            else:
                conversation += f"Assistant: {msg['content']}\n"
        conversation += "Assistant: "
        try:
            response = self.generate_response(conversation)
        except RuntimeError as e:
            if "CUDA out of memory" in str(e):
                self.handle_memory_error()
                return "显存不足，请减少生成长度或重试"
            return f"运行时错误: {str(e)}"
        except Exception as e:
            return f"发生异常: {str(e)}"

        # 将助手的回答也添加到对话历史中
        self.message_dict.append({"role": "assistant", "content": response})
        # 打印模型的响应
        return response

    def format_response(self, text):
        """格式化响应文本"""
        # 自动分段处理
        text = re.sub(r"(\n{3,})", "\n\n", text)  # 合并多余空行
        return text.strip()

    @monitor_performance
    def generate_response(self, prompt):
        if self.is_gguf:
            # llama-cpp-python推理
            output = self.llama_cpp_model(
                prompt,
                max_tokens=self.max_new_tokens,
                temperature=self.temperature,
                top_k=self.top_k,
                stop=["User:"]
            )
            response = output["choices"][0]["text"]
            return self.format_response(response)
        else:
            generation_config = self._get_generation_config()
            tokens = self.tokenizer.encode(prompt, truncation=False)
            if len(tokens) > self.input_max_length - 100:
                truncated = self.tokenizer.decode(
                    tokens[:self._get_truncate_length()],
                    skip_special_tokens=True
                )
                prompt = f"[内容过长已截断]...{truncated}"
            with torch.inference_mode():
                inputs = self.tokenizer(
                    prompt,
                    return_tensors="pt",
                    max_length=self.input_max_length,
                    truncation=True
                ).to(self.device)
                if inputs.input_ids.shape[1] > 512:
                    generation_config["num_beams"] = max(1, generation_config["num_beams"] - 1)
                    generation_config["temperature"] = max(0.4, generation_config["temperature"])
                outputs = self.model.generate(
                    **inputs,
                    **generation_config
                )
                response = self.tokenizer.decode(
                    outputs[0],
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=True
                )
            return self.postprocess_response(response, original_prompt=prompt)

    def format_response(self, text):
        """格式化响应文本"""
        # 自动分段处理
        text = re.sub(r"(\n{3,})", "\n\n", text)  # 合并多余空行
        return text.strip()

    def _get_generation_config(self):
        """动态生成参数配置"""
        base_config = {
            "max_new_tokens": self.max_new_tokens,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": 0.9,
            "repetition_penalty": self.repetition_penalty,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
            "do_sample": self.do_sample,
            "early_stopping": True
        }

        if self.is_deepSeek:
            # 深度思考模式参数
            return {
                **base_config,
                "num_beams": 5,
                "temperature": max(0.5, self.temperature),
                "no_repeat_ngram_size": 3,
                "length_penalty": 1.2,
                "max_new_tokens": min(self.max_new_tokens, 800)
            }
        else:
            # 快速响应模式参数
            return {
                **base_config,
                "num_beams": 1 if self.do_sample else 3,
                "temperature": min(0.9, self.temperature + 0.2),
                "top_k": max(30, self.top_k),
                "max_new_tokens": min(self.max_new_tokens, 400)
            }

    def _get_truncate_length(self):
        """动态截断长度策略"""
        if self.is_deepSeek:
            return self.input_max_length - 200  # 保留更多上下文
        else:
            return self.input_max_length - 100  # 更激进的截断

    def postprocess_response(self, response, original_prompt):
        response = self.release_response(response)
        """差异化后处理"""
        if self.is_deepSeek:
            # 深度思考模式后处理
            return self._deep_postprocess(response, original_prompt)
        else:
            # 快速模式后处理
            return self._fast_postprocess(response, original_prompt)

    def _deep_postprocess(self, response, original_prompt):
        """深度思考模式后处理"""
        # 提取结构化内容
        prompt_len = len(original_prompt)
        clean_response = response[prompt_len:].strip()

        # 添加格式优化
        structured_response = ""
        for i, line in enumerate(clean_response.split('\n')):
            if "步骤" in line or "分析" in line:
                structured_response += f"\n## 分析阶段 {i + 1} ##\n{line}"
            else:
                structured_response += line
        return self.format_response(structured_response)

    def _fast_postprocess(self, response, original_prompt):
        """快速响应后处理"""
        # 直接提取有效内容
        return self.format_response(response.strip())

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

    def need_web_search(self, question: str) -> bool:
        """基于关键词的简单搜索需求判断"""
        search_keywords = [
            "最新", "当前", "现在", "搜索", "过去", "推荐", "新闻", "实时", "怎么安装", "如何配置",
        ]
        return any(keyword in question for keyword in search_keywords)

    def handle_memory_error(self):
        """内存错误处理策略"""
        torch.cuda.empty_cache()
        self.model.to('cpu')
        # 自动降级配置
        self.max_new_tokens = min(self.max_new_tokens, 300)
        self.temperature = max(self.temperature, 0.5)
