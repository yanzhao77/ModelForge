"""API Client for communicating with ModelForge backend (REST + SSE)."""
import json
from typing import Dict, Iterator, List, Optional

import httpx


class ModelForgeClient:
    """HTTP client for the ModelForge REST API with Bearer-token auth."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = None
        self.username: Optional[str] = None

    # ---- auth state ----

    def set_token(self, token: Optional[str]):
        self._token = token

    def has_token(self) -> bool:
        return bool(self._token)

    def _headers(self) -> Dict:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # ---- server info ----

    def get_info(self) -> Dict:
        return self._get("/")

    def system_status(self) -> Dict:
        return self._get("/api/v1/system/status")

    # ---- auth ----

    def register(self, username: str, password: str, email: Optional[str] = None) -> Dict:
        return self._post("/api/v1/auth/register", json={"username": username, "password": password, "email": email})

    def login(self, username: str, password: str) -> Dict:
        data = self._post("/api/v1/auth/login", json={"username": username, "password": password})
        self.set_token(data.get("token"))
        self.username = (data.get("user") or {}).get("username", username)
        return data

    def me(self) -> Dict:
        return self._get("/api/v1/auth/me")

    def change_password(self, old_password: str, new_password: str) -> Dict:
        return self._post(
            "/api/v1/auth/change-password",
            json={"old_password": old_password, "new_password": new_password},
        )

    # ---- models ----

    def list_models(self) -> List[Dict]:
        return self._get("/api/v1/models")

    def scan_models(self, path: Optional[str] = None) -> List[Dict]:
        return self._post("/api/v1/models/scan", json={"path": path or None})

    def install_model(self, name: str, provider: str, path: str, size: str = "") -> Dict:
        return self._post("/api/v1/models/install", json={"name": name, "provider": provider, "path": path, "size": size})

    def remove_model(self, model_id: int) -> Dict:
        return self._delete(f"/api/v1/models/{model_id}")

    def search_models(self, query: str = "", author: Optional[str] = None, limit: int = 20) -> List[Dict]:
        params = {"q": query, "limit": limit}
        if author:
            params["author"] = author
        return self._get("/api/v1/models/search", params=params)

    def download_model(self, repo_id: str, filename: Optional[str] = None) -> Dict:
        return self._post("/api/v1/models/download", json={"repo_id": repo_id, "filename": filename})

    def download_status(self, task_id: str) -> Dict:
        return self._get(f"/api/v1/models/download/{task_id}")

    # ---- runtime ----

    def runtime_start(self, model: str) -> Dict:
        return self._post("/api/v1/runtime/start", json={"model": model})

    def runtime_chat(self, model: str, messages: list) -> Dict:
        return self._post("/api/v1/runtime/chat", json={"model": model, "messages": messages})

    def runtime_stop(self, model: str) -> Dict:
        return self._post("/api/v1/runtime/stop", json={"model": model})

    def runtime_status(self) -> Dict:
        return self._get("/api/v1/runtime/status")

    # ---- chat (JSON + SSE) ----

    def chat(self, model: str, messages: list, session_id: Optional[int] = None) -> Dict:
        return self._post(
            "/api/v1/chat",
            json={"model": model, "messages": messages, "session_id": session_id},
        )

    def stream_chat(
        self, model: str, messages: list, session_id: Optional[int] = None
    ) -> Iterator[Dict]:
        """Yield SSE events: {type: delta|done|error, data: ...}."""
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/api/v1/chat/stream",
                json={"model": model, "messages": messages, "session_id": session_id},
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    yield event
                    if event.get("type") in ("done", "error"):
                        break

    # ---- sessions ----

    def list_sessions(self) -> List[Dict]:
        return self._get("/api/v1/sessions")

    def create_session(self, title: str = "新对话") -> Dict:
        return self._post("/api/v1/sessions", json={"title": title})

    def get_session(self, session_id: int) -> Dict:
        return self._get(f"/api/v1/sessions/{session_id}")

    def rename_session(self, session_id: int, title: str) -> Dict:
        return self._patch(f"/api/v1/sessions/{session_id}", json={"title": title})

    def delete_session(self, session_id: int) -> Dict:
        return self._delete(f"/api/v1/sessions/{session_id}")

    def list_messages(self, session_id: int, limit: Optional[int] = None) -> List[Dict]:
        params = {}
        if limit:
            params["limit"] = limit
        return self._get(f"/api/v1/sessions/{session_id}/messages", params=params)

    def clear_messages(self, session_id: int) -> Dict:
        return self._delete(f"/api/v1/sessions/{session_id}/messages")

    def auto_title(self, session_id: int) -> Dict:
        return self._post(f"/api/v1/sessions/{session_id}/title")

    # ---- memories ----

    def list_memories(self, memory_type: Optional[str] = None) -> List[Dict]:
        params = {"memory_type": memory_type} if memory_type else {}
        return self._get("/api/v1/memories", params=params)

    def create_memory(self, memory_type: str, key: str, value: str) -> Dict:
        return self._post("/api/v1/memories", json={"memory_type": memory_type, "key": key, "value": value})

    def search_memories(self, q: str) -> List[Dict]:
        return self._get("/api/v1/memories/search", params={"q": q})

    def delete_memory(self, memory_id: int) -> Dict:
        return self._delete(f"/api/v1/memories/{memory_id}")

    # ---- agents / knowledge (basic) ----

    def create_agent(self, name: str, model: str, tools: List[str]) -> Dict:
        return self._post("/api/v1/agent/create", json={"name": name, "model": model, "tools": tools})

    def list_agents(self) -> List[Dict]:
        return self._get("/api/v1/agent/list")

    def agent_chat(self, name: str, message: str) -> Dict:
        return self._post(f"/api/v1/agent/{name}/chat", json={"message": message})

    def knowledge_upload(self, filepath: str) -> Dict:
        with open(filepath, "rb") as f:
            files = {"file": (filepath.split("/")[-1], f, "application/octet-stream")}
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/knowledge/upload", files=files, headers=self._headers()
                )
                resp.raise_for_status()
                return resp.json()

    def knowledge_query(self, question: str, top_k: int = 5) -> Dict:
        return self._post("/api/v1/knowledge/query", json={"question": question, "top_k": top_k})


    # ---- agent runs (3.0) ----

    def create_agent_run(self, agent_id: str, input_text: str, session_id: Optional[int] = None, metadata: Optional[dict] = None, execute: bool = True) -> Dict:
        return self._post("/api/v1/agent/runs", json={
            "agent_id": agent_id, "input": input_text,
            "session_id": session_id, "metadata": metadata, "execute": execute,
        })

    def list_agent_runs(self, agent_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> List[Dict]:
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if status:
            params["status"] = status
        return self._get("/api/v1/agent/runs", params=params)

    def get_agent_run(self, run_id: str) -> Dict:
        return self._get(f"/api/v1/agent/runs/{run_id}")

    def cancel_agent_run(self, run_id: str) -> Dict:
        return self._post(f"/api/v1/agent/runs/{run_id}/cancel")

    def approve_agent_run(self, run_id: str) -> Dict:
        return self._post(f"/api/v1/agent/runs/{run_id}/approve")

    def reject_agent_run(self, run_id: str) -> Dict:
        return self._post(f"/api/v1/agent/runs/{run_id}/reject")

    def get_agent_run_events(self, run_id: str, after_sequence: int = 0) -> List[Dict]:
        data = self._get(f"/api/v1/agent/runs/{run_id}/events", params={"after_sequence": after_sequence})
        return data.get("events", [])

    def stream_agent_run(self, run_id: str, after_sequence: int = 0) -> Iterator[Dict]:
        """Yield SSE events: {event_type, sequence, timestamp, payload} (spec 26)."""
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "GET",
                f"{self.base_url}/api/v1/agent/runs/{run_id}/stream",
                params={"after_sequence": after_sequence},
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith(":") or line.startswith("event:"):
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    yield event

    def list_agent_tools(self) -> List[Dict]:
        data = self._get("/api/v1/agent/tools")
        return data.get("tools", [])

    def agent_metrics(self) -> Dict:
        return self._get("/api/v1/agent/metrics")

    def register_mcp_server(self, name: str, endpoint: str) -> Dict:
        return self._post("/api/v1/agent/mcp/servers", json={"name": name, "endpoint": endpoint})

    def list_mcp_servers(self) -> List[Dict]:
        data = self._get("/api/v1/agent/mcp/servers")
        return data.get("servers", [])

    def create_agent_config(self, name: str, model: str, tools: List[str], system_prompt: Optional[str] = None, policy: Optional[dict] = None, runtime_config: Optional[dict] = None) -> Dict:
        return self._post("/api/v1/agent/create", json={
            "name": name, "model": model, "tools": tools,
            "system_prompt": system_prompt, "policy": policy, "runtime_config": runtime_config,
        })

    # ---- datasets ----

    def upload_dataset(self, filepath: str, name: Optional[str] = None) -> Dict:
        with open(filepath, "rb") as f:
            files = {"file": (filepath.split("/")[-1], f, "application/octet-stream")}
            data = {"name": name} if name else None
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/datasets/upload",
                    files=files, data=data, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()

    def list_datasets(self) -> List[Dict]:
        return self._get("/api/v1/datasets")

    def get_dataset(self, dataset_id: int) -> Dict:
        return self._get(f"/api/v1/datasets/{dataset_id}")

    def validate_dataset(self, dataset_id: int) -> Dict:
        return self._post(f"/api/v1/datasets/{dataset_id}/validate")

    def delete_dataset(self, dataset_id: int) -> Dict:
        return self._delete(f"/api/v1/datasets/{dataset_id}")

    # ---- training ----

    def train_templates(self) -> Dict:
        return self._get("/api/v1/train/templates")

    def train_start(self, config: dict) -> Dict:
        return self._post("/api/v1/train/start", json=config)

    def train_status(self, task_id: str) -> Dict:
        return self._get(f"/api/v1/train/status/{task_id}")

    def train_tasks(self) -> List[Dict]:
        return self._get("/api/v1/train/tasks")

    def train_stop(self, task_id: str) -> Dict:
        return self._post(f"/api/v1/train/stop/{task_id}")

    def train_register_model(self, task_id: str) -> Dict:
        return self._post(f"/api/v1/train/{task_id}/register-model")

    def train_stream(self, task_id: str) -> Iterator[Dict]:
        """Yield training SSE events: {type: log|progress|done, data: ...}."""
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "GET",
                f"{self.base_url}/api/v1/train/stream/{task_id}",
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    yield event
                    if event.get("type") == "done":
                        break

    # ---- knowledge ----

    def knowledge_documents(self) -> List[Dict]:
        return self._get("/api/v1/knowledge/documents")

    def knowledge_delete(self, filename: str) -> Dict:
        return self._delete(f"/api/v1/knowledge/documents/{filename}")

    def knowledge_chunks(self, filename: str) -> List[Dict]:
        return self._get(f"/api/v1/knowledge/documents/{filename}/chunks")

    def knowledge_answer(self, model: str, question: str, top_k: int = 3) -> Dict:
        return self._post(
            "/api/v1/knowledge/answer",
            json={"question": question, "top_k": top_k, "model": model},
        )

    # ---- global task center / onboarding ----
    def list_tasks(self) -> List[Dict]:
        return self._get("/api/v1/tasks").get("tasks", [])

    def task_summary(self) -> Dict:
        return self._get("/api/v1/tasks/summary")

    def get_task(self, task_id: str) -> Dict:
        return self._get(f"/api/v1/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> Dict:
        return self._post(f"/api/v1/tasks/{task_id}/cancel")

    def onboarding_state(self) -> Dict:
        return self._get("/api/v1/tasks/onboarding/state")

    def stream_tasks(self, after_id: int = 0):
        """Yield decoded global task SSE events from a durable cursor."""
        headers = self._headers()
        headers["Last-Event-ID"] = str(max(0, after_id))
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=20.0, write=30.0, pool=30.0)) as client:
            with client.stream(
                "GET", f"{self.base_url}/api/v1/tasks/stream",
                headers=headers, params={"after_id": max(0, after_id)},
            ) as response:
                response.raise_for_status()
                event: Dict = {}
                for line in response.iter_lines():
                    if not line:
                        if event.get("data"):
                            import json
                            try:
                                event["payload"] = json.loads(event.pop("data"))
                            except (TypeError, ValueError):
                                event = {}
                            if event:
                                yield event
                        event = {}
                        continue
                    if line.startswith(":"):
                        continue
                    key, _, value = line.partition(":")
                    event[key] = value.lstrip()

    # ---- HTTP helpers ----

    def _get(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _post(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _patch(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.patch(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _delete(self, path: str, **kwargs) -> Dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.delete(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
            resp.raise_for_status()
            return resp.json()