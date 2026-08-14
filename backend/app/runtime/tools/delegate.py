from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

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

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Target agent name"},
                "task": {"type": "string", "description": "Task for the target agent"},
            },
            "required": ["agent_id", "task"],
        }

    async def execute(self, arguments: Dict[str, Any], context: Any = None) -> ToolResult:
        agent_id = str(arguments.get("agent_id", ""))
        task = str(arguments.get("task", ""))
        if not agent_id:
            return ToolResult.err("agent.delegate: agent_id required")
        if context is not None and getattr(context, "agent_id", None) == agent_id:
            return ToolResult.err("agent.delegate: cannot delegate to self")
        user_id = getattr(context, "user_id", None) if context is not None else None
        session_id = getattr(context, "session_id", None) if context is not None else None
        try:
            run = self._runtime.create_run(
                agent_id=agent_id,
                input_text=task,
                user_id=user_id,
                session_id=session_id,
                execute=True,
            )
        except Exception as e:
            return ToolResult.err(f"agent.delegate: {e}")
        # synchronous wait (spec 41 phase 1)
        deadline = time.monotonic() + 300.0
        status = None
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            try:
                run = self._runtime.get_run(run.run_id, user_id=user_id)
            except Exception:
                break
            status = run.status
            if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                break
        return ToolResult.ok(
            f"[delegated {agent_id} -> {status or str(None)}] {run.output or str(None)}",
            delegated_run_id=run.run_id, delegated_status=status,
        )