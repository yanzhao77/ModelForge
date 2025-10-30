import os
import re
import time
from llama_cpp import Llama
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

from common.const.common_const import common_const
from pytorch.base_generate import base_generate
from pytorch.webSearcher import WebSearcher

common_const.default_model_path = 'C:\\AppData\\ai\\ai_model\\stories15M_MOE'

# 设置环境变量
os.environ["HF_MODELS_HOME"] = common_const.default_model_path
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["ENABLE_FLASH_ATTENTION"] = "ON"
# 指定本地模型路径
local_model_path = common_const.default_model_path
model_name = "moe_shakespeare15M.gguf"  # 请替换为实际的模型名称
defeat_model_path = os.path.join(local_model_path, model_name)


def get_model_type(path):
    if os.path.isdir(path):
        return "transformers"
    elif path.endswith(".gguf"):
        return "gguf"
    else:
        raise ValueError("Unsupported model format")


def monitor_performance(func):
    def wrapper(self, *args, **kwargs):
        start_time = time.time()

        try:
            result = func(self, *args, **kwargs)
        except Exception as e:
            print(f"Error occurred in {func.__name__}: {e}")
            raise
        finally:
            elapsed_time = time.time() - start_time
            print(f"生成耗时: {elapsed_time:.2f}s")
        return result

    return wrapper


# 在初始化时根据类型选择加载器
model_type = get_model_type(defeat_model_path)


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
        # 根据文件后缀选择加载方式
        if model_path.endswith(".gguf"):
            self._load_gguf_model(model_path)
        else:
            self._load_transformers_model(model_path)
        try:
            # 加载预训练模型和分词器
            self.model_path = model_path
            self.command = []
            self.max_new_tokens = max_new_tokens  # 生成的新 tokens 数量
            self.do_sample = do_sample  # 启用基于温度的采样
            self.temperature = temperature  # 控制生成文本的多样性
            self.top_k = top_k  # 控制生成文本的质量
            self.input_max_length = input_max_length  # 指定序列的最大长度
            self.is_running = True  # 标志变量，控制对话是否继续
            self.message_dict = [] if message_dict is None else message_dict  # 维护对话历史
            self.repetition_penalty = repetition_penalty
            self.is_deepSeek = is_deepSeek
            self.online_search = online_search
            self.generation_priority = {
                "normal": {"num_beams": 3, "max_new_tokens": 500},
                "speed": {"num_beams": 1, "max_new_tokens": 300},
                "quality": {"num_beams": 5, "max_new_tokens": 800}
            }
        except Exception as e:
            print(f"Error loading model or tokenizer: {e}")
            self.is_running = False
            return

    def _load_transformers_model(self, path):
        self.tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        # CPU模式下使用float32
        self.model = AutoModelForCausalLM.from_pretrained(
            path,
            trust_remote_code=True,
            torch_dtype=torch.float32  # CPU使用float32
        ).to("cpu")  # 明确指定CPU

    def _load_gguf_model(self, path):
        # GGUF模型在CPU上运行，设置n_gpu_layers=0
        self.llm = Llama(
            model_path=path,
            n_ctx=2048,  # 上下文长度
            n_threads=8,  # CPU线程数
            n_gpu_layers=0  # 纯CPU模式，不使用GPU
        )
        # 需要创建兼容的tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            defeat_model_path,
            trust_remote_code=True
        )

    def pipeline_question(self):
        try:
            # 确保模型和数据都在 CPU 上
            self.device = torch.device("cpu")
            print("使用CPU设备运行")
            self.model.eval()
            print("开始对话，输入 'exit' 退出。")
        except Exception as e:
            print(f"Error during model inference: {e}")
            self.is_running = False

    def pipeline_answer(self, question):
        if question.lower() == 'exit':
            print("结束对话。")
            self.release_resources()
            self.is_running = False
            return

        # 网络搜索增强
        if self.need_web_search(question) or self.online_search:
            search_results = WebSearcher.cached_search(question)
            search_context = "\n".join([f"• {item['title']}: {item['content']}"
                                        for item in search_results])
            question = f"{question}\n[相关网络信息]:\n{search_context}"

        self.message_dict.append({
            "role": "user",
            "content": f"{question}\n思考后给出详细回答："
        })
        # 构造包含历史对话的完整提示
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
            return f"生成错误：{str(e)}"
        except Exception as e:
            return f"意外错误：{str(e)}"

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
        if hasattr(self, 'llm'):
            # GGUF模型的生成方式
            output = self.llm(
                prompt=prompt,
                max_tokens=self.max_new_tokens,
                temperature=self.temperature,
                top_k=self.top_k
            )
            return output['choices'][0]['text']
        else:
            # 动态生成参数配置
            generation_config = self._get_generation_config()

            # 添加系统提示词增强思考深度
            if self.is_deepSeek:
                enhanced_prompt = (
                    "【深度思考模式】你是一个严谨的AI助手，请按照以下步骤分析：\n"
                    "1. 问题本质分析\n2. 多角度验证\n3. 逻辑推理\n4. 最终结论\n"
                    f"对话历史：{prompt}\n回答："
                )
            else:
                enhanced_prompt = (
                    "【快速响应模式】请直接给出简明回答：\n"
                    f"{prompt}\n回答："
                )
                generation_config["early_stopping"] = False  # early_stopping只适用于波束搜索

            # 对整段对话进行编码
            tokens = self.tokenizer.encode(enhanced_prompt, truncation=False)
            if len(tokens) > self.input_max_length - 100:
                truncated = self.tokenizer.decode(
                    tokens[:self._get_truncate_length()],
                    skip_special_tokens=True
                )
                enhanced_prompt = f"[截断提示]...{truncated}"

            # CPU模式下使用CPU
            inputs = self.tokenizer(
                enhanced_prompt,
                return_tensors="pt",
                max_length=self.input_max_length,
                truncation=True
            ).to("cpu")

            # 动态调整长文本策略
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
        # 释放CPU资源
        self.model.to("cpu")  # 确保在CPU上
        del self.model
        del self.tokenizer

    def need_web_search(self, question: str) -> bool:
        """基于关键词的简单搜索需求判断"""
        search_keywords = [
            "最新", "当前", "现在", "搜索", "过去", "推荐", "新闻", "实时", "怎么安装", "如何配置",
        ]
        return any(keyword in question for keyword in search_keywords)


if __name__ == '__main__':
    generator = model_generate()
    generator.pipeline_question()

    while generator.is_running:
        user_input = input("你: ")
        response = generator.pipeline_answer(user_input)
        print(f"助手: {response}")