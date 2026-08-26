from __future__ import annotations

from typing import Any

from ..run_context import RunContext


class ContextBuilder:
    """Builds the final LLM context (spec 16 pipeline):

    User Input -> System Prompt -> Session History -> Memory Retrieval ->
    Knowledge Retrieval -> Tool State -> Context Budget -> Final Prompt.
    """

    def __init__(
        self,
        *,
        memory_provider: Any = None,
        knowledge_provider: Any = None,
        history_provider: Any = None,
        contributors: list | None = None,
    ):
        self.memory_provider = memory_provider
        self.knowledge_provider = knowledge_provider
        self.history_provider = history_provider
        self.contributors = list(contributors or [])

    async def build(
        self,
        ctx: RunContext,
        working_messages: list[dict[str, Any]],
        iteration: int = 0,
    ) -> list[dict[str, Any]]:
        """Return the prompt message list for the current LLM call."""
        system = ctx.system_prompt or "You are a helpful AI agent running tasks for the user."
        extras: list[str] = []

        # memory retrieval (spec 17)
        memories = await self._retrieve_memories(ctx)
        if memories:
            extras.append("[用户记忆]")
            extras.extend(f"- {m}" for m in memories)

        # knowledge retrieval (spec 18) - only when the agent declared sources
        knowledge = await self._retrieve_knowledge(ctx)
        if knowledge:
            extras.append("[知识库资料]")
            extras.extend(f"- [{k.get('source', '?')}] {k.get('text', '')}" for k in knowledge)

        # skill / instruction contributions (3.x-P4: plugins inject without
        # touching builder core - audit §9.3)
        segments = self._collect_contributions(ctx)
        if segments:
            extras.append("[技能]")
            extras.extend(f"- {seg.get('content', '')}" for seg in segments)

        if extras:
            system = system + "\n\n" + "\n".join(extras)

        prompt: list[dict[str, Any]] = [{"role": "system", "content": system}]

        # session history (spec 5: Session is long-term context)
        if self.history_provider is not None and ctx.session_id is not None:
            try:
                history = await self.history_provider.load(ctx.session_id, limit=20)
                prompt.extend(history)
            except Exception:
                pass

        prompt.extend(working_messages)
        return self._trim(prompt, ctx.max_context_tokens)

    def _collect_contributions(self, ctx: RunContext) -> list[dict[str, Any]]:
        """Merge run-level contributions (from skill plugins / agent plugins) with
        builder-registered contributors, sorted by priority."""
        items = list(getattr(ctx, "contributions", None) or [])
        for contributor in self.contributors:
            try:
                segments = contributor.contribute(ctx) or []
                items.extend(getattr(s, "to_dict", lambda: s)() if hasattr(s, "to_dict") else s for s in segments)
            except Exception:
                continue
        return sorted(items, key=lambda x: int(x.get("priority", 50)))

    async def _retrieve_memories(self, ctx: RunContext) -> list[str]:
        if self.memory_provider is None or ctx.user_id is None:
            return []
        if not ctx.memory_config:
            return []
        try:
            items = await self.memory_provider.retrieve(
                ctx.user_id, ctx.input_text, top_k=3,
            )
            return [str(i.get("value", "")) for i in items if i.get("value")]
        except Exception:
            return []

    async def _retrieve_knowledge(self, ctx: RunContext) -> list[dict[str, Any]]:
        if self.knowledge_provider is None:
            return []
        binding = dict(ctx.knowledge_binding or {})
        if binding.get("mode") == "disabled" or not ctx.knowledge_sources:
            return []
        try:
            return await self.knowledge_provider.retrieve(
                ctx.input_text, top_k=3, user_id=ctx.user_id, knowledge_binding=binding,
            )
        except Exception:
            return []

    @staticmethod
    def _rough_tokens(msg: dict[str, Any]) -> int:
        text = str(msg.get("content", "") or "")
        return max(1, len(text) // 4)

    def _trim(
        self,
        messages: list[dict[str, Any]],
        budget: int,
    ) -> list[dict[str, Any]]:
        """Context budget (spec 16): keep system + recent messages, drop oldest.

        Tool results and recent turns are preserved; only mid-history is dropped.
        """
        if budget <= 0:
            return messages
        total = sum(self._rough_tokens(m) for m in messages)
        if total <= budget:
            return messages
        if len(messages) <= 2:
            return messages
        out = list(messages)
        while len(out) > 7 and sum(self._rough_tokens(m) for m in out) > budget:
            for idx, m in enumerate(out):
                if m.get("role") != "system" and idx != len(out) - 1:
                    out.pop(idx)
                    break
            else:
                break
        return out
