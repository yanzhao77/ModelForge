"""Workflow execution engine (V1.5).

A workflow is a declarative graph of nodes. Supported node types are
``input``, ``output``, ``llm``, ``agent``, ``tool``, ``condition``, ``loop``,
``parallel`` and ``approval``, which together cover sequential flow, parallel
branches, conditions, loops, per-node retry, per-node timeout and
human-in-the-loop pauses.

Node arguments, prompts and outputs support ``{{path}}`` templates resolved
against ``{input, variables, nodes}``. Control-flow expressions are evaluated
with a small AST whitelist — never ``eval`` over arbitrary input.
"""

from __future__ import annotations

import ast
import asyncio
import datetime
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

NODE_TYPES = (
    "input",
    "output",
    "llm",
    "agent",
    "tool",
    "condition",
    "loop",
    "parallel",
    "approval",
)

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}

_TEMPLATE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


class WorkflowError(RuntimeError):
    """Stable workflow failure with an execution-phase code."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class WorkflowPaused(Exception):
    """Raised internally when an approval node suspends the run."""


_ALLOWED_CALLS = {"len": len, "str": str, "int": int, "float": float, "bool": bool, "abs": abs}
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Name, ast.Load, ast.Constant, ast.Call, ast.Attribute, ast.Subscript,
    ast.List, ast.Tuple,
)


class _ExpressionValidator(ast.NodeVisitor):
    """Reject anything outside the control-flow expression subset."""

    def generic_visit(self, node):  # noqa: N802 - ast API
        if not isinstance(node, _ALLOWED_NODES):
            raise WorkflowError(
                "WORKFLOW_EXPRESSION_INVALID",
                f"unsupported expression element: {type(node).__name__}",
            )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise WorkflowError("WORKFLOW_EXPRESSION_INVALID", "dunder names are not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise WorkflowError("WORKFLOW_EXPRESSION_INVALID", "dunder attributes are not allowed")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
                raise WorkflowError(
                    "WORKFLOW_EXPRESSION_INVALID",
                    "only len/str/int/float/bool/abs may be called",
                )
        super().generic_visit(node)


class _AttributeToItem(ast.NodeTransformer):
    """Rewrite ``a.b`` into ``a['b']``.

    Workflow data is nested dicts, so attribute syntax is the readable way to
    reach it. Rewriting before evaluation means no object attribute is ever
    touched — the dunder guard becomes a structural property rather than a
    check the evaluator has to remember.
    """

    def visit_Attribute(self, node):  # noqa: N802 - ast API
        self.generic_visit(node)
        return ast.Subscript(
            value=node.value,
            slice=ast.Constant(value=node.attr),
            ctx=ast.Load(),
        )


def evaluate_expression(expression: str, namespace: dict) -> Any:
    """Evaluate a control-flow expression against a restricted namespace."""
    if not expression or not str(expression).strip():
        return False
    try:
        tree = ast.parse(str(expression), mode="eval")
    except SyntaxError as exc:
        raise WorkflowError("WORKFLOW_EXPRESSION_INVALID", f"cannot parse expression: {exc.msg}") from exc
    _ExpressionValidator().visit(tree)
    tree = _AttributeToItem().visit(tree)
    ast.fix_missing_locations(tree)
    env = {**_ALLOWED_CALLS, **namespace}
    try:
        return eval(compile(tree, "<workflow-expression>", "eval"), {"__builtins__": {}}, env)  # noqa: S307
    except WorkflowError:
        raise
    except Exception as exc:
        raise WorkflowError("WORKFLOW_EXPRESSION_FAILED", f"expression failed: {type(exc).__name__}") from exc


def _lookup(path: str, namespace: dict) -> Any:
    current: Any = namespace
    for part in path.strip().split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current


def render_template(value: Any, namespace: dict) -> Any:
    """Resolve ``{{path}}`` placeholders, preserving non-string values whole."""
    if isinstance(value, str):
        exact = _TEMPLATE.fullmatch(value.strip())
        if exact:
            return _lookup(exact.group(1), namespace)
        return _TEMPLATE.sub(lambda match: str(_lookup(match.group(1), namespace) or ""), value)
    if isinstance(value, dict):
        return {key: render_template(item, namespace) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, namespace) for item in value]
    return value


def validate_definition(definition: dict) -> list[str]:
    """Return the list of structural problems (empty means valid)."""
    problems: list[str] = []
    if not isinstance(definition, dict):
        return ["definition must be an object"]
    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["definition.nodes must be a non-empty list"]
    ids: list[str] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            problems.append(f"node #{index} must be an object")
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            problems.append(f"node #{index} needs a string id")
            continue
        ids.append(node_id)
        if node.get("type") not in NODE_TYPES:
            problems.append(f"node {node_id} has unsupported type {node.get('type')!r}")
    duplicates = {node_id for node_id in ids if ids.count(node_id) > 1}
    if duplicates:
        problems.append("duplicate node ids: " + ", ".join(sorted(duplicates)))
    known = set(ids)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        targets: list[str] = []
        for key in ("next", "true_next", "false_next"):
            value = node.get(key)
            if isinstance(value, str):
                targets.append(value)
            elif isinstance(value, list):
                targets.extend(str(item) for item in value)
        for key in ("body",):
            value = node.get(key)
            if isinstance(value, list):
                targets.extend(str(item) for item in value)
        branches = node.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, list):
                    targets.extend(str(item) for item in branch)
        for target in targets:
            if target not in known:
                problems.append(f"node {node_id} points at unknown node {target}")
    for edge in definition.get("edges") or []:
        if not isinstance(edge, dict):
            problems.append("edges must be objects")
            continue
        if edge.get("from") not in known or edge.get("to") not in known:
            problems.append(f"edge {edge.get('from')} -> {edge.get('to')} references an unknown node")
    if not any(node.get("type") == "input" for node in nodes if isinstance(node, dict)):
        problems.append("definition needs an input node")
    return problems


@dataclass
class NodeState:
    node_id: str
    status: str = "PENDING"
    output: Any = None
    error: str | None = None
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "events": self.events,
        }


@dataclass
class WorkflowExecution:
    """Mutable state of one run."""

    run_id: str
    definition: dict
    input: dict
    variables: dict
    nodes: dict[str, NodeState] = field(default_factory=dict)
    output: Any = None
    current_node: str | None = None

    def namespace(self) -> dict:
        return {
            "input": self.input,
            "variables": self.variables,
            "nodes": {node_id: state.to_dict() for node_id, state in self.nodes.items()},
            "output": self.output,
        }

    def to_state(self) -> dict:
        return {
            "current_node": self.current_node,
            "variables": self.variables,
            "output": self.output,
            "nodes": {node_id: state.to_dict() for node_id, state in self.nodes.items()},
        }


def _preview(value: Any, limit: int = 500) -> Any:
    """Trim node output for events/trace without losing its JSON shape."""
    if isinstance(value, str):
        return value[:limit]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)[:limit]
    return text[:limit]


def new_run_id() -> str:
    return uuid.uuid4().hex


class WorkflowEngine:
    """Interprets a workflow definition.

    Collaborators are injected so the engine stays testable and never reaches
    for a global: the runtime manager for ``llm`` nodes, the Agent runtime for
    ``agent`` nodes and the Tool registry/executor for ``tool`` nodes.
    """

    max_steps = 200

    def __init__(
        self,
        *,
        emit: Callable[[str, dict], Awaitable[None]] | None = None,
        runtime_manager=None,
        agent_runtime=None,
        tool_registry=None,
        tool_runner=None,
        run_store=None,
        node_timeout_seconds: float = 300.0,
    ):
        self._emit_cb = emit
        self._runtime_manager = runtime_manager
        self._agent_runtime = agent_runtime
        self._tool_registry = tool_registry
        self._tool_runner = tool_runner
        self._run_store = run_store
        self.node_timeout_seconds = node_timeout_seconds

    async def _emit(self, event_type: str, payload: dict) -> None:
        if self._emit_cb is not None:
            await self._emit_cb(event_type, payload)

    def _nodes(self, execution: WorkflowExecution) -> dict[str, dict]:
        return {
            str(node.get("id")): node
            for node in execution.definition.get("nodes") or []
            if isinstance(node, dict)
        }

    def _entry(self, execution: WorkflowExecution) -> str:
        explicit = execution.definition.get("entry")
        if isinstance(explicit, str) and explicit:
            return explicit
        for node in execution.definition.get("nodes") or []:
            if isinstance(node, dict) and node.get("type") == "input":
                return str(node.get("id"))
        raise WorkflowError("WORKFLOW_DEFINITION_INVALID", "workflow has no input node")

    @staticmethod
    def _next_nodes(node: dict, *, branch: str | None = None) -> list[str]:
        key = {"true": "true_next", "false": "false_next"}.get(branch or "", "next")
        value = node.get(key)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    async def execute(self, execution: WorkflowExecution, *, start_at: str | None = None) -> WorkflowExecution:
        """Run the graph to completion (or until an approval pauses it)."""
        nodes = self._nodes(execution)
        current = start_at or self._entry(execution)
        steps = 0
        while current:
            steps += 1
            if steps > self.max_steps:
                raise WorkflowError("WORKFLOW_STEP_LIMIT", f"workflow exceeded {self.max_steps} steps")
            node = nodes.get(current)
            if node is None:
                raise WorkflowError(
                    "WORKFLOW_NODE_NOT_FOUND", f"node {current} does not exist", {"node_id": current}
                )
            execution.current_node = current
            result = await self._run_with_retry(execution, node)
            if node.get("type") == "condition" and isinstance(result, dict):
                targets = self._next_nodes(node, branch=result.get("branch"))
            elif node.get("type") == "output":
                targets = []
            else:
                targets = self._next_nodes(node)
            current = targets[0] if targets else None
        return execution

    async def _run_with_retry(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        retry = config.get("retry") or {}
        attempts = max(1, int(retry.get("attempts", 1)))
        backoff = max(0.0, float(retry.get("backoff_seconds", 0.1)))
        timeout = float(config.get("timeout_seconds") or self.node_timeout_seconds)
        node_id = str(node.get("id"))
        state = execution.nodes.get(node_id) or NodeState(node_id=node_id)
        execution.nodes[node_id] = state
        state.status = "RUNNING"
        state.started_at = datetime.datetime.utcnow().isoformat()
        await self._emit("workflow.node.started", {"node_id": node_id, "type": node.get("type")})
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            state.attempts = attempt
            try:
                result = await asyncio.wait_for(self._run_node(execution, node), timeout=timeout)
            except asyncio.TimeoutError:
                last_error = WorkflowError(
                    "WORKFLOW_NODE_TIMEOUT", f"node {node_id} timed out", {"node_id": node_id}
                )
            except WorkflowPaused:
                state.status = "WAITING_HUMAN"
                state.finished_at = datetime.datetime.utcnow().isoformat()
                await self._emit("workflow.node.waiting", {"node_id": node_id})
                raise
            except WorkflowError as exc:
                last_error = exc
            except Exception as exc:  # unexpected: keep the run debuggable
                last_error = WorkflowError(
                    "WORKFLOW_NODE_FAILED",
                    f"node {node_id} failed: {type(exc).__name__}",
                    {"node_id": node_id},
                )
            else:
                state.status = "COMPLETED"
                state.output = result
                state.finished_at = datetime.datetime.utcnow().isoformat()
                await self._emit(
                    "workflow.node.completed", {"node_id": node_id, "output": _preview(result)}
                )
                return result
            if attempt < attempts:
                await asyncio.sleep(backoff * attempt)
        state.status = "FAILED"
        state.error = getattr(last_error, "code", "WORKFLOW_NODE_FAILED")
        state.finished_at = datetime.datetime.utcnow().isoformat()
        await self._emit(
            "workflow.node.failed",
            {"node_id": node_id, "code": state.error, "message": str(last_error)},
        )
        raise last_error or WorkflowError("WORKFLOW_NODE_FAILED", f"node {node_id} failed")

    async def _run_node(self, execution: WorkflowExecution, node: dict):
        node_type = node.get("type")
        handler = getattr(self, f"_node_{node_type}", None)
        if handler is None:
            raise WorkflowError("WORKFLOW_NODE_TYPE_UNSUPPORTED", f"unsupported node type {node_type!r}")
        return await handler(execution, node)

    # -- node handlers ------------------------------------------------------

    async def _node_input(self, execution: WorkflowExecution, node: dict):  # noqa: ARG002
        return execution.input

    async def _node_output(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        namespace = execution.namespace()
        execution.output = (
            render_template(config.get("value"), namespace)
            if "value" in config
            else namespace["nodes"]
        )
        await self._emit(
            "workflow.output", {"node_id": node.get("id"), "output": _preview(execution.output)}
        )
        return execution.output

    async def _node_llm(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        namespace = execution.namespace()
        prompt = render_template(config.get("prompt") or "", namespace)
        messages = render_template(config.get("messages"), namespace) if config.get("messages") else None
        if messages is None:
            messages = [
                {
                    "role": "system",
                    "content": str(config.get("system_prompt") or "You are a helpful assistant."),
                },
                {"role": "user", "content": str(prompt)},
            ]
        model_id = config.get("model_id")
        if model_id is not None:
            result = await self._manager().chat(
                int(model_id),
                messages,
                user_id=execution.variables.get("user_id"),
                **({"runtime": config["runtime"]} if config.get("runtime") else {}),
            )
            return (result or {}).get("content", "")
        if str(config.get("provider") or "echo") == "echo":
            # Explicit, documented fallback so a definition can be validated
            # without a model; it never pretends to be real inference.
            return f"[echo] {messages[-1]['content']}"
        raise WorkflowError(
            "WORKFLOW_LLM_UNAVAILABLE", "llm node needs config.model_id or the echo provider"
        )

    async def _node_agent(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        agent_id = str(config.get("agent_id") or "")
        if not agent_id:
            raise WorkflowError("WORKFLOW_AGENT_REQUIRED", "agent node needs config.agent_id")
        namespace = execution.namespace()
        text = str(render_template(config.get("input") or "{{input.question}}", namespace))
        runtime = self._agent_runtime
        if runtime is None:
            from services.agent_runtime_service import get_agent_runtime

            runtime = get_agent_runtime()
        if runtime is None:
            raise WorkflowError("AGENT_RUNTIME_UNAVAILABLE", "agent runtime is not initialized")
        user_id = execution.variables.get("user_id")
        run = runtime.create_run(
            agent_id=agent_id,
            input_text=text,
            user_id=user_id,
            metadata={
                "workflow_run_id": execution.run_id,
                "workflow_node": node.get("id"),
                "model_id": _agent_model_id(runtime, agent_id),
            },
            execute=True,
        )
        store = self._run_store
        if store is None:
            from repositories.run_repository import SQLAlchemyRunStore

            store = SQLAlchemyRunStore()
        timeout = float(config.get("timeout_seconds") or self.node_timeout_seconds)
        deadline = asyncio.get_event_loop().time() + timeout
        current = None
        while True:
            current = store.get(run.run_id)
            if current is not None and current.status in TERMINAL_STATUSES:
                break
            if asyncio.get_event_loop().time() > deadline:
                raise WorkflowError(
                    "WORKFLOW_NODE_TIMEOUT", f"agent node {node.get('id')} timed out"
                )
            await asyncio.sleep(0.05)
        if current.status != "COMPLETED":
            raise WorkflowError(
                "WORKFLOW_AGENT_FAILED",
                f"agent {agent_id} run finished as {current.status}",
                {"run_id": current.run_id},
            )
        execution.variables.setdefault("agent_runs", {})[str(node.get("id"))] = current.run_id
        return current.output

    async def _node_tool(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        tool_name = str(config.get("tool") or "")
        if not tool_name:
            raise WorkflowError("WORKFLOW_TOOL_REQUIRED", "tool node needs config.tool")
        registry, runner = self._tooling()
        arguments = render_template(config.get("arguments") or {}, execution.namespace())
        tool = registry.get(tool_name) if registry is not None else None
        if tool is None:
            raise WorkflowError("TOOL_NOT_FOUND", f"tool {tool_name} is not registered", {"tool": tool_name})
        policy = self._policy_for(config)
        decision = policy.check_tool(None, tool_name, tool)
        if not decision.allowed:
            raise WorkflowError(
                "TOOL_DENIED", f"tool {tool_name} denied: {decision.reason}", {"tool": tool_name}
            )
        if decision.require_approval:
            raise WorkflowError(
                "HUMAN_APPROVAL_REQUIRED", f"tool {tool_name} requires human approval"
            )
        return await runner.run(tool_name, arguments, None)

    async def _node_condition(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        verdict = bool(evaluate_expression(str(config.get("expression") or ""), execution.namespace()))
        return {"branch": "true" if verdict else "false", "value": verdict}

    async def _node_parallel(self, execution: WorkflowExecution, node: dict):
        branches = node.get("branches") or []
        if not isinstance(branches, list) or not branches:
            raise WorkflowError("WORKFLOW_PARALLEL_EMPTY", "parallel node needs non-empty branches")
        nodes = self._nodes(execution)

        async def run_branch(branch: list) -> list[dict]:
            results = []
            for node_id in branch:
                target = nodes.get(str(node_id))
                if target is None:
                    raise WorkflowError("WORKFLOW_NODE_NOT_FOUND", f"node {node_id} does not exist")
                results.append(
                    {"node_id": node_id, "output": await self._run_with_retry(execution, target)}
                )
            return results

        gathered = await asyncio.gather(
            *(run_branch(branch) for branch in branches if isinstance(branch, list))
        )
        return {"branches": [item for group in gathered for item in group]}

    async def _node_loop(self, execution: WorkflowExecution, node: dict):
        config = node.get("config") or {}
        body = [str(item) for item in (node.get("body") or [])]
        if not body:
            raise WorkflowError("WORKFLOW_LOOP_EMPTY", "loop node needs a body")
        nodes = self._nodes(execution)
        max_iterations = max(1, int(config.get("max_iterations", 5)))
        iterations = 0
        results: list[dict] = []
        while iterations < max_iterations:
            iterations += 1
            for node_id in body:
                target = nodes.get(node_id)
                if target is None:
                    raise WorkflowError("WORKFLOW_NODE_NOT_FOUND", f"node {node_id} does not exist")
                results.append(
                    {"node_id": node_id, "output": await self._run_with_retry(execution, target)}
                )
            execution.variables["loop_iteration"] = iterations
            condition = config.get("while")
            if not condition or not evaluate_expression(str(condition), execution.namespace()):
                break
        return {"iterations": iterations, "results": results}

    async def _node_approval(self, execution: WorkflowExecution, node: dict):
        await self._emit(
            "workflow.approval.required",
            {
                "node_id": node.get("id"),
                "message": (node.get("config") or {}).get("message", "需要人工确认"),
            },
        )
        raise WorkflowPaused()

    # -- collaborators ------------------------------------------------------

    def _manager(self):
        if self._runtime_manager is not None:
            return self._runtime_manager
        from services.model_runtime_manager import get_model_runtime_manager

        return get_model_runtime_manager()

    def _tooling(self):
        if self._tool_registry is not None and self._tool_runner is not None:
            return self._tool_registry, self._tool_runner
        from runtime.tools import ToolExecutor, ToolRegistry
        from runtime.tools.builtin import register_builtin_tools

        registry = self._tool_registry or register_builtin_tools(ToolRegistry())
        runner = self._tool_runner or ToolExecutor(registry)
        return registry, runner

    @staticmethod
    def _policy_for(config: dict):
        from runtime.policy.engine import Policy

        raw = config.get("policy")
        if not isinstance(raw, dict):
            return Policy()
        fields = {key: value for key, value in raw.items() if key in Policy.__dataclass_fields__}
        return Policy(**fields)


def _agent_model_id(runtime, agent_id: str) -> int | None:
    try:
        agent = runtime.get_agent(agent_id)
    except Exception:
        return None
    return getattr(agent, "model_id", None)
