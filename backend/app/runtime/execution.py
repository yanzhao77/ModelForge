from __future__ import annotations

import asyncio
import time
from typing import Any

from .errors import (
    AgentLoopLimitError,
    AgentToolCallLimitError,
    RunCancelledError,
    RuntimeError,
    RunTimeoutError,
    ToolDeniedError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from .logging import get_logger, log_run
from .models.base import ModelProvider
from .run_context import RunContext, ToolExecutionContext
from .state import AgentState


class ExecutionEngine:
    """Executes the agent loop (spec 20):

    Create Run -> Load Agent -> Build Context -> Invoke LLM -> Tool Call?
    (No -> Finish) (Yes -> Execute Tool -> Emit Event -> Update State -> loop).

    LangGraph remains available as the 2.1 engine (services.agent_engine);
    this engine is the 3.0 default and does not depend on LangGraph (spec 21).
    """

    def __init__(
        self,
        *,
        event_bus: Any | None = None,
        tool_runner: Any | None = None,
        context_builder: Any | None = None,
        metrics: Any | None = None,
        logger: Any | None = None,
    ):
        self.event_bus = event_bus
        self.tool_runner = tool_runner
        self.context_builder = context_builder
        self.metrics = metrics
        self.logger = logger or get_logger()

    # ---- public ----
    async def execute(
        self,
        ctx: RunContext,
        provider: ModelProvider,
    ) -> dict[str, Any]:
        """Run the loop; never raises - returns an outcome dict (spec 20)."""
        state = AgentState(run_id=ctx.run_id)
        # system prompt is assembled by the ContextEngine when one is configured;
        # otherwise keep it inline for plain runs (spec 68).
        if self.context_builder is None and ctx.system_prompt:
            state.messages.append({"role": "system", "content": ctx.system_prompt})
        state.messages.append({"role": "user", "content": ctx.input_text or ""})

        token_usage: dict[str, int] = {}
        final_output = ""
        outcome_status = "COMPLETED"
        error: str | None = None
        started = time.monotonic()

        try:
            while True:
                self._check(ctx, state)
                state.iteration += 1
                if state.iteration > ctx.max_iterations:
                    raise AgentLoopLimitError()

                prompt_messages = state.messages
                if self.context_builder is not None:
                    prompt_messages = await self.context_builder.build(ctx, state.messages, state.iteration)

                tool_schemas = self._tool_schemas(ctx)
                await self._emit(ctx, "model.request.started", {"iteration": state.iteration})
                try:
                    llm_timeout = max(1.0, min(ctx.timeout_seconds or 600, 120.0))
                    result = await asyncio.wait_for(
                        provider.chat(prompt_messages, tools=tool_schemas),
                        timeout=llm_timeout,
                    )
                except asyncio.TimeoutError:
                    raise RunTimeoutError()
                except RunCancelledError:
                    raise
                except Exception as e:
                    raise RuntimeError(message=f"Model request failed: {e}")

                for k, v in (result.usage or {}).items():
                    token_usage[k] = token_usage.get(k, 0) + int(v or 0)
                if self.metrics is not None:
                    self.metrics.on_llm_call(result.total_tokens)
                await self._emit(ctx, "model.request.completed", {
                    "usage": result.usage,
                    "model": result.model,
                })

                # record the assistant turn so providers see the full history
                state.messages.append({
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": [t.to_dict() for t in result.tool_calls] if result.tool_calls else None,
                })

                if not result.tool_calls:
                    final_output = result.content or ""
                    await self._emit(ctx, "agent.response", {"content": final_output})
                    break

                for tc in result.tool_calls:
                    self._check(ctx, state)
                    state.tool_calls.append(tc.to_dict())
                    if state.tool_call_count + 1 > ctx.max_tool_calls:
                        raise AgentToolCallLimitError()
                    state.tool_call_count += 1
                    try:
                        await self._policy_gate(ctx, tc.name)
                    except ToolDeniedError as e:
                        await self._emit(ctx, "tool.call.failed", {
                            "tool": tc.name, "code": "TOOL_DENIED", "error": e.message,
                        })
                        state.messages.append({
                            "role": "tool",
                            "content": f"Error: {e.message} (denied by policy)",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                        })
                        continue

                    tctx = ToolExecutionContext(
                        user_id=ctx.user_id,
                        agent_id=ctx.agent_id,
                        run_id=ctx.run_id,
                        session_id=ctx.session_id,
                        timeout=ctx.tool_timeout,
                        policy=ctx.policy,
                        cancellation_token=ctx.cancellation,
                        metadata={**(getattr(ctx, "metadata", {}) or {}), "tool": tc.name},
                    )
                    await self._emit(ctx, "tool.call.started", {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "call_id": tc.id,
                    })
                    t0 = time.monotonic()
                    tool_ok = True
                    tool_output = ""
                    try:
                        tool_output = await self.tool_runner.run(tc.name, tc.arguments, tctx)
                    except ToolTimeoutError:
                        tool_ok = False
                        tool_output = "Error: tool timed out"
                    except ToolNotFoundError:
                        tool_ok = False
                        tool_output = "Error: tool not found"
                    except RunCancelledError:
                        raise
                    except Exception as e:
                        tool_ok = False
                        tool_output = "Error: " + str(e)
                    duration = time.monotonic() - t0
                    if self.metrics is not None:
                        self.metrics.on_tool_call(duration)
                    await self._emit(
                        ctx,
                        "tool.call.completed" if tool_ok else "tool.call.failed",
                        {"tool": tc.name, "duration": round(duration, 3), "output": tool_output[:500]},
                    )
                    state.messages.append({
                        "role": "tool",
                        "content": tool_output,
                        "tool_call_id": tc.id,
                        "name": tc.name,
                    })
                    state.variables["last_tool_output"] = tool_output
        except RunCancelledError:
            outcome_status = "CANCELLED"
            error = "cancelled"
        except RunTimeoutError:
            outcome_status = "TIMEOUT"
            error = "run timeout"
        except (AgentLoopLimitError, AgentToolCallLimitError) as e:
            outcome_status = "FAILED"
            error = f"{e.code}: {e.message}"
        except Exception as e:
            outcome_status = "FAILED"
            error = str(e)

        state.status = outcome_status
        duration = time.monotonic() - started
        log_run(self.logger, 20, "run finished", run_id=ctx.run_id,
                agent_id=ctx.agent_id, status=outcome_status, duration_ms=round(duration * 1000))
        return {
            "status": outcome_status,
            "output": final_output,
            "error": error,
            "iteration": state.iteration,
            "tool_call_count": state.tool_call_count,
            "token_usage": token_usage,
            "messages": state.messages,
            "duration": duration,
        }

    # ---- internals ----
    def _check(self, ctx: RunContext, state: AgentState) -> None:
        if ctx.cancellation is not None:
            ctx.cancellation.check()
        ctx.check_timeout()

    def _tool_schemas(self, ctx: RunContext) -> list | None:
        if self.tool_runner is None or not ctx.tools:
            return None
        schemas = []
        for name in ctx.tools:
            schema = self.tool_runner.schema(name) if hasattr(self.tool_runner, "schema") else None
            if schema:
                schemas.append(schema)
        return schemas or None

    async def _policy_gate(self, ctx: RunContext, tool_name: str) -> None:
        """Policy check + optional human gate before tool execution (spec 69 / 32)."""
        policy = getattr(ctx, "policy", None)
        if policy is None or not hasattr(policy, "check_tool"):
            return
        tool = None
        runner = self.tool_runner
        if runner is not None and hasattr(runner, "registry"):
            tool = runner.registry.get(tool_name)
        decision = policy.check_tool(ctx, tool_name, tool)
        if not decision.allowed:
            raise ToolDeniedError(decision.reason)
        if decision.require_approval:
            granted = await self._wait_for_approval(ctx, tool_name)
            if not granted:
                raise ToolDeniedError("human approval denied")

    async def _wait_for_approval(self, ctx: RunContext, tool_name: str) -> bool:
        """Wait for a human approve/reject decision (spec 32). No waiter -> deny."""
        waiter = getattr(ctx, "approval_waiter", None)
        if waiter is None:
            return False
        return await waiter(ctx, tool_name)

    async def _emit(self, ctx: RunContext, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(
                ctx.run_id, event_type, payload=payload, session_id=ctx.session_id,
            )