"""Remote OpenAI-compatible runtime with Responses-first streaming support."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from services.runtime import RuntimeEngine


class OpenAIRuntime(RuntimeEngine):
    """Call one user-selected OpenAI-compatible provider without persisting its key."""

    def __init__(self, api_key: str, base_url: str, model: str, protocol: str = "responses"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.protocol = protocol

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _model(self, model_name: str) -> str:
        return (model_name or self.default_model).strip()

    def _endpoint(self) -> str:
        return f"{self.base_url}/responses" if self.protocol == "responses" else f"{self.base_url}/chat/completions"

    @staticmethod
    def _responses_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str):
            return direct
        text: list[str] = []
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    text.append(content["text"])
        return "".join(text)

    async def load(self, model_name: str, **kwargs) -> dict:
        return {"status": "ready", "model": self._model(model_name), "remote": True}

    async def stop(self, model_name: str) -> dict:
        # Remote API capacity is provider-managed; this must never imply a provider-side stop.
        return {"status": "detached", "model": self._model(model_name), "remote": True}

    async def chat(self, model_name: str, messages: list[dict], **kwargs) -> dict:
        model = self._model(model_name)
        if not model:
            raise ValueError("Remote provider has no selected model.")
        if self.protocol == "responses":
            payload: dict[str, Any] = {"model": model, "input": messages, "stream": False}
            if kwargs.get("temperature") is not None:
                payload["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["max_output_tokens"] = kwargs["max_tokens"]
        else:
            payload = {"model": model, "messages": messages, "stream": False}
            for key in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty"):
                if kwargs.get(key) is not None:
                    payload[key] = kwargs[key]
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=False) as client:
            response = await client.post(self._endpoint(), headers=self._headers, json=payload)
        response.raise_for_status()
        data = response.json()
        content = self._responses_text(data) if self.protocol == "responses" else ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return {"model": model, "content": content or "", "raw": None, "remote": True, "protocol": self.protocol}

    async def stream_chat(self, model_name: str, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        model = self._model(model_name)
        if not model:
            raise ValueError("Remote provider has no selected model.")
        payload: dict[str, Any]
        if self.protocol == "responses":
            payload = {"model": model, "input": messages, "stream": True}
            if kwargs.get("temperature") is not None:
                payload["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["max_output_tokens"] = kwargs["max_tokens"]
        else:
            payload = {"model": model, "messages": messages, "stream": True}
            for key in ("temperature", "top_p", "max_tokens"):
                if kwargs.get(key) is not None:
                    payload[key] = kwargs[key]
        async with httpx.AsyncClient(timeout=None, follow_redirects=False) as client:
            async with client.stream("POST", self._endpoint(), headers=self._headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            return
                        continue
                    try:
                        event = httpx.Response(200, content=data).json()
                    except ValueError:
                        continue
                    if self.protocol == "responses":
                        event_type = event.get("type")
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta", "")
                            if delta:
                                yield delta
                        elif event_type in {"error", "response.failed"}:
                            detail = event.get("error") or event.get("message") or "Remote provider stream failed."
                            raise RuntimeError(str(detail))
                        elif event_type == "response.completed":
                            return
                    else:
                        choices = event.get("choices") or []
                        delta = ((choices[0].get("delta") or {}).get("content", "") if choices else "")
                        if delta:
                            yield delta
