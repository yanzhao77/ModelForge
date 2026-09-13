"""Extract tool calls from local-model text output.

llama.cpp / Transformers checkpoints do not expose a native tool-calling
channel the way hosted APIs do, so a local Agent has to be told to answer with
a small JSON envelope. This module is the single parser for that envelope: it
is used by the runtime-backed ModelProvider and by the Workflow engine's LLM
node so both agree on what a tool call looks like.

Recognised shapes (any of them, wrapped in ```json fences or bare)::

    {"tool_calls": [{"name": "filesystem.read", "arguments": {"filepath": "a"}}]}
    {"tool_call": {"name": "filesystem.read", "arguments": {...}}}
    {"name": "filesystem.read", "arguments": {...}}
    {"tool": "filesystem.read", "parameters": {...}}
    {"function": {"name": "filesystem.read", "arguments": "{\"filepath\": \"a\"}"}}
"""

from __future__ import annotations

import json
import uuid
from typing import Any


def _balanced_json_objects(text: str) -> list[tuple[dict, int, int]]:
    """Yield ``(object, start, end)`` for every balanced JSON object in text."""
    found: list[tuple[dict, int, int]] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = text[start:index + 1]
                    try:
                        payload = json.loads(candidate)
                    except (TypeError, ValueError):
                        payload = None
                    if isinstance(payload, dict):
                        found.append((payload, start, index + 1))
                    start = -1
    return found


def _normalize_arguments(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {"input": value}
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    return {}


def _normalize_call(payload: dict) -> dict | None:
    """Turn one call-shaped object into ``{id, name, arguments}``."""
    function = payload.get("function")
    if isinstance(function, dict):
        payload = {**payload, **function}
    name = payload.get("name") or payload.get("tool") or payload.get("tool_name")
    if not isinstance(name, str) or not name.strip():
        return None
    arguments = (
        payload.get("arguments")
        if payload.get("arguments") is not None
        else payload.get("parameters")
        if payload.get("parameters") is not None
        else payload.get("input")
    )
    return {
        "id": str(payload.get("id") or "call_" + uuid.uuid4().hex[:8]),
        "name": name.strip(),
        "arguments": _normalize_arguments(arguments),
    }


def parse_tool_calls(text: str) -> tuple[str, list[dict]]:
    """Return ``(content_without_calls, tool_calls)`` for one model message."""
    if not text:
        return "", []
    calls: list[dict] = []
    spans: list[tuple[int, int]] = []
    for payload, start, end in _balanced_json_objects(text):
        candidates: list[dict] = []
        if isinstance(payload.get("tool_calls"), list):
            candidates = [item for item in payload["tool_calls"] if isinstance(item, dict)]
        elif isinstance(payload.get("tool_call"), dict):
            candidates = [payload["tool_call"]]
        else:
            candidates = [payload]
        recognized = [call for call in (_normalize_call(item) for item in candidates) if call]
        if recognized:
            calls.extend(recognized)
            spans.append((start, end))
    if not calls:
        return text.strip(), []
    cleaned = text
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    # Drop empty ```json fences left behind by a removed envelope.
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned, calls


def tool_protocol_instructions(tools: list[dict] | None) -> str:
    """System-message fragment that teaches a local model the tool envelope."""
    if not tools:
        return ""
    lines = [
        "You may call tools. To call one, reply with ONLY a JSON object:",
        '{"tool_calls": [{"name": "<tool>", "arguments": {<args>}}]}',
        "Call at most one tool per reply. When you are ready to answer the user,",
        "reply with plain text and no JSON.",
        "Available tools:",
    ]
    for schema in tools:
        function = schema.get("function") if isinstance(schema, dict) else None
        if isinstance(function, dict):
            lines.append(f"- {function.get('name')}: {function.get('description', '')}")
    return "\n".join(lines)
