from __future__ import annotations

import asyncio
import datetime
import inspect
import time
import uuid
from collections.abc import Callable
from typing import Any

from core.config import RuntimeSettings, Settings
from core.config import settings as global_settings

from .cancellation import CancellationToken
from .errors import (
    AgentNotFoundError,
    ModelUnavailableError,
    RunNotFoundError,
    RuntimeError,
)
from .events import EventBus
from .execution import ExecutionEngine
from .logging import get_logger, log_run
from .metrics import MetricsRegistry
from .models.base import ModelProvider
from .run_context import RunContext
from .types import AgentConfig, RunRecord, RunStatus

ProviderFactory = Callable[..., ModelProvider]


def default_provider_factory(model_name: str) -> ModelProvider:
    """Default: Ollama-backed provider (spec 14). Overridable in tests."""
    from .models.ollama import OllamaProvider
    return OllamaProvider(model_name)


class AgentRuntime:
    """Facade of the 3.0 Agent Runtime (spec 19 / 44).

    API -> AgentRuntime -> ExecutionEngine -> Ports/Adapters.
    No global current_run (spec 58): every run lives in its own task with
    its own CancellationToken.
    """

    def __init__(
        self,
        *,
        run_store: Any,
        agent_store: Any,
        event_bus: EventBus | None = None,
        tool_runner: Any = None,
        tool_registry: Any = None,
        provider_factory: ProviderFactory | None = None,
        context_builder: Any = None,
        memory_provider: Any = None,
        knowledge_provider: Any = None,
        history_provider: Any = None,
        policy_engine: Any = None,
        metrics: MetricsRegistry | None = None,
        scheduler: Any = None,
        settings: Settings | None = None,
        logger: Any = None,
    ):
        self.run_store = run_store
        self.agent_store = agent_store
        self.event_bus = event_bus
        self.event_store = getattr(event_bus, "store", None) if event_bus is not None else None
        self.settings = settings or global_settings
        self.logger = logger or get_logger()
        self.metrics = metrics or MetricsRegistry()

        # Tool Registry (spec 8): default = builtin tools
        if tool_registry is None and tool_runner is None:
            from .tools import ToolRegistry
            from .tools.builtin import register_builtin_tools
            tool_registry = register_builtin_tools(ToolRegistry())
        self.tool_registry = tool_registry
        if tool_runner is None and tool_registry is not None:
            from .tools import ToolExecutor
            tool_runner = ToolExecutor(
                tool_registry,
                default_timeout=float(self.settings.tools.default_timeout_seconds),
            )
        if self.tool_registry is not None:
            # multi-agent capability (spec 40 / 73)
            from .tools.delegate import DelegateTool
            self.tool_registry.register(DelegateTool(self))
        self.tool_runner = tool_runner

        self.provider_factory = provider_factory or default_provider_factory
        self.context_builder = context_builder
        self.memory_provider = memory_provider
        self.knowledge_provider = knowledge_provider
        self.history_provider = history_provider
        if policy_engine is None:
            from .policy import PolicyEngine
            policy_engine = PolicyEngine(settings=self.settings)
        self.policy_engine = policy_engine
        if scheduler is not None and getattr(scheduler, "trigger", None) is None:
            scheduler.trigger = self._scheduler_trigger
        self.scheduler = scheduler

        self.engine = ExecutionEngine(
            event_bus=event_bus,
            tool_runner=tool_runner,
            context_builder=context_builder,
            metrics=self.metrics,
            logger=self.logger,
        )

        # per-run bookkeeping (no globals, spec 58)
        self._cancellations: dict[str, CancellationToken] = {}
        self._running: set = set()
        self._approvals: dict[str, asyncio.Event] = {}
        self._approval_grants: dict[str, bool] = {}
        self._created_events: set = set()
        self._delegation_counts: dict[str, int] = {}
        self._mcp_registry: Any = None
        self._scopes: dict[str, Any] = {}
        self.plugin_manager: Any = None
        self._started = False

    # ---- lifecycle (spec 64) ----
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self.event_bus is not None:
            self.event_bus.start()
        if self.scheduler is not None and hasattr(self.scheduler, "start"):
            self.scheduler.start()
        log_run(self.logger, 20, "agent runtime started")

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        for token in list(self._cancellations.values()):
            token.cancel()
        if self.scheduler is not None and hasattr(self.scheduler, "stop"):
            await self.scheduler.stop()
        if self.event_bus is not None:
            await self.event_bus.shutdown()
        log_run(self.logger, 20, "agent runtime stopped")

    # ---- run lifecycle (spec 65) ----
    def create_run(
        self,
        *,
        agent_id: str,
        input_text: str,
        user_id: int | None = None,
        session_id: int | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        execute: bool = True,
    ) -> RunRecord:
        agent = self.agent_store.get(agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        run = RunRecord(
            run_id=uuid.uuid4().hex,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            parent_run_id=parent_run_id,
            status=RunStatus.PENDING.value,
            input=input_text,
            model=agent.model,
            metadata=metadata or {},
        )
        self.run_store.create(run)
        self._spawn(self._emit_created(run))
        if execute:
            self._spawn(self.execute_run(run.run_id))
        log_run(self.logger, 20, "run created", run_id=run.run_id, agent_id=agent_id)
        return run

    async def execute_run(self, run_id: str) -> dict[str, Any]:
        run = self.run_store.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        if run.status in RunStatus.terminal():
            return {"status": run.status, "output": run.output, "error": run.error}
        # idempotency: another task may already be executing this run (spec 58)
        if run.status == "RUNNING" or run_id in self._running:
            return {"status": run.status, "output": run.output, "error": run.error}

        agent = self.agent_store.get(run.agent_id)
        if agent is None:
            await self._fail(run_id, "AGENT_NOT_FOUND", f"Agent {run.agent_id} not found", "FAILED")
            return {"status": "FAILED", "error": "agent not found"}

        token = CancellationToken()
        self._cancellations[run_id] = token
        self._running.add(run_id)
        await self._emit_created(run)
        now = datetime.datetime.utcnow()
        self.run_store.update(run_id, status="RUNNING", started_at=now)
        await self._publish(run_id, "run.started", {"agent_id": run.agent_id, "model": run.model})

        try:
            provider = self._make_provider(run, agent)
        except ModelUnavailableError as e:
            await self._fail(run_id, e.code, e.message, "FAILED")
            return {"status": "FAILED", "error": e.message}

        ctx = self._build_context(run, agent, token)
        started = time.monotonic()
        outcome = None
        duration = 0.0
        try:
            outcome = await self.engine.execute(ctx, provider)
            duration = time.monotonic() - started
            status = outcome["status"]
            self.run_store.update(
                run_id,
                status=status,
                output=outcome.get("output") or None,
                error=outcome.get("error"),
                token_usage=outcome.get("token_usage") or {},
                tool_call_count=outcome.get("tool_call_count", 0),
                iteration_count=outcome.get("iteration", 0),
                finished_at=datetime.datetime.utcnow(),
            )
            self.metrics.on_run_finished(status, duration)
        finally:
            # audit P0-5: run bookkeeping is always released even if finalize throws
            self._cancellations.pop(run_id, None)
            self._running.discard(run_id)
            self._created_events.discard(run_id)
            self._delegation_counts.pop(run_id, None)

        if outcome is None:
            await self._fail(run_id, "RUNTIME_ERROR", "engine returned no outcome", "FAILED")
            return {"status": "FAILED", "error": "engine returned no outcome"}

        payload = {
            "output": (outcome.get("output") or "")[:500],
            "duration": round(duration, 3),
            "tokens": outcome.get("token_usage") or {},
            "iteration": outcome.get("iteration", 0),
            "tool_calls": outcome.get("tool_call_count", 0),
        }
        if status == "COMPLETED":
            await self._publish(run_id, "run.completed", payload)
        elif status == "CANCELLED":
            await self._publish(run_id, "run.cancelled", payload)
        else:
            payload["error"] = outcome.get("error")
            payload["code"] = self._error_code(outcome.get("error"))
            await self._publish(run_id, "run.failed", payload)

        if self.event_bus is not None:
            try:
                await self.event_bus.flush()
                # audit P0-3: drop per-run sequence state only after terminal events are persisted
                self.event_bus.prune(run_id)
            except Exception:
                pass
        log_run(self.logger, 20, "run executed", run_id=run_id,
                status=status, duration_ms=round(duration * 1000))
        return outcome

    async def cancel_run(self, run_id: str, user_id: int | None = None) -> RunRecord:
        run = self.run_store.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        if user_id is not None and run.user_id is not None and run.user_id != user_id:
            raise RunNotFoundError(run_id)
        if run.status in RunStatus.terminal():
            return run
        token = self._cancellations.get(run_id)
        if token is not None:
            token.cancel()
        finished = datetime.datetime.utcnow()
        self.run_store.update(run_id, status="CANCELLED", finished_at=finished)
        self._cancellations.pop(run_id, None)
        self._running.discard(run_id)
        self._delegation_counts.pop(run_id, None)
        await self._publish(run_id, "run.cancelled", {"reason": "user requested", "output": run.output})
        self.metrics.on_run_finished("CANCELLED", 0.0)
        # 3.x-P5: cancellation propagates to children (recursively)
        children = self.run_store.list(parent_run_id=run_id)
        for child in children:
            if child.status not in RunStatus.terminal():
                try:
                    await self.cancel_run(child.run_id, user_id=user_id)
                except Exception:
                    continue
        return self.run_store.get(run_id)

    def get_run(self, run_id: str, user_id: int | None = None) -> RunRecord:
        run = self.run_store.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        if user_id is not None and run.user_id is not None and run.user_id != user_id:
            raise RunNotFoundError(run_id)
        return run

    def list_runs(
        self,
        user_id: int | None = None,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        return self.run_store.list(
            user_id=user_id, agent_id=agent_id, status=status, limit=limit, offset=offset,
        )

    def metrics_snapshot(self) -> dict[str, Any]:
        return self.metrics.snapshot()

    def is_running(self, run_id: str) -> bool:
        return run_id in self._running

    # ---- human gate (spec 32) ----
    async def _wait_for_approval(self, ctx: Any, tool_name: str) -> bool:
        """Pause the run at WAITING_HUMAN until approve/reject or timeout."""
        run_id = ctx.run_id
        if run_id in self._approval_grants:
            return bool(self._approval_grants.pop(run_id, False))
        await self._publish(run_id, "human.approval.required", {"tool": tool_name})
        await self._flush_audit_events()
        self.run_store.update(run_id, status="WAITING_HUMAN")
        event = asyncio.Event()
        self._approvals[run_id] = event
        self._approval_grants[run_id] = False
        try:
            timeout = getattr(ctx, "timeout_seconds", None) or 600
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            granted = False
        else:
            granted = bool(self._approval_grants.pop(run_id, False))
        self._approvals.pop(run_id, None)
        self._approval_grants.pop(run_id, None)
        self.run_store.update(run_id, status="RUNNING")
        return granted

    async def approve_run(self, run_id: str, user_id: int | None = None) -> RunRecord:
        run = self.get_run(run_id, user_id=user_id)
        self._approval_grants[run_id] = True
        await self._publish(run_id, "human.approval.granted", {"tool": None})
        await self._flush_audit_events()
        event = self._approvals.get(run_id)
        if event is not None:
            event.set()
        return run

    async def reject_run(self, run_id: str, user_id: int | None = None) -> RunRecord:
        run = self.get_run(run_id, user_id=user_id)
        self._approval_grants[run_id] = False
        await self._publish(run_id, "human.approval.denied", {"tool": None})
        await self._flush_audit_events()
        event = self._approvals.get(run_id)
        if event is not None:
            event.set()
        return run

    # ---- tool registry (spec 8 / 36) ----
    def register_tool(self, tool: Any, aliases: list[str] | None = None) -> Any:
        if self.tool_registry is None:
            raise RuntimeError("tool registry not configured")
        self.tool_registry.register(tool, aliases=aliases)
        return tool

    def unregister_tool(self, name: str) -> bool:
        if self.tool_registry is None:
            return False
        return self.tool_registry.unregister(name)

    def list_tools(self) -> list[dict[str, Any]]:
        if self.tool_registry is None:
            return []
        return [t.to_dict() for t in self.tool_registry.list()]

    def get_tool(self, name: str) -> Any | None:
        if self.tool_registry is None:
            return None
        return self.tool_registry.get(name)

    # ---- MCP servers (spec 36 / 70) ----
    async def register_mcp_server(
        self, name: str, endpoint: str, headers: dict[str, str] | None = None,
        transport: Any = None,
    ) -> dict[str, Any]:
        from .mcp import MCPClient, MCPRegistry
        if self._mcp_registry is None:
            self._mcp_registry = MCPRegistry()
        client = MCPClient(name, endpoint, headers=headers)
        if transport is not None:
            client.with_transport(transport)
        self._mcp_registry.register(client)
        await client.initialize()
        await client.list_tools()
        self._mcp_registry.sync_tools(self.tool_registry)
        log_run(self.logger, 20, "mcp server registered", name=name, tools=len(client.tools))
        return {"name": name, "endpoint": endpoint, "tools": len(client.tools), "server_info": client.server_info}

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        if self._mcp_registry is None:
            return []
        return self._mcp_registry.list()

    async def unregister_mcp_server(self, name: str) -> bool:
        if self._mcp_registry is None:
            return False
        client = self._mcp_registry.get(name)
        if client is None:
            return False
        for tool_def in getattr(client, "tools", []) or []:
            self.unregister_tool(tool_def.get("name"))
        return self._mcp_registry.unregister(name)

    # ---- events (spec 6 / 30 / 31) ----
    def list_events(self, run_id: str, after_sequence: int = 0, limit: int = 1000, user_id: int | None = None) -> list[Any]:
        run = self.get_run(run_id, user_id=user_id)
        if self.event_store is None:
            return []
        events = self.event_store.list(run.run_id, after_sequence=after_sequence, limit=limit)
        return events

    async def stream_events(self, run_id: str, after_sequence: int = 0, user_id: int | None = None):
        """Async generator: replay persisted events, then live events (SSE, spec 26 / 31).

        Subscribe first (no gap), then replay persisted events, then drain live
        events, skipping any already replayed (dedupe by sequence).
        """
        self.get_run(run_id, user_id=user_id)
        bus = self.event_bus
        last = after_sequence
        queue: asyncio.Queue[Any] = asyncio.Queue()

        def _sub(event: Any) -> None:
            if event.run_id == run_id and event.sequence > after_sequence:
                queue.put_nowait(event)

        if bus is not None:
            bus.subscribe(_sub)
        try:
            if self.event_store is not None:
                for ev in self.event_store.list(run_id, after_sequence=after_sequence):
                    last = max(last, ev.sequence)
                    yield ev
            if bus is None:
                return
            while True:
                terminal = self.run_store.get(run_id)
                if terminal is not None and terminal.status in RunStatus.terminal() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield None  # heartbeat
                    continue
                if event.sequence > last:
                    last = event.sequence
                    yield event
        finally:
            if bus is not None:
                bus.unsubscribe(_sub)

    # ---- agent definitions ----
    def create_agent(self, config: AgentConfig) -> AgentConfig:
        return self.agent_store.create(config)

    def get_agent(self, name: str, user_id: int | None = None) -> AgentConfig | None:
        return self.agent_store.get(name, user_id=user_id)

    def list_agents(self, user_id: int | None = None) -> list[AgentConfig]:
        return self.agent_store.list(user_id=user_id)

    def delete_agent(self, name: str, user_id: int | None = None) -> bool:
        return self.agent_store.delete(name, user_id=user_id)
    # ---- plugin manager (3.x, audit §16.5) ----
    def discover_capabilities(self, scope_id: str | None = None) -> dict[str, Any]:
        """Read-only capability index (3.x-P6, audit §16.9)."""
        from .plugins.discovery import CapabilityDiscovery
        return CapabilityDiscovery(self).discover(scope_id=scope_id)

    def get_plugin_manager(self) -> Any:
        """Lazily create the PluginManager bound to this runtime."""
        if self.plugin_manager is None:
            from .plugins.manager import PluginManager
            self.plugin_manager = PluginManager(
                self, plugins_dir=getattr(self.settings, "plugins_dir", None),
                event_bus=self.event_bus, logger=self.logger,
            )
        return self.plugin_manager

    # ---- plugin scopes (3.x, audit §16.4) ----
    def create_scope(self, scope_id: str, name: str | None = None) -> Any:
        """Create (or reuse) a plugin scope; mounts tools into the shared registry."""
        if scope_id in self._scopes:
            return self._scopes[scope_id]
        from .plugins.scope import PluginScope
        scope = PluginScope(
            scope_id, name=name, tool_registry=self.tool_registry,
            event_bus=self.event_bus, logger=self.logger,
        )
        self._scopes[scope_id] = scope
        return scope

    def get_scope(self, scope_id: str) -> Any | None:
        return self._scopes.get(scope_id)

    def list_scopes(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._scopes.values()]

    def remove_scope(self, scope_id: str) -> bool:
        scope = self._scopes.pop(scope_id, None)
        if scope is None:
            return False
        scope.unmount()
        return True

    def plugin_context(self, scope_id: str, plugin_name: str, config: dict[str, Any] | None = None) -> Any:
        scope = self.create_scope(scope_id)
        return scope.context(plugin_name, config=config)

    # ---- scheduler (spec 38 / 72) ----
    async def _scheduler_trigger(self, run_spec: dict[str, Any]) -> None:
        """Scheduler fires -> runtime creates an owned AgentRun."""
        agent_id = run_spec.get("agent_id", "")
        user_id = run_spec.get("user_id")
        if self.get_agent(agent_id, user_id=user_id) is None:
            return
        self.create_run(
            agent_id=agent_id,
            input_text=run_spec.get("input", ""),
            user_id=user_id,
            session_id=run_spec.get("session_id"),
            metadata=run_spec.get("metadata"),
            execute=True,
        )

    def schedule_once(self, delay: float, run_spec: dict[str, Any], user_id: int | None = None) -> str:
        if self.scheduler is None:
            raise RuntimeError("scheduler not configured")
        return self.scheduler.schedule_once(delay, run_spec, user_id=user_id)

    def schedule_interval(self, interval: float, run_spec: dict[str, Any], user_id: int | None = None) -> str:
        if self.scheduler is None:
            raise RuntimeError("scheduler not configured")
        return self.scheduler.schedule_interval(interval, run_spec, user_id=user_id)

    def cancel_schedule(self, job_id: str, user_id: int | None = None) -> bool:
        if self.scheduler is None:
            return False
        return self.scheduler.cancel(job_id, user_id=user_id)

    def list_schedules(self, user_id: int | None = None) -> list[dict[str, Any]]:
        if self.scheduler is None:
            return []
        return self.scheduler.jobs(user_id=user_id)
    # ---- internals ----
    def _make_provider(self, run: RunRecord, agent: AgentConfig) -> ModelProvider:
        model = run.model or agent.model or ""
        if not model:
            raise ModelUnavailableError("agent has no model")
        try:
            parameters = inspect.signature(self.provider_factory).parameters.values()
            accepts_agent = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in parameters) or len(parameters) >= 2
        except (TypeError, ValueError):
            accepts_agent = False
        return self.provider_factory(model, agent) if accepts_agent else self.provider_factory(model)

    async def _flush_audit_events(self) -> None:
        """Make human-gate audit records visible before changing the gate state."""
        if self.event_bus is not None:
            await self.event_bus.flush()

    def _build_context(
        self, run: RunRecord, agent: AgentConfig, token: CancellationToken,
    ) -> RunContext:
        rs: RuntimeSettings = self.settings.runtime
        rt_cfg = agent.runtime_config or {}
        meta = dict(run.metadata or {})
        meta.setdefault("ancestors", [])
        meta.setdefault("depth", 0)
        meta.setdefault("delegation_max_depth", int(rt_cfg.get("delegation_max_depth", 3)))
        meta.setdefault("delegation_max_children", int(rt_cfg.get("delegation_max_children", 5)))
        base_timeout = int(rt_cfg.get("timeout_seconds", rs.timeout_seconds))
        meta.setdefault("remaining_seconds", float(base_timeout))
        profile = self._resolve_agent_profile(agent)
        tools = profile["tools"]
        system_prompt = profile["system_prompt"]
        policy = None
        if self.policy_engine is not None:
            merged_agent = agent
            if profile["policy"]:
                merged = dict(agent.policy or {})
                merged.update(profile["policy"])
                merged_agent = AgentConfig(**{**agent.to_dict(), "policy": merged})
            policy = self.policy_engine.for_agent(merged_agent) if hasattr(self.policy_engine, "for_agent") else self.policy_engine
        return RunContext(
            approval_waiter=self._wait_for_approval,
            run_id=run.run_id,
            agent_id=run.agent_id,
            user_id=run.user_id,
            session_id=run.session_id,
            input_text=run.input or "",
            model=run.model or agent.model,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            cancellation=token,
            max_iterations=int(rt_cfg.get("max_iterations", rs.max_iterations)),
            max_tool_calls=int(rt_cfg.get("max_tool_calls", rs.max_tool_calls)),
            timeout_seconds=max(1, min(base_timeout, int(float(meta["remaining_seconds"])))),
            max_context_tokens=int(rt_cfg.get("max_context_tokens", 8192)),
            max_output_tokens=int(rt_cfg.get("max_output_tokens", 2048)),
            delegation_max_depth=meta["delegation_max_depth"],
            delegation_max_children=meta["delegation_max_children"],
            tool_timeout=float(self.settings.tools.default_timeout_seconds),
            memory_config=profile["memory_config"],
            knowledge_sources=profile["knowledge_sources"],
            contributions=profile.get("contributions") or [],
            metadata=meta,
            started_at=time.monotonic(),
        )

    @staticmethod
    def _budgeted_timeout(rt_cfg: dict[str, Any], meta: dict[str, Any], rs: RuntimeSettings) -> int:
        """Cap the child run timeout by the parent remaining budget (3.x-P5)."""
        timeout = int(rt_cfg.get("timeout_seconds", rs.timeout_seconds))
        remaining = meta.get("remaining_seconds")
        if remaining is not None:
            timeout = min(timeout, int(float(remaining)))
        return max(1, timeout)

    def _register_child(self, parent_run_id: str, max_children: int) -> bool:
        """Track child runs per parent; enforce the child count limit (3.x-P5)."""
        n = self._delegation_counts.get(parent_run_id, 0)
        if n >= max_children:
            return False
        self._delegation_counts[parent_run_id] = n + 1
        return True

    def _plugin_extensions(self, agent: AgentConfig) -> list[dict[str, Any]]:
        """Collect behavior extensions from the loaded plugins of the agent (3.x-P3).

        Agent composition: AgentProfile = base agent + plugin contributions.
        """
        if not agent.plugins or self.plugin_manager is None:
            return []
        exts = []
        for name in agent.plugins:
            state = self.plugin_manager.get(name)
            if state is not None and state.get("extension"):
                exts.append(state["extension"])
        return exts

    def _resolve_agent_profile(self, agent: AgentConfig) -> dict[str, Any]:
        """Merge plugin extensions into the agent profile (additive, no core change)."""
        tools = list(agent.tools or [])
        sys_prompt = agent.system_prompt
        knowledge = dict(agent.knowledge_config or {})
        memory = dict(agent.memory_config or {}) if agent.memory_config else None
        policy = dict(agent.policy or {}) if agent.policy else {}
        contributions: list[dict[str, Any]] = []
        contributions: list[dict[str, Any]] = []
        if agent.plugins and self.plugin_manager is not None:
            for name in agent.plugins:
                state = self.plugin_manager.get(name)
                if state is not None:
                    contributions.extend(state.get("contributions") or [])
                    ext = state.get("extension") or {}
                    contributions.extend(ext.get("contributions") or [])
        for ext in self._plugin_extensions(agent):
            for n in ext.get("tool_names") or []:
                if n and n not in tools:
                    tools.append(n)
            sp = ext.get("system_prompt")
            if sp:
                sys_prompt = (sys_prompt or "") + str(sp)
            ks = ext.get("knowledge_sources")
            if ks:
                knowledge["sources"] = list(set(knowledge.get("sources") or []) | set(ks))
            mem = ext.get("memory")
            if mem and isinstance(mem, dict):
                if memory is None:
                    memory = {}
                memory.update(mem)
            ext_pol = ext.get("policy")
            if ext_pol and isinstance(ext_pol, dict):
                policy.update(ext_pol)
        return {
            "tools": tools,
            "system_prompt": sys_prompt,
            "knowledge_config": knowledge,
            "knowledge_sources": list(knowledge.get("sources") or []),
            "memory_config": memory,
            "policy": policy,
            "contributions": contributions,
        }

    async def _fail(self, run_id: str, code: str, message: str, status: str) -> None:
        self.run_store.update(
            run_id, status=status, error=f"{code}: {message}", finished_at=datetime.datetime.utcnow(),
        )
        await self._publish(run_id, "run.failed", {"code": code, "error": message})
        self._cancellations.pop(run_id, None)
        self._running.discard(run_id)

    async def _emit_created(self, run: RunRecord) -> None:
        """Idempotent run.created emission (first caller wins, spec 6)."""
        if run.run_id in self._created_events:
            return
        self._created_events.add(run.run_id)
        await self._publish(run.run_id, "run.created", {
            "agent_id": run.agent_id, "input": (run.input or "")[:200], "user_id": run.user_id,
        })

    async def _publish(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(run_id, event_type, payload=payload)

    def _spawn(self, coro: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            task.add_done_callback(self._on_task_done)
        except RuntimeError:
            pass

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log_run(self.logger, 40, "background task failed", error=str(exc))

    @staticmethod
    def _error_code(error: str | None) -> str:
        if not error:
            return "RUNTIME_ERROR"
        for code in ("AGENT_LOOP_LIMIT", "AGENT_TOOL_CALL_LIMIT", "RUN_TIMEOUT",
                     "TOOL_TIMEOUT", "TOOL_DENIED", "POLICY_DENIED", "MODEL_UNAVAILABLE"):
            if code in error:
                return code
        return "RUNTIME_ERROR"
