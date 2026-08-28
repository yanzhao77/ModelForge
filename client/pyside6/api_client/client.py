"""API Client for communicating with ModelForge backend (REST + SSE)."""
import json
from collections.abc import Iterator
from typing import Dict

import httpx


class ApiClientError(RuntimeError):
    """Base error displayed safely by desktop UI boundaries."""

    def __init__(self, code: str, correlation_id: str | None = None):
        self.code = code
        self.correlation_id = correlation_id
        suffix = f" (request_id: {correlation_id})" if correlation_id else ""
        super().__init__(f"{code}{suffix}")


class AuthenticationError(ApiClientError):
    """The current session is missing, expired, or rejected by the service."""

    def __init__(self, code: str, correlation_id: str | None = None):
        super().__init__(code, correlation_id)
        suffix = f" (request_id: {correlation_id})" if correlation_id else ""
        self.args = (f"会话已失效，请重新登录 [{code}]{suffix}",)


class AuthorizationError(ApiClientError):
    """The signed-in account lacks permission for the requested operation."""

    def __init__(self, code: str, correlation_id: str | None = None):
        super().__init__(code, correlation_id)
        suffix = f" (request_id: {correlation_id})" if correlation_id else ""
        self.args = (f"无权执行此操作 [{code}]{suffix}",)


class ValidationError(ApiClientError):
    """The service rejected user-supplied input."""


class ServiceUnavailableError(ApiClientError):
    """The service is unreachable or cannot process the request."""

    def __init__(self, code: str, correlation_id: str | None = None):
        super().__init__(code, correlation_id)
        suffix = f" (request_id: {correlation_id})" if correlation_id else ""
        self.args = (f"无法连接到服务或服务暂不可用 [{code}]{suffix}",)


class ModelForgeClient:
    """HTTP client for the ModelForge REST API with Bearer-token auth."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self.username: str | None = None

    # ---- auth state ----

    def set_token(self, token: str | None):
        self._token = token

    def has_token(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # ---- server info ----

    def get_info(self) -> dict:
        return self._get("/")

    def system_status(self) -> dict:
        return self._get("/api/v1/system/status")

    # ---- auth ----

    def register(self, username: str, password: str, email: str | None = None) -> dict:
        return self._post("/api/v1/auth/register", json={"username": username, "password": password, "email": email})

    def login(self, username: str, password: str) -> dict:
        data = self._post("/api/v1/auth/login", json={"username": username, "password": password})
        self.set_token(data.get("token"))
        self.username = (data.get("user") or {}).get("username", username)
        return data

    def me(self) -> dict:
        return self._get("/api/v1/auth/me")

    def change_password(self, old_password: str, new_password: str) -> dict:
        return self._post(
            "/api/v1/auth/change-password",
            json={"old_password": old_password, "new_password": new_password},
        )

    # ---- models ----

    def list_models(self) -> list[dict]:
        return self._get("/api/v1/models")

    def model_readiness(self) -> dict:
        return self._get("/api/v1/models/readiness")

    def set_default_model(
        self, kind: str, model_ref: str, provider_id: int | None = None
    ) -> dict:
        payload = {"kind": kind, "model_ref": model_ref}
        if provider_id is not None:
            payload["provider_id"] = provider_id
        return self._put("/api/v1/models/default", json=payload)

    def clear_default_model(self) -> dict:
        return self._delete("/api/v1/models/default")

    # ---- remote providers (API keys are write-only and never returned) ----
    def list_remote_providers(self) -> list[dict]:
        return self._get("/api/v1/providers").get("providers", [])

    def save_remote_provider(self, name: str, base_url: str, protocol: str, default_model: str, api_key: str | None = None) -> dict:
        payload = {"name": name, "base_url": base_url, "protocol": protocol, "default_model": default_model}
        if api_key:
            payload["api_key"] = api_key
        return self._post("/api/v1/providers", json=payload)

    def verify_remote_provider(self, provider_id: int, *, confirm: bool = False, request_id: str | None = None) -> dict:
        payload = {"confirm": confirm}
        if request_id:
            payload["request_id"] = request_id
        return self._post(f"/api/v1/providers/{provider_id}/verify", json=payload)

    def delete_remote_provider(self, provider_id: int) -> dict:
        return self._delete(f"/api/v1/providers/{provider_id}")

    def scan_models(self, path: str | None = None) -> list[dict]:
        return self._post("/api/v1/models/scan", json={"path": path or None})

    def install_model(self, name: str, provider: str, path: str, size: str = "") -> dict:
        return self._post("/api/v1/models/install", json={"name": name, "provider": provider, "path": path, "size": size})

    def remove_model(self, model_id: int) -> dict:
        return self._delete(f"/api/v1/models/{model_id}")

    def search_models(self, query: str = "", author: str | None = None, limit: int = 20) -> list[dict]:
        params = {"q": query, "limit": limit}
        if author:
            params["author"] = author
        return self._get("/api/v1/models/search", params=params)

    def download_model(self, repo_id: str, filename: str | None = None) -> dict:
        return self._post("/api/v1/models/download", json={"repo_id": repo_id, "filename": filename})

    def download_status(self, task_id: str) -> dict:
        return self._get(f"/api/v1/models/download/{task_id}")

    # ---- runtime ----

    def runtime_start(self, model: str) -> dict:
        return self._post("/api/v1/runtime/start", json={"model": model})

    def runtime_chat(self, model: str, messages: list) -> dict:
        return self._post("/api/v1/runtime/chat", json={"model": model, "messages": messages})

    def runtime_stop(self, model: str) -> dict:
        return self._post("/api/v1/runtime/stop", json={"model": model})

    def runtime_status(self) -> dict:
        return self._get("/api/v1/runtime/status")

    # ---- chat (JSON + SSE) ----

    def chat(self, model: str, messages: list, session_id: int | None = None, provider_id: int | None = None) -> dict:
        return self._post(
            "/api/v1/chat",
            json={"model": model, "messages": messages, "session_id": session_id, "provider_id": provider_id},
        )

    def stream_chat(
        self, model: str, messages: list, session_id: int | None = None, provider_id: int | None = None
    ) -> Iterator[dict]:
        """Yield SSE events: {type: delta|done|error, data: ...}."""
        with httpx.Client(timeout=None) as client, client.stream(
            "POST",
            f"{self.base_url}/api/v1/chat/stream",
            json={"model": model, "messages": messages, "session_id": session_id, "provider_id": provider_id},
            headers=self._headers(),
        ) as resp:
            self._raise_for_status(resp)
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

    def list_sessions(self) -> list[dict]:
        return self._get("/api/v1/sessions")

    def create_session(self, title: str = "新对话") -> dict:
        return self._post("/api/v1/sessions", json={"title": title})

    def get_session(self, session_id: int) -> dict:
        return self._get(f"/api/v1/sessions/{session_id}")

    def rename_session(self, session_id: int, title: str) -> dict:
        return self._patch(f"/api/v1/sessions/{session_id}", json={"title": title})

    def delete_session(self, session_id: int) -> dict:
        return self._delete(f"/api/v1/sessions/{session_id}")

    def list_messages(self, session_id: int, limit: int | None = None) -> list[dict]:
        params = {}
        if limit:
            params["limit"] = limit
        return self._get(f"/api/v1/sessions/{session_id}/messages", params=params)

    def clear_messages(self, session_id: int) -> dict:
        return self._delete(f"/api/v1/sessions/{session_id}/messages")

    def auto_title(self, session_id: int) -> dict:
        return self._post(f"/api/v1/sessions/{session_id}/title")

    # ---- memories ----

    def list_memories(self, memory_type: str | None = None) -> list[dict]:
        params = {"memory_type": memory_type} if memory_type else {}
        return self._get("/api/v1/memories", params=params)

    def create_memory(self, memory_type: str, key: str, value: str) -> dict:
        return self._post("/api/v1/memories", json={"memory_type": memory_type, "key": key, "value": value})

    def search_memories(self, q: str) -> list[dict]:
        return self._get("/api/v1/memories/search", params={"q": q})

    # ---- automation schedules ----

    def list_schedules(self) -> list[dict]:
        return self._get("/api/v1/agent/schedules").get("schedules", [])

    def create_schedule(self, payload: dict) -> dict:
        return self._post("/api/v1/agent/schedules", json=payload)

    def update_schedule(self, schedule_id: str, payload: dict) -> dict:
        return self._patch(f"/api/v1/agent/schedules/{schedule_id}", json=payload)

    def enable_schedule(self, schedule_id: str, *, confirm: bool = False) -> dict:
        return self._post(f"/api/v1/agent/schedules/{schedule_id}/enable", json={"confirm": confirm})

    def pause_schedule(self, schedule_id: str, *, confirm: bool = False) -> dict:
        return self._post(f"/api/v1/agent/schedules/{schedule_id}/pause", json={"confirm": confirm})

    def run_schedule_now(self, schedule_id: str, *, confirm: bool = False) -> dict:
        return self._post(f"/api/v1/agent/schedules/{schedule_id}/run-now", json={"confirm": confirm})

    def delete_schedule(self, schedule_id: str, *, confirm: bool = False) -> dict:
        return self._delete(f"/api/v1/agent/schedules/{schedule_id}", json={"confirm": confirm})

    def schedule_executions(self, schedule_id: str) -> list[dict]:
        return self._get(f"/api/v1/agent/schedules/{schedule_id}/executions").get("executions", [])

    def schedule_preview(self, schedule_id: str) -> dict:
        return self._get(f"/api/v1/agent/schedules/{schedule_id}/preview")

    # ---- workspace governance ----

    def migration_preflight(self) -> dict:
        return self._get("/api/v1/workspaces/migration-preflight")

    def runtime_diagnostics(self) -> dict:
        return self._get("/api/v1/workspaces/runtime-diagnostics")

    def lifecycle_diagnostics(self, retention_days: int = 30) -> dict:
        return self._get("/api/v1/workspaces/lifecycle-diagnostics", params={"retention_days": retention_days})

    def operation_audits(self, *, limit: int = 100, user_id: int | None = None, action: str | None = None, correlation: str | None = None, before: str | None = None) -> dict:
        params = {"limit": max(1, min(int(limit), 200))}
        for key, value in {"user_id": user_id, "action": action, "correlation": correlation, "before": before}.items():
            if value not in (None, ""):
                params[key] = value
        return self._get("/api/v1/workspaces/operation-audits", params=params)

    def preview_lifecycle(self, retention_days: int = 30, *, action: str = "retention.cleanup", target_id: str | None = None) -> dict:
        payload = {"retention_days": retention_days, "action": action}
        if target_id:
            payload["target_id"] = target_id
        return self._post("/api/v1/workspaces/lifecycle-preview", json=payload)

    def check_lifecycle_confirmation(self, action: str, preview_token: str, confirm: bool) -> dict:
        return self._post(
            "/api/v1/workspaces/lifecycle-confirmation-check",
            json={"action": action, "preview_token": preview_token, "confirm": confirm},
        )

    def preview_execution_intent(
        self,
        action: str,
        target_ids: list[str],
        *,
        expected_versions: list[int] | None = None,
        expected_versions_by_target: dict[str, int] | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Request a read-only confirmation summary; this never executes the action."""
        payload = {
            "action": action,
            "target_ids": target_ids,
            "expected_versions": expected_versions or [],
            "expected_versions_by_target": expected_versions_by_target or {},
        }
        if request_id:
            payload["request_id"] = request_id
        return self._post("/api/v1/workspaces/execution-intent-preview", json=payload)

    def check_execution_intent_confirmation(
        self,
        action: str,
        preview_token: str,
        *,
        confirm: bool = False,
        request_id: str | None = None,
    ) -> dict:
        """Check the signed preview contract while the server still blocks execution."""
        payload = {"action": action, "preview_token": preview_token, "confirm": confirm}
        if request_id:
            payload["request_id"] = request_id
        return self._post("/api/v1/workspaces/execution-intent-confirmation-check", json=payload)

    def list_artifacts(self) -> list[dict]:
        return self._get("/api/v1/workspaces/artifacts").get("artifacts", [])

    def capture_run_artifact(self, run_id: str) -> dict:
        return self._post(f"/api/v1/workspaces/artifacts/from-run/{run_id}")

    def delete_artifact(self, artifact_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._delete(f"/api/v1/workspaces/artifacts/{artifact_id}", json={"confirm": confirm, "request_id": request_id})

    def get_artifact(self, artifact_id: str) -> dict:
        return self._get(f"/api/v1/workspaces/artifacts/{artifact_id}")

    def list_knowledge_collections(self) -> list[dict]:
        return self._get("/api/v1/workspaces/collections").get("collections", [])

    def create_knowledge_collection(self, name: str, description: str = "", tags: list[str] | None = None, *, request_id: str | None = None) -> dict:
        return self._post("/api/v1/workspaces/collections", json={"name": name, "description": description, "tags": tags or [], "request_id": request_id})

    def add_document_to_knowledge_collection(self, collection_id: str, document_id: int, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/workspaces/collections/{collection_id}/documents/{document_id}", json={"confirm": confirm, "request_id": request_id})

    def get_knowledge_collection(self, collection_id: str) -> dict:
        return self._get(f"/api/v1/workspaces/collections/{collection_id}")

    def remove_document_from_knowledge_collection(self, collection_id: str, document_id: int, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._delete(f"/api/v1/workspaces/collections/{collection_id}/documents/{document_id}", json={"confirm": confirm, "request_id": request_id})

    def delete_knowledge_collection(self, collection_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._delete(f"/api/v1/workspaces/collections/{collection_id}", json={"confirm": confirm, "request_id": request_id})

    def list_plugin_profiles(self) -> list[dict]:
        return self._get("/api/v1/workspaces/plugin-profiles").get("profiles", [])

    def create_plugin_profile(self, name: str, plugins: list[str] | None = None, mcp_servers: list[str] | None = None, *, request_id: str | None = None) -> dict:
        return self._post("/api/v1/workspaces/plugin-profiles", json={"name": name, "plugins": plugins or [], "mcp_servers": mcp_servers or [], "request_id": request_id})

    def preview_plugin_profile(self, profile_id: str) -> dict:
        return self._get(f"/api/v1/workspaces/plugin-profiles/{profile_id}/preview")

    def delete_plugin_profile(self, profile_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._delete(f"/api/v1/workspaces/plugin-profiles/{profile_id}", json={"confirm": confirm, "request_id": request_id})

    def model_insights(self, days: int = 30) -> dict:
        return self._get("/api/v1/workspaces/insights", params={"days": days})

    def control_plane_budget(self) -> dict:
        """Read the informational budget summary; this does not start or alter work."""
        return self._get("/api/v1/workspaces/control-plane-budget")

    def update_model_insight_preferences(self, payload: dict, *, request_id: str | None = None) -> dict:
        return self._put("/api/v1/workspaces/insights/preferences", json={**payload, "request_id": request_id})

    def delete_memory(self, memory_id: int, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._delete(f"/api/v1/memories/{memory_id}", json={"confirm": confirm, "request_id": request_id})

    def update_memory(self, memory_id: int, *, value: str | None = None, importance: float | None = None, request_id: str | None = None) -> dict:
        payload = {key: item for key, item in {"value": value, "importance": importance, "request_id": request_id}.items() if item is not None}
        return self._patch(f"/api/v1/memories/{memory_id}", json=payload)

    def list_agent_templates(self) -> list[dict]:
        return self._get("/api/v1/agent/templates").get("templates", [])

    def create_agent_template(self, name: str, definition: dict, description: str = "") -> dict:
        return self._post("/api/v1/agent/templates", json={"name": name, "description": description, "definition": definition})

    def delete_agent_template(self, template_id: str) -> dict:
        return self._delete(f"/api/v1/agent/templates/{template_id}")

    def agent_versions(self, name: str) -> dict:
        return self._get(f"/api/v1/agent/{name}/versions")

    def list_runtime_plugins(self) -> list[dict]:
        return self._get("/api/v1/plugins/runtime").get("plugins", [])

    def plugin_impact(self, name: str) -> dict:
        return self._get(f"/api/v1/plugins/{name}/impact")

    def plugin_health(self, name: str) -> dict:
        return self._post(f"/api/v1/plugins/{name}/health")

    def plugin_lifecycle(self, name: str, action: str, *, confirm: bool = False) -> dict:
        if action not in {"start", "stop", "mount", "unmount", "unload"}:
            raise ValueError("unsupported plugin lifecycle action")
        if action == "unload":
            return self._delete(f"/api/v1/plugins/{name}", json={"confirm": confirm})
        return self._post(f"/api/v1/plugins/{name}/{action}", json={"confirm": confirm})

    # ---- agents / knowledge (basic) ----

    def create_agent(self, name: str, model: str, tools: list[str]) -> dict:
        return self._post("/api/v1/agent/create", json={"name": name, "model": model, "tools": tools})

    def list_agents(self) -> list[dict]:
        return self._get("/api/v1/agent/list")

    def delete_agent(self, name: str) -> Dict:
        return self._delete(f"/api/v1/agent/{name}")

    def agent_chat(self, name: str, message: str) -> dict:
        return self._post(f"/api/v1/agent/{name}/chat", json={"message": message})

    def knowledge_upload(self, filepath: str) -> dict:
        with open(filepath, "rb") as f:
            files = {"file": (filepath.split("/")[-1], f, "application/octet-stream")}
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/knowledge/upload", files=files, headers=self._headers()
                )
                self._raise_for_status(resp)
                return resp.json()

    def knowledge_query(self, question: str, top_k: int = 5) -> dict:
        return self._post("/api/v1/knowledge/query", json={"question": question, "top_k": top_k})


    # ---- agent runs (3.0) ----

    def create_agent_run(self, agent_id: str, input_text: str, session_id: int | None = None, metadata: dict | None = None, execute: bool = False, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post("/api/v1/agent/runs", json={
            "agent_id": agent_id, "input": input_text,
            "session_id": session_id, "metadata": metadata, "execute": execute,
            "confirm": confirm, "request_id": request_id,
        })

    def list_agent_runs(self, agent_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if status:
            params["status"] = status
        return self._get("/api/v1/agent/runs", params=params)

    def get_agent_run(self, run_id: str) -> dict:
        return self._get(f"/api/v1/agent/runs/{run_id}")

    def cancel_agent_run(self, run_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/agent/runs/{run_id}/cancel", json={"confirm": confirm, "request_id": request_id})

    def approve_agent_run(self, run_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/agent/runs/{run_id}/approve", json={"confirm": confirm, "request_id": request_id})

    def reject_agent_run(self, run_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/agent/runs/{run_id}/reject", json={"confirm": confirm, "request_id": request_id})

    def get_agent_run_events(self, run_id: str, after_sequence: int = 0) -> list[dict]:
        data = self._get(f"/api/v1/agent/runs/{run_id}/events", params={"after_sequence": after_sequence})
        return data.get("events", [])

    def stream_agent_run(self, run_id: str, after_sequence: int = 0) -> Iterator[dict]:
        """Yield Agent Run SSE events while sending equivalent query and header cursors."""
        cursor = max(0, after_sequence)
        headers = self._headers()
        headers["Last-Event-ID"] = str(cursor)
        with httpx.Client(timeout=None) as client, client.stream(
            "GET",
            f"{self.base_url}/api/v1/agent/runs/{run_id}/stream",
            params={"after_sequence": cursor},
            headers=headers,
        ) as resp:
            self._raise_for_status(resp)
            event: dict[str, str] = {}
            data_lines: list[str] = []

            def flush_event() -> dict | None:
                """Decode one SSE frame and clear the parser buffer."""
                nonlocal event, data_lines
                if not data_lines:
                    event = {}
                    return None
                try:
                    payload = json.loads("\n".join(data_lines))
                except (TypeError, ValueError):
                    event = {}
                    data_lines = []
                    return None
                if event.get("event") == "resync_required" and isinstance(payload, dict):
                    result: dict | None = {"event_type": "resync_required", "payload": payload}
                elif isinstance(payload, dict):
                    if event.get("id") is not None and "sequence" not in payload:
                        payload["sequence"] = event["id"]
                    result = payload
                else:
                    result = None
                event = {}
                data_lines = []
                return result

            for line in resp.iter_lines():
                line = line.rstrip("\r")
                if not line:
                    payload = flush_event()
                    if payload is not None:
                        yield payload
                    continue
                if line.startswith(":"):
                    continue
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                if value.startswith(" "):
                    value = value[1:]
                if key == "data":
                    # Some reverse proxies close or coalesce streams without a
                    # blank separator. If the buffered frame is already a valid
                    # JSON event, emit it before starting the next data frame;
                    # otherwise retain it for a standards-compliant multiline
                    # SSE payload.
                    if data_lines:
                        try:
                            json.loads("\n".join(data_lines))
                        except (TypeError, ValueError):
                            pass
                        else:
                            payload = flush_event()
                            if payload is not None:
                                yield payload
                    data_lines.append(value)
                elif key in {"event", "id"}:
                    event[key] = value

            # A compliant stream normally ends with a blank frame separator, but
            # accept a final buffered event so abrupt proxy/server EOF does not
            # silently drop the last Agent Run update.
            payload = flush_event()
            if payload is not None:
                yield payload

    def list_agent_tools(self) -> list[dict]:
        data = self._get("/api/v1/agent/tools")
        return data.get("tools", [])

    def agent_metrics(self) -> dict:
        return self._get("/api/v1/agent/metrics")

    def register_mcp_server(self, name: str, endpoint: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post("/api/v1/agent/mcp/servers", json={"name": name, "endpoint": endpoint, "confirm": confirm, "request_id": request_id})

    def list_mcp_servers(self) -> list[dict]:
        data = self._get("/api/v1/agent/mcp/servers")
        return data.get("servers", [])

    def unregister_mcp_server(self, name: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._delete(f"/api/v1/agent/mcp/servers/{name}", json={"confirm": confirm, "request_id": request_id})

    def create_agent_config(self, name: str, model: str, tools: list[str], system_prompt: str | None = None, policy: dict | None = None, runtime_config: dict | None = None, model_target: dict | None = None) -> dict:
        return self._post("/api/v1/agent/create", json={
            "name": name, "model": model, "tools": tools,
            "system_prompt": system_prompt, "policy": policy, "runtime_config": runtime_config,
            "model_target": model_target,
        })

    # ---- datasets ----

    def upload_dataset(self, filepath: str, name: str | None = None) -> dict:
        with open(filepath, "rb") as f:
            files = {"file": (filepath.split("/")[-1], f, "application/octet-stream")}
            data = {"name": name} if name else None
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/datasets/upload",
                    files=files, data=data, headers=self._headers(),
                )
                self._raise_for_status(resp)
                return resp.json()

    def list_datasets(self) -> list[dict]:
        return self._get("/api/v1/datasets")

    def get_dataset(self, dataset_id: int) -> dict:
        return self._get(f"/api/v1/datasets/{dataset_id}")

    def validate_dataset(self, dataset_id: int) -> dict:
        return self._post(f"/api/v1/datasets/{dataset_id}/validate")

    def delete_dataset(self, dataset_id: int) -> dict:
        return self._delete(f"/api/v1/datasets/{dataset_id}")

    # ---- training ----

    def train_templates(self) -> dict:
        return self._get("/api/v1/train/templates")

    def train_start(self, config: dict, *, confirm: bool = False, request_id: str | None = None) -> dict:
        payload = {**config, "confirm": confirm, "request_id": request_id}
        return self._post("/api/v1/train/start", json=payload)

    def train_status(self, task_id: str) -> dict:
        return self._get(f"/api/v1/train/status/{task_id}")

    def train_tasks(self) -> list[dict]:
        return self._get("/api/v1/train/tasks")

    def train_stop(self, task_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/train/stop/{task_id}", json={"confirm": confirm, "request_id": request_id})

    def train_register_model(self, task_id: str, *, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/train/{task_id}/register-model", json={"confirm": confirm, "request_id": request_id})

    def train_stream(self, task_id: str) -> Iterator[dict]:
        """Yield training SSE events: {type: log|progress|done, data: ...}."""
        with httpx.Client(timeout=None) as client, client.stream(
            "GET",
            f"{self.base_url}/api/v1/train/stream/{task_id}",
            headers=self._headers(),
        ) as resp:
            self._raise_for_status(resp)
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

    def knowledge_documents(self) -> list[dict]:
        return self._get("/api/v1/knowledge/documents")

    def knowledge_delete(self, filename: str) -> dict:
        return self._delete(f"/api/v1/knowledge/documents/{filename}")

    def knowledge_chunks(self, filename: str) -> list[dict]:
        return self._get(f"/api/v1/knowledge/documents/{filename}/chunks")

    def knowledge_answer(self, model: str, question: str, top_k: int = 3) -> dict:
        return self._post(
            "/api/v1/knowledge/answer",
            json={"question": question, "top_k": top_k, "model": model},
        )

    # ---- global task center / onboarding ----
    def list_tasks(self) -> list[dict]:
        return self._get("/api/v1/tasks").get("tasks", [])

    def task_summary(self) -> dict:
        return self._get("/api/v1/tasks/summary")

    def get_task(self, task_id: str) -> dict:
        return self._get(f"/api/v1/tasks/{task_id}")

    def cancel_task(self, task_id: str, *, confirm: bool = False, expected_version: int | None = None, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/tasks/{task_id}/cancel", json={"confirm": confirm, "expected_version": expected_version, "request_id": request_id})

    def retry_task(self, task_id: str, *, confirm: bool = False, expected_version: int | None = None, request_id: str | None = None) -> dict:
        return self._post(f"/api/v1/tasks/{task_id}/retry", json={"confirm": confirm, "expected_version": expected_version, "request_id": request_id})

    def retry_tasks_batch(self, task_ids: list[str], *, expected_versions: dict[str, int] | None = None, confirm: bool = False, request_id: str | None = None) -> dict:
        return self._post("/api/v1/tasks/retry-batch", json={"task_ids": task_ids, "expected_versions": expected_versions or {}, "confirm": confirm, "request_id": request_id})

    def task_events(self, task_id: str, limit: int = 200) -> list[dict]:
        return self._get(f"/api/v1/tasks/{task_id}/events", params={"limit": limit}).get("events", [])

    def task_logs(self, task_id: str, limit: int = 200) -> dict:
        return self._get(f"/api/v1/tasks/{task_id}/logs", params={"limit": limit})

    def onboarding_state(self) -> dict:
        return self._get("/api/v1/tasks/onboarding/state")

    def stream_tasks(self, after_id: int = 0):
        """Yield decoded global task SSE events from a durable cursor."""
        cursor = max(0, after_id)
        headers = self._headers()
        headers["Last-Event-ID"] = str(cursor)
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=20.0, write=30.0, pool=30.0)) as client:
            with client.stream(
                "GET", f"{self.base_url}/api/v1/tasks/stream",
                headers=headers, params={"after_id": cursor},
            ) as response:
                self._raise_for_status(response)
                event: dict = {}
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

    def _raise_for_status(self, response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            code = f"HTTP_{status}"
            correlation = error.response.headers.get("X-Request-ID")
            try:
                body = error.response.json()
                detail = body.get("detail") if isinstance(body, dict) else None
            except (TypeError, ValueError):
                detail = None
            if isinstance(detail, dict):
                code = str(detail.get("code") or code)
                correlation = str(detail.get("correlation_id") or correlation or "") or None
            code = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in code.upper())[:96] or f"HTTP_{status}"
            if correlation:
                correlation = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in correlation)[:128] or None
            if status == 401:
                self.set_token(None)
                self.username = None
                raise AuthenticationError(code or "AUTHENTICATION_REQUIRED", correlation) from error
            if status == 403:
                raise AuthorizationError(code or "AUTHORIZATION_DENIED", correlation) from error
            if status in {400, 404, 409, 422}:
                raise ValidationError(code, correlation) from error
            raise ServiceUnavailableError(code, correlation) from error
        except httpx.HTTPError as error:
            raise ServiceUnavailableError("SERVICE_UNAVAILABLE") from error

    # ---- HTTP helpers ----

    def _get(self, path: str, **kwargs) -> dict:
        return self._request_json("get", path, timeout=30.0, **kwargs)

    def _post(self, path: str, **kwargs) -> dict:
        return self._request_json("post", path, timeout=120.0, **kwargs)

    def _patch(self, path: str, **kwargs) -> dict:
        return self._request_json("patch", path, timeout=30.0, **kwargs)

    def _put(self, path: str, **kwargs) -> dict:
        return self._request_json("put", path, timeout=30.0, **kwargs)

    def _delete(self, path: str, **kwargs) -> dict:
        return self._request_json("delete", path, timeout=30.0, **kwargs)

    def _request_json(self, method: str, path: str, timeout: float, **kwargs) -> dict:
        try:
            with httpx.Client(timeout=timeout) as client:
                request = getattr(client, method)
                response = request(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
                self._raise_for_status(response)
                return response.json()
        except ApiClientError:
            raise
        except httpx.HTTPError as error:
            raise ServiceUnavailableError("SERVICE_UNAVAILABLE") from error
