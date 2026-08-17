"""Local inference runtime: transformers + GGUF (llama-cpp), ported from legacy model_generate."""
from typing import Dict, Optional

from services.runtime import RuntimeEngine


class LocalRuntime(RuntimeEngine):
    """Local model inference via transformers / llama-cpp-python.

    Heavy imports (torch, transformers, llama_cpp) happen lazily on first load
    so this module can be imported without the AI stack installed.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._model = None
        self._tokenizer = None
        self._is_gguf = False

    @staticmethod
    def _is_gguf_model(path: str) -> bool:
        import os
        if os.path.isfile(path) and path.lower().endswith(".gguf"):
            return True
        if os.path.isdir(path):
            return any(f.lower().endswith(".gguf") for f in os.listdir(path))
        return False

    async def load(self, model_name: str, **kwargs) -> Dict:
        """Load a local model (directory or .gguf file)."""
        path = self.model_path or model_name
        self._is_gguf = self._is_gguf_model(path)
        if self._is_gguf:
            from llama_cpp import Llama
            gguf_path = path if path.lower().endswith(".gguf") else None
            if gguf_path is None:
                import os
                gguf_path = os.path.join(
                    path,
                    [f for f in os.listdir(path) if f.lower().endswith(".gguf")][0],
                )
            self._model = Llama(model_path=gguf_path, n_ctx=kwargs.get("input_max_length", 4096))
            self._tokenizer = None
        else:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            # Model repositories and local model directories are untrusted input.
            # Keep custom repository code disabled; supported architectures must
            # use Transformers' built-in implementations.
            self._tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=False)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = AutoModelForCausalLM.from_pretrained(
                path, trust_remote_code=False,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            ).to(device)
            self._model.eval()
        return {"status": "loaded", "model": model_name}

    async def chat(self, model_name: str, messages: list, **kwargs) -> Dict:
        """Run a chat turn locally."""
        if self._model is None:
            await self.load(model_name)
        prompt = self._build_prompt(messages)
        max_tokens = int(kwargs.get("max_new_tokens", 2048))
        temperature = float(kwargs.get("temperature", 0.7))
        if self._is_gguf:
            output = self._model(
                prompt, max_tokens=max_tokens, temperature=temperature, stop=["User:"]
            )
            content = output["choices"][0]["text"].strip()
        else:
            import torch
            inputs = self._tokenizer(
                prompt, return_tensors="pt", max_length=4096, truncation=True
            ).to(self._model.device)
            with torch.inference_mode():
                outputs = self._model.generate(
                    **inputs, max_new_tokens=max_tokens, temperature=temperature,
                    do_sample=True, top_k=int(kwargs.get("top_k", 50)),
                )
            content = self._tokenizer.decode(
                outputs[0], skip_special_tokens=True, clean_up_tokenization_spaces=True
            )
            content = self._release_response(content)
        return {"model": model_name, "content": content, "raw": None}

    async def stop(self, model_name: str) -> Dict:
        try:
            if self._model is not None:
                if not self._is_gguf:
                    import torch
                    self._model.to("cpu")
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
                self._tokenizer = None
        except Exception:
            pass
        return {"status": "stopped", "model": model_name}

    @staticmethod
    def _build_prompt(messages: list) -> str:
        conversation = ""
        for msg in messages:
            role = "User" if msg.get("role") == "user" else "Assistant"
            conversation += f"{role}: {msg.get('content', '')}\n"
        return conversation + "Assistant: "

    @staticmethod
    def _release_response(full_output: str) -> str:
        idx = full_output.rfind("User:")
        if idx == -1:
            return full_output.strip()
        after = full_output[idx + len("User:"):]
        a_idx = after.find("Assistant:")
        return after[a_idx + len("Assistant:"):].strip() if a_idx != -1 else after.strip()