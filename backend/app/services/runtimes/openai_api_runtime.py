"""OpenAI-compatible API runtime, ported from legacy interface_generate."""

from services.runtime import RuntimeEngine


class OpenAIRuntime(RuntimeEngine):
    """Chat through any OpenAI-compatible endpoint (OpenAI, 讯飞星火, DeepSeek, ...)."""

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", model: str = ""):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key or "sk-placeholder", base_url=self.base_url)
        return self._client

    async def load(self, model_name: str, **kwargs) -> dict:
        return {"status": "loaded", "model": model_name}

    async def chat(self, model_name: str, messages: list, **kwargs) -> dict:
        """Call the remote chat completions endpoint."""
        client = self._get_client()
        params = {
            "model": model_name or self.default_model,
            "messages": messages,
        }
        for key in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty"):
            if kwargs.get(key) is not None:
                params[key] = kwargs[key]
        try:
            completion = await asyncio_to_thread(client.chat.completions.create, **params)
            content = completion.choices[0].message.content or ""
            return {"model": params["model"], "content": content, "raw": None}
        except Exception as e:
            return {"model": params["model"], "content": f"[接口错误] {e}", "raw": None}

    async def stop(self, model_name: str) -> dict:
        return {"status": "stopped", "model": model_name}

async def asyncio_to_thread(func, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(func, *args, **kwargs)