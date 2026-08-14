"""Singleton wiring for the 3.0 Agent Runtime (injected at app startup)."""
from __future__ import annotations

from typing import Any, Optional

from repositories.run_repository import SQLAlchemyRunStore
from runtime.events import EventBus
from runtime.metrics import MetricsRegistry
from runtime.runtime import AgentRuntime, default_provider_factory
from runtime.tools import LegacyToolRunner
from services.agent_store import DBAgentStore

_runtime: Optional[AgentRuntime] = None


def init_agent_runtime(runtime: AgentRuntime) -> None:
    global _runtime
    _runtime = runtime


def get_agent_runtime() -> Optional[AgentRuntime]:
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
) -> AgentRuntime:
    """Build the runtime with default adapters (spec 80).

    Provider factory defaults to Ollama; tests / deployments override it.
    Events persist to the DB (spec 30) via the event store unless one is injected.
    """
    from repositories.event_repository import SQLAlchemyEventStore
    from services.agent_engine import get_engine
    run_store = SQLAlchemyRunStore()
    agent_store = DBAgentStore(agent_engine or get_engine())
    bus = EventBus(store=event_store or SQLAlchemyEventStore())
    runtime = AgentRuntime(
        run_store=run_store,
        agent_store=agent_store,
        event_bus=bus,
        tool_runner=LegacyToolRunner(),
        provider_factory=provider_factory or default_provider_factory,
        context_builder=context_builder,
        memory_provider=memory_provider,
        knowledge_provider=knowledge_provider,
        history_provider=history_provider,
        policy_engine=policy_engine,
        metrics=MetricsRegistry(),
        scheduler=scheduler,
    )
    return runtime