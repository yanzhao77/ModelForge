from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from .cancellation import CancellationToken
from .context import RunContext, ToolExecutionContext
from .errors import (
    AgentLoopLimitError, AgentToolCallLimitError, RunCancelledError,
    RunTimeoutError, RuntimeError, ToolNotFoundError, ToolTimeoutError,
)
from .logging import get_logger, log_run
from .models.base import ModelProvider
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
        event_bus: Optional[Any] = None,
        tool_runner: Optional[Any] = None,
        context_builder: Optional[Any] = None,
        metrics: Optional[Any] = None,
        logger: Optional[Any] = None,
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
    ) -> Dict[str, Any]:
        """Run the loop; never raises - returns an outcome dict (spec 20)."""
        state = AgentState(run_id=ctx.run_id)
        if ctx.system_prompt:
            state.messages.append({"role": "system", "content": ctx.system_prompt})
        state.messages.append({"role": "user", "content": ctx.input_text or ""})

        token_usage: Dict[str, int] = {}
        final_output = ""
        outcome_status = "COMPLETED"
        error: Optional[str] = None
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
                    llm_timeout = max(10.0, min(ctx.timeout_seconds or 600, 120.0))
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
                    await self._policy_gate(ctx, tc.name)

                    tctx = ToolExecutionContext(
                        user_id=ctx.user_id,
                        agent_id=ctx.agent_id,
                        run_id=ctx.run_id,
                        session_id=ctx.session_id,
                        permissions=getattr(ctx.policy, "permissions", []) if ctx.policy else [],
                        timeout=ctx.tool_timeout,
                        cancellation_token=ctx.cancellation,
                        metadata={"tool": tc.name},
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

    def _tool_schemas(self, ctx: RunContext) -> Optional[list]:
        if self.tool_runner is None or not ctx.tools:
            return None
        schemas = []
        for name in ctx.tools:
            schema = self.tool_runner.schema(name) if hasattr(self.tool_runner, "schema") else None
            if schema:
                schemas.append(schema)
        return schemas or None

    async def _policy_gate(self, ctx: RunContext, tool_name: str) -> None:
        """Phase 6 hook: policy check before tool execution."""
        policy = getattr(ctx, "policy", None)
        if policy is not None and hasattr(policy, "check_tool"):
            await policy.check_tool(ctx, tool_name)

    async def _emit(self, ctx: RunContext, event_type: str, payload: Dict[str, Any]) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(
                ctx.run_id, event_type, payload=payload, session_id=ctx.session_id,
            )