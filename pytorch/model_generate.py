import os
import re
import time
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
from functools import wraps

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers.tokenization_utils import PreTrainedTokenizer
from transformers.modeling_utils import PreTrainedModel

from common.const.common_const import LoggerNames, get_logger, Constants
from pytorch.base_generate import BaseGenerate
from pytorch.webSearcher import WebSearcher

logger = get_logger(LoggerNames.MODEL)

# 设置环境变量
os.environ["HF_MODELS_HOME"] = str(Constants.APP_CONFIG.paths.model_dir)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["ENABLE_FLASH_ATTENTION"] = "ON"

@dataclass
class ModelConfig:
    """模型配置"""
    model_path: str = str(Constants.APP_CONFIG.paths.model_dir / Constants.APP_CONFIG.default_model_name)
    max_new_tokens: int = 2048
    do_sample: bool = True
    temperature: float = 0.7
    top_k: int = 50
    input_max_length: int = 4096
    message_dict: List[Dict[str, str]] = field(default_factory=list)
    repetition_penalty: float = 1.2
    is_deepseek: bool = False
    online_search: bool = False
    
    def __post_init__(self):
        """验证配置参数"""
        if not self.model_path:
            raise ValueError("模型路径不能为空")
        if self.max_new_tokens < 1:
            raise ValueError("max_new_tokens必须大于0")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature必须在0到2之间")
        if self.top_k < 1:
            raise ValueError("top_k必须大于0")
        if self.input_max_length < 1:
            raise ValueError("input_max_length必须大于0")
        if self.repetition_penalty < 0:
            raise ValueError("repetition_penalty必须大于0")

def monitor_performance(func):
    """性能监控装饰器"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        start_time = time.time()
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        if device.type == 'cuda':
            torch.cuda.reset_peak_memory_stats(device)

        try:
            result = func(self, *args, **kwargs)
            elapsed_time = time.time() - start_time
            
            if device.type == 'cuda':
                max_memory = torch.cuda.max_memory_allocated(device) // (1024 ** 2)
                logger.info(f"生成耗时: {elapsed_time:.2f}s, 显存峰值: {max_memory}MB")
            else:
                logger.info(f"生成耗时: {elapsed_time:.2f}s")
                
            return result
            
        except Exception as e:
            logger.error(f"函数 {func.__name__} 执行失败: {str(e)}")
            raise
            
    return wrapper

class ModelGenerate(BaseGenerate):
    """模型生成类"""
    
    def __init__(self, config: Optional[ModelConfig] = None):
        """初始化模型生成器"""
        super().__init__()
        try:
            self.config = config or ModelConfig()
            self.tokenizer: Optional[PreTrainedTokenizer] = None
            self.model: Optional[PreTrainedModel] = None
            self.device: torch.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.is_running: bool = True
            self.command: List[str] = []
            
            # 生成优先级配置
            self.generation_priority = {
                "normal": {"num_beams": 3, "max_new_tokens": 500},
                "speed": {"num_beams": 1, "max_new_tokens": 300},
                "quality": {"num_beams": 5, "max_new_tokens": 800}
            }
            
            logger.info(f"模型生成器初始化完成，使用设备: {self.device}")
        except Exception as e:
            logger.error(f"初始化失败: {str(e)}")
            self.is_running = False
            raise

    def pipeline_question(self) -> None:
        """准备模型管道"""
        try:
            # 加载分词器
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.config.model_path,
                trust_remote_code=True
            )
            
            # 设置填充标记
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
                
            # 加载模型
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config.model_path,
                trust_remote_code=True,
                torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32
            ).to(self.device)
            
            self.model.eval()
            logger.info("模型管道准备完成，开始对话")
            
        except Exception as e:
            logger.error(f"模型管道准备失败: {str(e)}")
            self.is_running = False
            raise

    def pipeline_answer(self, question: str) -> str:
        """生成回答"""
        try:
            if question.lower() == 'exit':
                logger.info("结束对话")
                self.release_resources()
                self.is_running = False
                return "对话已结束"

            # 网络搜索增强
            if self.need_web_search(question) or self.config.online_search:
                question = self._enhance_with_web_search(question)

            # 更新消息历史
            self.config.message_dict.append({
                "role": "user",
                "content": f"{question}\n思考后给出详细回答："
            })

            # 构造对话
            conversation = self._build_conversation()
            
            # 生成响应
            response = self.generate_response(conversation)
            
            # 更新消息历史
            self.config.message_dict.append({
                "role": "assistant",
                "content": response
            })
            
            logger.debug(f"生成回答成功，长度: {len(response)}")
            return response
            
        except RuntimeError as e:
            if "CUDA out of memory" in str(e):
                logger.error("CUDA内存不足")
                self.handle_memory_error()
                return "生成内容过长，已自动优化，请重试"
            logger.error(f"生成错误: {str(e)}")
            return f"生成错误：{str(e)}"
            
        except Exception as e:
            logger.error(f"意外错误: {str(e)}")
            return f"意外错误：{str(e)}"

    def _enhance_with_web_search(self, question: str) -> str:
        """使用网络搜索增强问题"""
        try:
            search_results = WebSearcher.cached_search(question)
            search_context = "\n".join([
                f"• {item['title']}: {item['content']}"
                for item in search_results
            ])
            enhanced_question = f"{question}\n[相关网络信息]:\n{search_context}"
            logger.debug("问题已通过网络搜索增强")
            return enhanced_question
        except Exception as e:
            logger.error(f"网络搜索增强失败: {str(e)}")
            return question

    def _build_conversation(self) -> str:
        """构建对话历史"""
        try:
            conversation = ""
            for msg in self.config.message_dict:
                if msg["role"] == "user":
                    conversation += f"User: {msg['content']}\n"
                else:
                    conversation += f"Assistant: {msg['content']}\n"
            conversation += "Assistant: "
            return conversation
        except Exception as e:
            logger.error(f"构建对话历史失败: {str(e)}")
            raise

    @monitor_performance
    def generate_response(self, prompt: str) -> str:
        """生成响应"""
        try:
            # 获取生成配置
            generation_config = self._get_generation_config()
            
            # 构建增强提示
            enhanced_prompt = self._build_enhanced_prompt(prompt)
            
            # 编码和截断
            tokens = self._encode_and_truncate(enhanced_prompt)
            
            # 生成响应
            with torch.inference_mode():
                inputs = self.tokenizer(
                    tokens,
                    return_tensors="pt",
                    max_length=self.config.input_max_length,
                    truncation=True
                ).to(self.device)
                
                # 动态调整长文本策略
                if inputs.input_ids.shape[1] > 512:
                    generation_config = self._adjust_long_text_config(generation_config)
                
                outputs = self.model.generate(**inputs, **generation_config)
                response = self.tokenizer.decode(
                    outputs[0],
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=True
                )
            
            return self.postprocess_response(response, original_prompt=prompt)
            
        except Exception as e:
            logger.error(f"生成响应失败: {str(e)}")
            raise

    def _build_enhanced_prompt(self, prompt: str) -> str:
        """构建增强提示"""
        if self.config.is_deepseek:
            return (
                "【深度思考模式】你是一个严谨的AI助手，请按照以下步骤分析：\n"
                "1. 问题本质分析\n2. 多角度验证\n3. 逻辑推理\n4. 最终结论\n"
                f"对话历史：{prompt}\n回答："
            )
        else:
            return (
                "【快速响应模式】请直接给出简明回答：\n"
                f"{prompt}\n回答："
            )

    def _encode_and_truncate(self, prompt: str) -> str:
        """编码和截断提示"""
        try:
            tokens = self.tokenizer.encode(prompt, truncation=False)
            if len(tokens) > self.config.input_max_length - 100:
                truncated = self.tokenizer.decode(
                    tokens[:self._get_truncate_length()],
                    skip_special_tokens=True
                )
                return f"[截断提示]...{truncated}"
            return prompt
        except Exception as e:
            logger.error(f"编码和截断失败: {str(e)}")
            raise

    def _get_generation_config(self) -> Dict[str, Any]:
        """获取生成配置"""
        try:
            base_config = {
                "max_new_tokens": self.config.max_new_tokens,
                "temperature": self.config.temperature,
                "top_k": self.config.top_k,
                "top_p": 0.9,
                "repetition_penalty": self.config.repetition_penalty,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "do_sample": self.config.do_sample,
                "early_stopping": True
            }

            if self.config.is_deepseek:
                return {
                    **base_config,
                    "num_beams": 5,
                    "temperature": max(0.5, self.config.temperature),
                    "no_repeat_ngram_size": 3,
                    "length_penalty": 1.2,
                    "max_new_tokens": min(self.config.max_new_tokens, 800)
                }
            else:
                return {
                    **base_config,
                    "num_beams": 1 if self.config.do_sample else 3,
                    "temperature": min(0.9, self.config.temperature + 0.2),
                    "top_k": max(30, self.config.top_k),
                    "max_new_tokens": min(self.config.max_new_tokens, 400),
                    "early_stopping": False
                }
        except Exception as e:
            logger.error(f"获取生成配置失败: {str(e)}")
            raise

    def _adjust_long_text_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """调整长文本配置"""
        try:
            config["num_beams"] = max(1, config["num_beams"] - 1)
            config["temperature"] = max(0.4, config["temperature"])
            return config
        except Exception as e:
            logger.error(f"调整长文本配置失败: {str(e)}")
            raise

    def _get_truncate_length(self) -> int:
        """获取截断长度"""
        return self.config.input_max_length - 100

    def postprocess_response(self, response: str, original_prompt: str) -> str:
        """后处理响应"""
        try:
            if self.config.is_deepseek:
                return self._deep_postprocess(response, original_prompt)
            return self._fast_postprocess(response, original_prompt)
        except Exception as e:
            logger.error(f"后处理响应失败: {str(e)}")
            raise

    def _deep_postprocess(self, response: str, original_prompt: str) -> str:
        """深度思考模式后处理"""
        try:
            # 提取回答部分
            answer = self.release_response(response)
            # 格式化回答
            formatted = self.format_response(answer)
            return formatted
        except Exception as e:
            logger.error(f"深度思考模式后处理失败: {str(e)}")
            raise

    def _fast_postprocess(self, response: str, original_prompt: str) -> str:
        """快速响应模式后处理"""
        return self.release_response(response)

    def release_response(self, full_output: str) -> str:
        """提取响应"""
        try:
            # 查找最后一个用户输入之后的助手回答
            last_user = full_output.rfind("User:")
            last_assistant = full_output.rfind("Assistant:")
            
            if last_assistant > last_user:
                response = full_output[last_assistant + len("Assistant:"):].strip()
            else:
                response = full_output
                
            return response
            
        except Exception as e:
            logger.error(f"提取响应失败: {str(e)}")
            return full_output

    def format_response(self, text: str) -> str:
        """格式化响应"""
        try:
            # 合并多余空行
            formatted = re.sub(r"(\n{3,})", "\n\n", text)
            return formatted.strip()
        except Exception as e:
            logger.error(f"格式化响应失败: {str(e)}")
            return text

    def release_resources(self) -> None:
        """释放资源"""
        try:
            if self.model is not None:
                del self.model
            if self.tokenizer is not None:
                del self.tokenizer
            torch.cuda.empty_cache()
            self.is_running = False
            logger.info("资源已释放")
        except Exception as e:
            logger.error(f"释放资源失败: {str(e)}")
            raise

    def need_web_search(self, question: str) -> bool:
        """判断是否需要网络搜索"""
        try:
            keywords = ["搜索", "查找", "最新", "新闻", "资讯"]
            return any(keyword in question for keyword in keywords)
        except Exception as e:
            logger.error(f"判断是否需要网络搜索失败: {str(e)}")
            return False

    def handle_memory_error(self) -> None:
        """处理内存错误"""
        try:
            self.release_resources()
            self.config.max_new_tokens = int(self.config.max_new_tokens * 0.8)
            self.config.input_max_length = int(self.config.input_max_length * 0.8)
            logger.info("已降低生成参数以处理内存错误")
        except Exception as e:
            logger.error(f"处理内存错误失败: {str(e)}")
            raise
