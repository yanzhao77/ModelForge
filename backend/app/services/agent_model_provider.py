"""ModelProvider backed by the unified model runtime (V1.1).

An Agent must never build a llama.cpp/Transformers engine itself: it holds a
``model_id`` and hands it to the ModelRuntimeManager, which owns loading,
eviction and the adapter choice. This provider is the single bridge between the
Agent runtime's ``ModelProvider`` port and that manager.

Tool calling: local checkpoints have no native tool channel, so the provider
injects the JSON envelope described in :mod:`services.tool_call_parser` and
parses the reply back into ``ToolCall`` objects.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.models.base import ModelProvider, ModelResult, ToolCall
from services.tool_call_parser import parse_tool_calls, tool_protocol_instructions


class RuntimeBackedProvider(ModelProvider):
    """Agent-side provider that delegates inference to the runtime manager."""

    name = "model_runtime"

    def __init__(
        self,
        model_id: int,
        *,
        model_name: str = "",
        user_id: int | None = None,
        runtime: str | None = None,
        generation: dict[str, Any] | None = None,
    ):
        self.model_id = int(model_id)
        self.model_name = model_name or str(model_id)
        self.user_id = user_id
        self.runtime = runtime
        self.generation = dict(generation or {})

    def capabilities(self) -> set:
        return {"CHAT", "STREAM", "TOOL_CALLING"}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> ModelResult:
        payload = list(messages)
        protocol = tool_protocol_instructions(tools)
        if protocol:
            payload = [{"role": "system", "content": protocol}, *payload]
        options = dict(self.generation)
        if timeout:
            options.setdefault("timeout", timeout)
        result = await self._chat(payload, options)
        content = str((result or {}).get("content") or "")
        cleaned, raw_calls = parse_tool_calls(content) if tools else (content, [])
        tool_calls = [
            ToolCall(id=call["id"], name=call["name"], arguments=call.get("arguments") or {})
            for call in raw_calls
        ]
        usage = result.get("usage") if isinstance(result, dict) else None
        return ModelResult(
            content=cleaned if tool_calls else content,
            tool_calls=tool_calls,
            model=str((result or {}).get("model") or self.model_name),
            usage=usage or {},
            raw=result,
        )

    async def _chat(self, payload: list[dict], options: dict) -> dict:
        from services.model_runtime_manager import get_model_runtime_manager

        manager = get_model_runtime_manager()
        try:
            return await manager.chat(
                self.model_id, payload, user_id=self.user_id, runtime=self.runtime, **options
            )
        except TypeError:
            # Older manager signatures do not accept ``runtime``; degrade to the
            # registry-resolved default instead of failing the Run.
            return await manager.chat(self.model_id, payload, user_id=self.user_id, **options)

    @classmethod
    def from_agent(cls, agent: Any) -> "RuntimeBackedProvider | None":
        """Build a provider for a local (registry-backed) agent, else ``None``."""
        model_id = getattr(agent, "model_id", None)
        if model_id is None:
            target = getattr(agent, "model_target", None) or {}
            model_id = target.get("model_id")
        if model_id is None:
            return None
        runtime_config = getattr(agent, "runtime_config", None)
        runtime = None
        generation: dict[str, Any] = {}
        if isinstance(runtime_config, dict):
            runtime = runtime_config.get("runtime") or runtime_config.get("preferred_runtime")
            candidate = runtime_config.get("generation")
            if isinstance(candidate, dict):
                generation = candidate
        return cls(
            int(model_id),
            model_name=getattr(agent, "model", "") or "",
            user_id=getattr(agent, "user_id", None),
            runtime=runtime,
            generation=generation,
        )


def local_model_target(model_id: int, model_name: str, capabilities: list[str]) -> dict:
    """Registry-backed ``model_target`` payload persisted on an Agent."""
    payload = {
        "kind": "local",
        "model_id": int(model_id),
        "model_ref": str(model_id),
        "model_name": model_name,
        "provider_id": None,
        "provider_name": None,
        "protocol": None,
        "capabilities": list(capabilities or []),
    }
    return json.loads(json.dumps(payload))  # normalise nested types
