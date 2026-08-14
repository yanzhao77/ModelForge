"""3.x-P4 tests: ContextContributor protocol + SkillPlugin (audit §9.3 / §16.3)."""
import os
import sys
import tempfile

_tmp_db = tempfile.mkdtemp(prefix="mf_p4_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from runtime.context.contributor import ContextContributor, ContextSegment
from runtime.context.builder import ContextBuilder
from runtime.run_context import RunContext


def make_ctx(**kw):
    defaults = dict(
        run_id="r", agent_id="a", user_id=1, input_text="hi",
        max_context_tokens=8192, timeout_seconds=60,
    )
    defaults.update(kw)
    return RunContext(**defaults)


class StaticContributor:
    """Duck-typed ContextContributor."""

    name = "static"

    def contribute(self, ctx):
        return [ContextSegment(content="静态技能说明", section="skill", priority=10)]


class TestContextContributor:
    @pytest.mark.asyncio
    async def test_protocol_runtime_checkable(self):
        assert isinstance(StaticContributor(), ContextContributor)

    @pytest.mark.asyncio
    async def test_segment_roundtrip(self):
        seg = ContextSegment(content="x", section="skill", priority=7)
        seg2 = ContextSegment.from_dict(seg.to_dict())
        assert seg2.content == "x"
        assert seg2.priority == 7

    @pytest.mark.asyncio
    async def test_builder_injects_contributor(self):
        builder = ContextBuilder(contributors=[StaticContributor()])
        prompt = await builder.build(make_ctx(), [{"role": "user", "content": "hi"}])
        assert "静态技能说明" in prompt[0]["content"]
        assert "[技能]" in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_ctx_contributions_injected(self):
        builder = ContextBuilder()
        ctx = make_ctx(contributions=[
            {"content": "插件贡献A", "section": "skill", "priority": 5},
            {"content": "插件贡献B", "section": "instruction", "priority": 90},
        ])
        prompt = await builder.build(ctx, [{"role": "user", "content": "hi"}])
        assert "插件贡献A" in prompt[0]["content"]
        assert "插件贡献B" in prompt[0]["content"]

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        builder = ContextBuilder(contributors=[StaticContributor()])
        ctx = make_ctx(contributions=[{"content": "LOW", "section": "skill", "priority": 100}])
        prompt = await builder.build(ctx, [{"role": "user", "content": "hi"}])
        content = prompt[0]["content"]
        assert content.index("静态技能说明") < content.index("LOW"), "priority 10 before 100"


class TestSkillPlugin:
    SKILL_ENTRY = """
from runtime.context.contributor import ContextSegment


def contribute(ctx):
    return [
        ContextSegment(content="技能：擅长项目分析", section="skill", priority=20),
        ContextSegment(content="技能：擅长代码审查", section="skill", priority=30),
    ]
"""

    def _setup(self):
        tmp = tempfile.mkdtemp(prefix="mf_skill_")
        pdir = os.path.join(tmp, "skill.analyze")
        os.makedirs(pdir)
        with open(os.path.join(pdir, "plugin.yaml"), "w", encoding="utf-8") as f:
            f.write("name: skill.analyze\nversion: 1.0.0\ntype: skill\nentry: skill_plugin.py\n")
        with open(os.path.join(pdir, "skill_plugin.py"), "w", encoding="utf-8") as f:
            f.write(self.SKILL_ENTRY)
        from models.records import AgentRun  # noqa: F401
        from core.database import init_db
        from repositories.event_repository import SQLAlchemyEventStore
        from repositories.run_repository import SQLAlchemyRunStore
        from runtime.events import EventBus
        from runtime.plugins import PluginManager, PluginManifest
        from runtime.runtime import AgentRuntime
        from runtime.tools import ToolExecutor, ToolRegistry
        from runtime.tools.builtin import register_builtin_tools
        from services.agent_store import DBAgentStore
        init_db()
        registry = register_builtin_tools(ToolRegistry())
        rt = AgentRuntime(
            run_store=SQLAlchemyRunStore(),
            agent_store=DBAgentStore(engine=None),
            event_bus=EventBus(store=SQLAlchemyEventStore()),
            tool_registry=registry,
            tool_runner=ToolExecutor(registry),
            context_builder=ContextBuilder(),
            provider_factory=lambda m: None,
        )
        rt.plugin_manager = PluginManager(rt, plugins_dir=tmp, event_bus=rt.event_bus)
        manifest = PluginManifest.from_file(os.path.join(pdir, "plugin.yaml"))
        rt.plugin_manager.load(manifest)
        return rt

    @pytest.mark.asyncio
    async def test_skill_contributions_in_run(self):
        rt = self._setup()
        from runtime.models import MockProvider
        from runtime.types import AgentConfig
        seen = []
        async def capture(messages, tools=None, timeout=None):
            seen.append(list(messages))
            return MockProvider.final("skill answer")
        rt.create_agent(AgentConfig(name="skbot", model="mock", tools=[], plugins=["skill.analyze"]))
        rt.provider_factory = lambda m: MockProvider(callback=capture)
        run = rt.create_run(agent_id="skbot", input_text="analyze", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        stored = rt.get_run(run.run_id, user_id=1)
        assert stored.status == "COMPLETED"
        system = seen[-1][0]["content"]
        assert "擅长项目分析" in system
        assert "擅长代码审查" in system
        assert "[技能]" in system

    @pytest.mark.asyncio
    async def test_skill_without_plugin_not_injected(self):
        rt = self._setup()
        from runtime.models import MockProvider
        from runtime.types import AgentConfig
        seen = []
        async def capture(messages, tools=None, timeout=None):
            seen.append(list(messages))
            return MockProvider.final("plain")
        rt.create_agent(AgentConfig(name="plainbot", model="mock", tools=[]))
        rt.provider_factory = lambda m: MockProvider(callback=capture)
        run = rt.create_run(agent_id="plainbot", input_text="hi", user_id=1, execute=False)
        await rt.execute_run(run.run_id)
        system = seen[-1][0]["content"]
        assert "擅长项目分析" not in system