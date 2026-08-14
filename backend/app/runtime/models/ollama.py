from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from .base import ModelProvider, ModelResult, ToolCall


class OllamaProvider(ModelProvider):
    """Ollama-backed provider with tool-calling support (spec 14)."""

    name = "ollama"

    def __init__(self, model_name: str, base_url: Optional[str] = None):
        self.model_name = model_name
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def capabilities(self) -> set:
        return {"CHAT", "STREAM", "TOOL_CALLING"}

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> ModelResult:
        payload: Dict[str, Any] = {"model": self.model_name, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(timeout=timeout or 120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        msg = data.get("message") or {}
        content = msg.get("content") or ""
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tool_calls.append(ToolCall(
                id=tc.get("id") or "call_" + uuid.uuid4().hex[:8],
                name=fn.get("name", ""),
                arguments=fn.get("arguments") or {},
            ))
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": (data.get("prompt_eval_count", 0) or 0) + (data.get("eval_count", 0) or 0),
        }
        return ModelResult(content=content, tool_calls=tool_calls, model=self.model_name, usage=usage, raw=data)