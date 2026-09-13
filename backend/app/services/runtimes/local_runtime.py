"""Local inference runtime: transformers + GGUF (llama-cpp), ported from legacy model_generate."""

import asyncio
import threading
from collections.abc import AsyncIterator

from services.runtime import RuntimeEngine


class LocalRuntime(RuntimeEngine):
    """Local model inference via transformers / llama-cpp-python.

    Heavy imports (torch, transformers, llama_cpp) happen lazily on first load
    so this module can be imported without the AI stack installed.
    """

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path
        self._model = None
        self._tokenizer = None
        self._is_gguf = False
        # The inference lease already serialises the API paths; this lock keeps
        # a load/stop from mutating the model while a worker thread generates.
        self._lock = threading.Lock()

    @staticmethod
    def _is_gguf_model(path: str) -> bool:
        import os
        if os.path.isfile(path) and path.lower().endswith(".gguf"):
            return True
        if os.path.isdir(path):
            return any(f.lower().endswith(".gguf") for f in os.listdir(path))
        return False

    async def load(self, model_name: str, **kwargs) -> dict:
        """Load a local model (directory or .gguf file).

        Reading a multi-gigabyte checkpoint and moving it onto the device takes
        minutes. It runs in a worker thread so health checks, task streams and
        cancellation keep working while the model loads.
        """
        await asyncio.to_thread(self._locked, self._load_sync, model_name, **kwargs)
        return {"status": "loaded", "model": model_name}

    def _locked(self, func, *args, **kwargs):
        """Run a model-mutating step in a worker thread under the instance lock."""
        with self._lock:
            return func(*args, **kwargs)

    def _load_sync(self, model_name: str, **kwargs) -> None:
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
            # Only forward the optional knobs when the caller asked for them:
            # llama.cpp applies its own defaults otherwise, and the registry
            # runtime manager is the layer that decides the shipped defaults.
            llama_kwargs: dict = {
                "model_path": gguf_path,
                "n_ctx": kwargs.get("input_max_length", 4096),
            }
            if kwargs.get("n_gpu_layers") is not None:
                llama_kwargs["n_gpu_layers"] = int(kwargs["n_gpu_layers"])
            if kwargs.get("n_threads"):
                llama_kwargs["n_threads"] = int(kwargs["n_threads"])
            self._model = Llama(**llama_kwargs)
            self._tokenizer = None
        else:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
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

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        """Run a chat turn locally, off the event loop.

        Token generation is CPU/GPU bound and can run for minutes; performing it
        inline used to freeze every other request in the process.
        """
        if self._model is None:
            await self.load(model_name)
        return await asyncio.to_thread(
            self._locked, self._chat_sync, model_name, messages, **kwargs
        )

    def _chat_sync(self, model_name: str, messages: list, **kwargs) -> dict:
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

    async def stop(self, model_name: str) -> dict:
        await asyncio.to_thread(self._locked, self._stop_sync)
        return {"status": "stopped", "model": model_name}

    async def stream_chat(self, model_name: str, messages: list, **kwargs) -> AsyncIterator[str]:
        """Yield generated text incrementally, off the event loop.

        GGUF models are streamed token by token through a worker thread so the
        asyncio loop keeps serving heartbeats and cancellation while a long
        generation runs. Transformers checkpoints have no incremental decode
        path here, so their full answer is yielded as a single chunk.
        """
        if self._model is None:
            await self.load(model_name)
        if not self._is_gguf:
            result = await asyncio.to_thread(
                self._locked, self._chat_sync, model_name, messages, **kwargs
            )
            content = str(result.get("content", ""))
            if content:
                yield content
            return
        async for chunk in self._stream_gguf(messages, **kwargs):
            yield chunk

    async def _stream_gguf(self, messages: list, **kwargs) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        prompt = self._build_prompt(messages)
        max_tokens = int(kwargs.get("max_new_tokens", 2048))
        temperature = float(kwargs.get("temperature", 0.7))
        top_p = float(kwargs.get("top_p", 0.95))

        def _worker() -> None:
            try:
                with self._lock:
                    for chunk in self._model(
                        prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        stop=["User:"],
                        stream=True,
                    ):
                        text = ((chunk or {}).get("choices") or [{}])[0].get("text", "")
                        if text:
                            loop.call_soon_threadsafe(queue.put_nowait, ("chunk", text))
            except Exception as exc:  # surfaced to the caller, not swallowed
                loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "end":
                    return
                if kind == "error":
                    raise payload
                yield payload
        finally:
            # The worker is a daemon thread; joining briefly avoids leaking a
            # generation thread if the consumer stopped early.
            await asyncio.to_thread(thread.join, 0.5)

    def _stop_sync(self) -> None:
        try:
            if self._model is not None:
                if not self._is_gguf:
                    self._model.to("cpu")
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
                self._tokenizer = None
        except Exception:
            pass

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
