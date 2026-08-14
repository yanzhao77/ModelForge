"""Phase 5: Context Engine tests - pipeline, budget, memory/knowledge/history (spec 68)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.context.builder import ContextBuilder
from runtime.run_context import RunContext
from runtime.cancellation import CancellationToken
from runtime.models import MockProvider


class FakeMemoryProvider:
    async def retrieve(self, user_id, query, top_k=3):
        return [{"value": "用户喜欢 Python", "key": "喜欢", "type": "preference"}]


class FakeKnowledgeProvider:
    def __init__(self, results=None):
        self.results = results or [{"text": "ModelForge 是本地 AI 平台", "source": "docs.md"}]
        self.calls = 0

    async def retrieve(self, query, top_k=3):
        self.calls += 1
        return self.results


class FakeHistoryProvider:
    async def load(self, session_id, limit=20):
        return [
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
        ]


def make_ctx(**kw):
    defaults = dict(
        run_id="r", agent_id="a", user_id=1, input_text="帮我看看项目",
        max_context_tokens=8192, timeout_seconds=60,
        cancellation=CancellationToken(),
    )
    defaults.update(kw)
    return RunContext(**defaults)


class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_basic_system_and_working(self):
        builder = ContextBuilder()
        ctx = make_ctx(system_prompt="你是助手")
        prompt = await builder.build(ctx, [{"role": "user", "content": "hi"}])
        assert prompt[0]["role"] == "system"
        assert prompt[0]["content"] == "你是助手"
        assert prompt[-1] == {"role": "user", "content": "hi"}

    @pytest.mark.asyncio
    async def test_default_system_prompt(self):
        builder = ContextBuilder()
        prompt = await builder.build(make_ctx(), [{"role": "user", "content": "x"}])
        assert "AI agent" in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_memory_injected(self):
        builder = ContextBuilder(memory_provider=FakeMemoryProvider())
        ctx = make_ctx(memory_config={"type": "user"})
        prompt = await builder.build(ctx, [{"role": "user", "content": "hi"}])
        assert "[用户记忆]" in prompt[0]["content"]
        assert "用户喜欢 Python" in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_memory_gated_by_config(self):
        builder = ContextBuilder(memory_provider=FakeMemoryProvider())
        prompt = await builder.build(make_ctx(), [{"role": "user", "content": "hi"}])
        assert "用户喜欢 Python" not in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_knowledge_injected_when_sources_declared(self):
        kb = FakeKnowledgeProvider()
        builder = ContextBuilder(knowledge_provider=kb)
        ctx = make_ctx(knowledge_sources=["docs"])
        prompt = await builder.build(ctx, [{"role": "user", "content": "hi"}])
        assert "[知识库资料]" in prompt[0]["content"]
        assert "ModelForge 是本地 AI 平台" in prompt[0]["content"]
        assert kb.calls == 1

    @pytest.mark.asyncio
    async def test_knowledge_not_queried_without_sources(self):
        kb = FakeKnowledgeProvider()
        builder = ContextBuilder(knowledge_provider=kb)
        prompt = await builder.build(make_ctx(), [{"role": "user", "content": "hi"}])
        assert kb.calls == 0
        assert "知识库" not in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_history_prepended(self):
        builder = ContextBuilder(history_provider=FakeHistoryProvider())
        ctx = make_ctx(session_id=5)
        prompt = await builder.build(ctx, [{"role": "user", "content": "now"}])
        roles = [m["role"] for m in prompt]
        assert roles == ["system", "user", "assistant", "user"]
        assert prompt[-1]["content"] == "now"

    @pytest.mark.asyncio
    async def test_budget_trims_old_history(self):
        builder = ContextBuilder()
        working = [{"role": "user", "content": "msg" + str(i) * 100} for i in range(10)]
        ctx = make_ctx(max_context_tokens=60)
        prompt = await builder.build(ctx, working)
        assert prompt[0]["role"] == "system"
        assert len(prompt) < len(working) + 1
        assert prompt[-1]["content"].startswith("msg9")

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        builder = ContextBuilder(
            memory_provider=FakeMemoryProvider(),
            knowledge_provider=FakeKnowledgeProvider(),
            history_provider=FakeHistoryProvider(),
        )
        ctx = make_ctx(
            system_prompt="SYS",
            session_id=1,
            memory_config={"type": "user"},
            knowledge_sources=["docs"],
        )
        prompt = await builder.build(ctx, [{"role": "user", "content": "q"}])
        assert prompt[0]["role"] == "system"
        assert "SYS" in prompt[0]["content"]
        assert "用户喜欢 Python" in prompt[0]["content"]
        assert "ModelForge 是本地 AI 平台" in prompt[0]["content"]
        assert len(prompt) >= 4


class TestRuntimeContext:
    @pytest.mark.asyncio
    async def test_engine_uses_context_builder(self):
        from models.records import AgentRun  # noqa: F401
        from core.database import init_db
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.runtime import AgentRuntime
        from runtime.tools import ToolRegistry, ToolExecutor
        from runtime.tools.builtin import register_builtin_tools
        from runtime.types import AgentConfig
        from services.agent_store import DBAgentStore
        init_db()
        seen_prompts = []

        async def capture(messages, tools=None, timeout=None):
            seen_prompts.append(list(messages))
            return MockProvider.final("context answer")

        builder = ContextBuilder(
            memory_provider=FakeMemoryProvider(),
            knowledge_provider=FakeKnowledgeProvider(),
        )
        registry = register_builtin_tools(ToolRegistry())
        rt = AgentRuntime(
            run_store=SQLAlchemyRunStore(),
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(),
            tool_registry=registry,
            tool_runner=ToolExecutor(registry),
            context_builder=builder,
            provider_factory=lambda m: MockProvider(callback=capture),
        )
        rt.create_agent(AgentConfig(
            name="ctxbot5", model="mock",
            system_prompt="AGENT SYS PROMPT",
            memory_config={"type": "user"},
            knowledge_config={"sources": ["docs"]},
        ))
        run = rt.create_run(agent_id="ctxbot5", input_text="问题", user_id=1)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        prompt = seen_prompts[-1]
        assert prompt[0]["role"] == "system"
        assert "AGENT SYS PROMPT" in prompt[0]["content"]
        assert "用户喜欢 Python" in prompt[0]["content"]
        assert "ModelForge 是本地 AI 平台" in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_history_provider_wired(self):
        from runtime.kb_provider import SessionHistoryProvider
        prov = SessionHistoryProvider()
        history = await prov.load(999999)
        assert history == []