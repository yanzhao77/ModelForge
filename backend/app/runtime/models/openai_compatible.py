"""OpenAI-compatible ModelProvider used only for server-resolved Agent targets."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from core.config import settings
from core.network_security import provider_validation_mode, validate_provider_target

from .base import ModelProvider, ModelResult, ToolCall


class OpenAICompatibleProvider(ModelProvider):
    """Responses-first provider that keeps decrypted credentials inside the backend."""

    name = "openai-compatible"

    def __init__(self, *, api_key: str, base_url: str, model: str, protocol: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.protocol = protocol

    def capabilities(self) -> set:
        return {"CHAT", "TOOL_CALLING"}

    def _validate_target(self) -> None:
        validate_provider_target(self.base_url, mode=provider_validation_mode(settings.environment))

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> ModelResult:
        self._validate_target()
        if self.protocol == "responses":
            endpoint = f"{self.base_url}/responses"
            payload: dict[str, Any] = {"model": self.model, "input": messages, "stream": False}
        else:
            endpoint = f"{self.base_url}/chat/completions"
            payload = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout or 120.0, follow_redirects=False) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if self.protocol == "responses":
            return self._responses_result(data)
        return self._chat_result(data)

    def _responses_result(self, data: dict[str, Any]) -> ModelResult:
        text: list[str] = []
        calls: list[ToolCall] = []
        for item in data.get("output") or []:
            if item.get("type") == "function_call":
                calls.append(ToolCall(
                    id=item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                    name=item.get("name") or "",
                    arguments=self._arguments(item.get("arguments")),
                ))
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    text.append(content["text"])
        usage = data.get("usage") or {}
        return ModelResult(content="".join(text), tool_calls=calls, model=self.model, usage=self._usage(usage), raw=None)

    def _chat_result(self, data: dict[str, Any]) -> ModelResult:
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        calls = [
            ToolCall(
                id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=(call.get("function") or {}).get("name") or "",
                arguments=self._arguments((call.get("function") or {}).get("arguments")),
            )
            for call in message.get("tool_calls") or []
        ]
        return ModelResult(
            content=message.get("content") or "",
            tool_calls=calls,
            model=self.model,
            usage=self._usage(data.get("usage") or {}),
            raw=None,
        )

    @staticmethod
    def _arguments(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _usage(value: dict[str, Any]) -> dict[str, int]:
        prompt = int(value.get("input_tokens") or value.get("prompt_tokens") or 0)
        completion = int(value.get("output_tokens") or value.get("completion_tokens") or 0)
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}
