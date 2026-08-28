from __future__ import annotations

import asyncio
import time
from typing import Any

from ..tools.base import Tool, ToolResult


class DelegateTool(Tool):
    """agent.delegate - run another agent and wait for its result (spec 40 / 41 / 73).

    The delegated run is a real nested AgentRun created through the runtime.
    Phase 1 waits synchronously; async delegation comes later.
    """

    name = "agent.delegate"
    description = "Delegate a task to another agent and wait for its result"
    version = "1.0.0"
    source = "builtin"
    timeout = 300.0
    permissions = []  # allowed by default; policy.allowed_tools still applies

    def __init__(self, runtime: Any):
        self._runtime = runtime
        self.aliases = []

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Target agent name"},
                "task": {"type": "string", "description": "Task for the target agent"},
            },
            "required": ["agent_id", "task"],
        }

    async def execute(self, arguments: dict[str, Any], context: Any = None) -> ToolResult:
        agent_id = str(arguments.get("agent_id", ""))
        task = str(arguments.get("task", ""))
        if not agent_id:
            return ToolResult.err("agent.delegate: agent_id required")
        meta = (getattr(context, "metadata", None) or {}) if context is not None else {}
        my_agent = getattr(context, "agent_id", None) if context is not None else None
        if my_agent == agent_id:
            return ToolResult.err("agent.delegate: cannot delegate to self")
        user_id = getattr(context, "user_id", None) if context is not None else None
        session_id = getattr(context, "session_id", None) if context is not None else None
        parent_run_id = getattr(context, "run_id", None) if context is not None else None

        # 3.x-P5 guards: depth / cycle / child count / budget
        ancestors = list(meta.get("ancestors") or [])
        if my_agent:
            ancestors = ancestors + [my_agent]
        if agent_id in ancestors:
            return ToolResult.err("agent.delegate: delegation cycle detected")
        depth = int(meta.get("depth") or 0)
        max_depth = int(meta.get("delegation_max_depth") or 3)
        if depth + 1 > max_depth:
            return ToolResult.err(f"agent.delegate: max delegation depth {max_depth} exceeded")
        max_children = int(meta.get("delegation_max_children") or 5)
        if parent_run_id and not self._runtime._register_child(parent_run_id, max_children):
            return ToolResult.err(f"agent.delegate: max child runs {max_children} exceeded")
        remaining = float(meta.get("remaining_seconds") or 600.0)

        child_meta = {
            "ancestors": ancestors,
            "depth": depth + 1,
            "delegation_max_depth": max_depth,
            "delegation_max_children": max_children,
            "remaining_seconds": max(1.0, remaining),
        }
        try:
            run = self._runtime.create_run(
                agent_id=agent_id,
                input_text=task,
                user_id=user_id,
                session_id=session_id,
                parent_run_id=parent_run_id,
                metadata=child_meta,
                execute=True,
            )
        except Exception as e:
            return ToolResult.err(f"agent.delegate: {e}")
        # synchronous wait (spec 41 phase 1), bounded by the parent remaining budget
        deadline = time.monotonic() + min(remaining, 300.0)
        status = None
        token = getattr(context, "cancellation_token", None) if context is not None else None
        while time.monotonic() < deadline:
            if token is not None and token.cancelled:
                return ToolResult.err("agent.delegate: parent run cancelled while delegating")
            await asyncio.sleep(0.05)
            try:
                run = self._runtime.get_run(run.run_id, user_id=user_id)
            except Exception:
                break
            status = run.status
            if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                break
        if status not in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
            timed_out = await self._runtime.timeout_run(
                run.run_id,
                user_id=user_id,
                reason="delegation budget exhausted",
            )
            run = timed_out
            status = timed_out.status
        return ToolResult.ok(
            f"[delegated {agent_id} -> {status or str(None)}] {run.output or str(None)}",
            delegated_run_id=run.run_id, delegated_status=status,
            parent_run_id=parent_run_id,
        )