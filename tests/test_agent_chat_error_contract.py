"""Agent chat must not leak internals and must answer with stable codes.

The engine used to return ``"Agent graph build failed: {exception}"`` as a
successful 200 response, which echoed internal detail to the client, and the
route answered a missing agent with a bare string detail instead of the shared
problem envelope.
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import api.agent as agent_api  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from services.agent_engine import AgentEngine  # noqa: E402


def test_engine_graph_failure_does_not_echo_the_exception():
    engine = AgentEngine()
    engine.create_agent("probe-agent", "local-gguf", [])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            AgentEngine,
            "_build_graph",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret-internal-path")),
        )
        result = engine.chat("probe-agent", "hello", llm=object())

    assert result["error_code"] == "AGENT_GRAPH_FAILED"
    assert "secret-internal-path" not in str(result)
    assert "response" not in result


def test_engine_without_a_provider_marks_the_answer_as_provider_required():
    engine = AgentEngine()
    engine.create_agent("probe-agent", "local-gguf", [])

    result = engine.chat("probe-agent", "hello")

    assert result["provider_required"] is True
    assert "No LLM provider" in result["response"]


class _Runtime:
    def __init__(self, agent):
        self._agent = agent
        self.policy_engine = None
        self.tool_registry = None

    def get_agent(self, name, user_id=None):
        return self._agent


_EXISTING_AGENT = object()


def _chat(monkeypatch, engine_result, agent=_EXISTING_AGENT):
    runtime_agent = (
        SimpleNamespace(name="probe-agent") if agent is _EXISTING_AGENT else agent
    )
    monkeypatch.setattr(agent_api, "_get_runtime", lambda: _Runtime(runtime_agent))
    monkeypatch.setattr(
        agent_api,
        "_get_engine",
        lambda: SimpleNamespace(chat=lambda *args, **kwargs: engine_result),
    )
    user = SimpleNamespace(id=1, username="qa-user")
    return asyncio.run(agent_api.agent_chat("probe-agent", {"message": "hello"}, user=user))


def test_route_maps_graph_failure_to_a_problem_response(monkeypatch):
    with pytest.raises(HTTPException) as raised:
        _chat(monkeypatch, {"error_code": "AGENT_GRAPH_FAILED", "tool_calls": []})

    assert raised.value.status_code == 502
    assert raised.value.detail["code"] == "AGENT_GRAPH_FAILED"
    assert raised.value.detail["correlation_id"]


def test_route_maps_a_missing_agent_to_the_shared_envelope(monkeypatch):
    with pytest.raises(HTTPException) as raised:
        _chat(monkeypatch, {"error": "Agent 'probe-agent' not found"})

    assert raised.value.status_code == 404
    assert raised.value.detail == {
        "code": "AGENT_NOT_FOUND",
        "message": "Agent not found",
        "correlation_id": raised.value.detail["correlation_id"],
    }


def test_route_answers_with_an_unknown_agent_problem(monkeypatch):
    with pytest.raises(HTTPException) as raised:
        _chat(monkeypatch, {}, agent=None)

    assert raised.value.status_code == 404
    assert raised.value.detail["code"] == "AGENT_NOT_FOUND"
