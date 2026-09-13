"""ModelForge Python SDK (V1.6).

The SDK is a thin, typed wrapper over the REST + OpenAI-compatible API: it never
re-implements product behaviour, so an application built on it behaves exactly
like the desktop client.

```python
from modelforge import ModelForge

client = ModelForge("http://127.0.0.1:8000")
client.login("alice", "secret123")

for model in client.models.list(capability="CHAT"):
    print(model["name"], model["status"])

client.models.load(model_id=3)
reply = client.chat.completions.create(
    model="qwen2.5-0.5b",
    messages=[{"role": "user", "content": "你好"}],
)

client.embeddings.create(["hello", "world"])
client.agents.run("writer", "写一段介绍")
client.knowledge.search("统一模型生命周期", top_k=3)
client.workflows.run(workflow_id="...", run_input={"question": "你好"})
```
"""

from __future__ import annotations

from typing import Any

import httpx


class ModelForgeError(RuntimeError):
    """Raised for a non-2xx response, carrying the stable error code."""

    def __init__(self, status: int, code: str, message: str, correlation_id: str | None = None):
        super().__init__(f"[{status} {code}] {message}")
        self.status = status
        self.code = code
        self.message = message
        self.correlation_id = correlation_id


class _Resource:
    def __init__(self, client: "ModelForge"):
        self._client = client


class ModelsResource(_Resource):
    def list(self, *, capability: str | None = None, source: str | None = None) -> list[dict]:
        params = {key: value for key, value in (("capability", capability), ("source", source)) if value}
        return self._client.request("GET", "/api/v1/models", params=params or None)

    def get(self, model_id: int) -> dict:
        return self._client.request("GET", f"/api/v1/models/{model_id}")

    def load(self, model_id: int, **options: Any) -> dict:
        return self._client.request("POST", f"/api/v1/models/{model_id}/load", json=options)

    def unload(self, model_id: int) -> dict:
        return self._client.request("POST", f"/api/v1/models/{model_id}/unload", json={})

    def runtime(self, model_id: int) -> dict:
        return self._client.request("GET", f"/api/v1/models/{model_id}/runtime")

    def runtimes(self) -> dict:
        return self._client.request("GET", "/api/v1/runtimes")


class ChatCompletionsResource(_Resource):
    def create(
        self,
        *,
        model: str,
        messages: list[dict],
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return self._client.request("POST", "/v1/chat/completions", json=payload)


class ChatResource(_Resource):
    def __init__(self, client: "ModelForge"):
        super().__init__(client)
        self.completions = ChatCompletionsResource(client)


class EmbeddingsResource(_Resource):
    def create(self, model_input: str | list[str], *, model_id: int | None = None) -> dict:
        payload: dict[str, Any] = {"input": model_input}
        if model_id is not None:
            payload["model_id"] = model_id
        return self._client.request("POST", "/v1/embeddings", json=payload)


class AgentsResource(_Resource):
    def list(self) -> list[dict]:
        return self._client.request("GET", "/v1/agents").get("data", [])

    def create(self, payload: dict) -> dict:
        return self._client.request("POST", "/api/v1/agents", json=payload)

    def run(self, agent_id: str, text: str, *, session_id: int | None = None, wait: bool = False, timeout: float = 60.0) -> dict:
        run = self._client.request(
            "POST",
            f"/v1/agents/{agent_id}/runs",
            json={"input": text, "session_id": session_id},
        )
        if not wait:
            return run
        return self.wait(run["run_id"], timeout=timeout)

    def get_run(self, run_id: str) -> dict:
        return self._client.request("GET", f"/v1/agents/runs/{run_id}")

    def trace(self, run_id: str) -> dict:
        return self._client.request("GET", f"/v1/agents/runs/{run_id}/trace")

    def wait(self, run_id: str, *, timeout: float = 60.0, interval: float = 0.2) -> dict:
        deadline = _now() + timeout
        while True:
            run = self.get_run(run_id)
            if run.get("status") in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}:
                return run
            if _now() > deadline:
                raise TimeoutError(f"agent run {run_id} did not finish within {timeout}s")
            _sleep(interval)


class KnowledgeResource(_Resource):
    def search(self, query: str, *, top_k: int = 5, knowledge_id: str | None = None, retrieval_mode: str | None = None) -> dict:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if knowledge_id:
            payload["knowledge_id"] = knowledge_id
        if retrieval_mode:
            payload["retrieval_mode"] = retrieval_mode
        return self._client.request("POST", "/v1/knowledge/search", json=payload)

    def bases(self) -> list[dict]:
        return self._client.request("GET", "/api/v1/knowledge/bases").get("knowledge_bases", [])

    def create_base(self, name: str) -> dict:
        return self._client.request("POST", "/api/v1/knowledge/bases", json={"name": name})


class WorkflowsResource(_Resource):
    def list(self) -> list[dict]:
        return self._client.request("GET", "/api/v1/workflows").get("workflows", [])

    def run(self, workflow_id: str, run_input: dict | None = None, *, wait: bool = False, timeout: float = 60.0) -> dict:
        run = self._client.request(
            "POST", f"/v1/workflows/{workflow_id}/runs", json={"input": run_input or {}}
        )
        if not wait:
            return run
        return self.wait(run["run_id"], timeout=timeout)

    def get_run(self, run_id: str) -> dict:
        return self._client.request("GET", f"/v1/workflows/runs/{run_id}")

    def trace(self, run_id: str) -> dict:
        return self._client.request("GET", f"/v1/workflows/runs/{run_id}/trace")

    def approve(self, run_id: str) -> dict:
        return self._client.request("POST", f"/api/v1/workflows/runs/{run_id}/approve", json={})

    def wait(self, run_id: str, *, timeout: float = 60.0, interval: float = 0.2) -> dict:
        deadline = _now() + timeout
        while True:
            run = self.get_run(run_id)
            if run.get("status") in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}:
                return run
            if _now() > deadline:
                raise TimeoutError(f"workflow run {run_id} did not finish within {timeout}s")
            _sleep(interval)


class PlatformResource(_Resource):
    def capabilities(self) -> dict:
        return self._client.request("GET", "/v1/platform/capabilities")


def _now() -> float:
    import time

    return time.monotonic()


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


class ModelForge:
    """Synchronous ModelForge client."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport
        self.models = ModelsResource(self)
        self.chat = ChatResource(self)
        self.embeddings = EmbeddingsResource(self)
        self.agents = AgentsResource(self)
        self.knowledge = KnowledgeResource(self)
        self.workflows = WorkflowsResource(self)
        self.platform = PlatformResource(self)

    # -- auth ---------------------------------------------------------------

    def login(self, username: str, password: str) -> dict:
        payload = self.request(
            "POST", "/api/v1/auth/login", json={"username": username, "password": password}
        )
        self.api_key = payload.get("token") or self.api_key
        return payload

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    # -- transport ----------------------------------------------------------

    def request(self, method: str, path: str, **kwargs: Any):
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout, transport=self._transport, base_url=self.base_url) as client:
            response = client.request(method, path, headers=self._headers, **kwargs)
        if response.status_code >= 400:
            raise _error_from(response, url)
        if not response.content:
            return {}
        return response.json()


def _error_from(response: httpx.Response, url: str) -> ModelForgeError:
    code, message, correlation = "HTTP_ERROR", response.text[:300], None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        error = payload.get("error")
        if isinstance(detail, dict):
            code = str(detail.get("code") or code)
            message = str(detail.get("message") or message)
            correlation = detail.get("correlation_id")
        elif isinstance(error, dict):
            code = str(error.get("code") or code)
            message = str(error.get("message") or message)
            correlation = payload.get("correlation_id")
    return ModelForgeError(response.status_code, code, message, correlation)
