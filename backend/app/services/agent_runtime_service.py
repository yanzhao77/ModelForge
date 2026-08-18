"""Singleton wiring for the 3.0 Agent Runtime (injected at app startup)."""
from __future__ import annotations

from typing import Any

from repositories.run_repository import SQLAlchemyRunStore
from runtime.events import EventBus
from runtime.metrics import MetricsRegistry
from runtime.runtime import AgentRuntime, default_provider_factory
from services.agent_store import DBAgentStore

_runtime: AgentRuntime | None = None


def init_agent_runtime(runtime: AgentRuntime) -> None:
    global _runtime
    _runtime = runtime


def get_agent_runtime() -> AgentRuntime | None:
    return _runtime


def build_agent_runtime(
    agent_engine: Any = None,
    provider_factory: Any = None,
    event_store: Any = None,
    policy_engine: Any = None,
    context_builder: Any = None,
    memory_provider: Any = None,
    knowledge_provider: Any = None,
    history_provider: Any = None,
    scheduler: Any = None,
    plugin_manager: Any = None,
) -> AgentRuntime:
    """Build the runtime with default adapters (spec 80).

    Provider factory defaults to Ollama; tests / deployments override it.
    Events persist to the DB (spec 30) via the event store unless one is injected.
    """
    from repositories.event_repository import SQLAlchemyEventStore
    from runtime.scheduler import Scheduler
    from runtime.tools import ToolExecutor, ToolRegistry
    from runtime.tools.builtin import register_builtin_tools
    from services.agent_engine import get_engine
    if scheduler is None:
        scheduler = Scheduler()
    run_store = SQLAlchemyRunStore()
    agent_store = DBAgentStore(agent_engine or get_engine())
    bus = EventBus(store=event_store or SQLAlchemyEventStore())
    registry = register_builtin_tools(ToolRegistry())
    if context_builder is None:
        from runtime.context.builder import ContextBuilder
        from runtime.kb_provider import KBKnowledgeProvider, SessionHistoryProvider
        from runtime.memory.providers import DBMemoryProvider
        context_builder = ContextBuilder(
            memory_provider=memory_provider or DBMemoryProvider(),
            knowledge_provider=knowledge_provider or KBKnowledgeProvider(),
            history_provider=history_provider or SessionHistoryProvider(),
        )
    runtime = AgentRuntime(
        run_store=run_store,
        agent_store=agent_store,
        event_bus=bus,
        tool_registry=registry,
        tool_runner=ToolExecutor(registry),
        provider_factory=provider_factory or default_provider_factory,
        context_builder=context_builder,
        memory_provider=memory_provider,
        knowledge_provider=knowledge_provider,
        history_provider=history_provider,
        policy_engine=policy_engine,
        metrics=MetricsRegistry(),
        scheduler=scheduler,
    )
    if scheduler is not None and runtime.scheduler is not None:
        runtime.scheduler.trigger = runtime._scheduler_trigger
    if plugin_manager is not None:
        runtime.plugin_manager = plugin_manager
    return runtime