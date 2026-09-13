"""V1.5 Workflow engine unit tests: templates, expressions, validation, nodes."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.workflow_engine import (  # noqa: E402
    WorkflowEngine,
    WorkflowError,
    WorkflowExecution,
    evaluate_expression,
    render_template,
    validate_definition,
)


def _execution(definition: dict, run_input: dict | None = None, variables: dict | None = None) -> WorkflowExecution:
    return WorkflowExecution(
        run_id="run-1",
        definition=definition,
        input=run_input or {},
        variables=variables or {},
    )


def test_templates_resolve_paths_and_preserve_types():
    namespace = {
        "input": {"name": "bob", "items": [1, 2]},
        "variables": {"count": 3},
        "nodes": {"a": {"output": "hello"}},
    }

    assert render_template("hi {{input.name}}", namespace) == "hi bob"
    assert render_template("{{nodes.a.output}}", namespace) == "hello"
    assert render_template("{{variables.count}}", namespace) == 3
    assert render_template({"x": ["{{input.name}}", 1]}, namespace) == {"x": ["bob", 1]}
    # An exact placeholder keeps the raw value (None when missing) so a node can
    # detect the miss; an inline placeholder degrades to an empty string.
    assert render_template("{{unknown.path}}", namespace) is None
    assert render_template("value={{unknown.path}}", namespace) == "value="


def test_expression_whitelist_blocks_dangerous_code():
    namespace = {"nodes": {"a": {"output": "x"}}, "input": {"n": 2}}

    assert evaluate_expression("nodes.a.output == 'x'", namespace) is True
    assert evaluate_expression("input.n > 1 and len(nodes.a.output) == 1", namespace) is True
    assert evaluate_expression("'x' in nodes.a.output", namespace) is True
    assert evaluate_expression("", namespace) is False

    for bad in ("__import__('os').system('echo hi')", "open('/etc/passwd').read()", "input.__class__"):
        with pytest.raises(WorkflowError) as excinfo:
            evaluate_expression(bad, namespace)
        assert excinfo.value.code in {"WORKFLOW_EXPRESSION_INVALID", "WORKFLOW_EXPRESSION_FAILED"}


def test_definition_validation_reports_problems():
    assert validate_definition({
        "nodes": [
            {"id": "start", "type": "input", "next": "done"},
            {"id": "done", "type": "output"},
        ]
    }) == []

    problems = validate_definition({
        "nodes": [
            {"id": "start", "type": "input", "next": "ghost"},
            {"id": "start", "type": "nope"},
        ]
    })
    assert any("duplicate" in item for item in problems)
    assert any("unsupported type" in item for item in problems)
    assert any("unknown node ghost" in item for item in problems)
    assert "definition.nodes must be a non-empty list" in validate_definition({})


@pytest.mark.asyncio
async def test_sequential_condition_and_output(monkeypatch):
    definition = {
        "nodes": [
            {"id": "start", "type": "input", "next": "ask"},
            {"id": "ask", "type": "llm", "config": {"prompt": "{{input.question}}"}, "next": "check"},
            {
                "id": "check",
                "type": "condition",
                "config": {"expression": "'echo' in nodes.ask.output"},
                "true_next": "done",
                "false_next": "ask",
            },
            {"id": "done", "type": "output", "config": {"value": "{{nodes.ask.output}}"}},
        ]
    }
    execution = _execution(definition, {"question": "hello"})

    await WorkflowEngine(emit=_noop).execute(execution)

    assert execution.output == "[echo] hello"
    assert execution.nodes["check"].output["branch"] == "true"
    assert execution.nodes["done"].status == "COMPLETED"


async def _noop(event_type: str, payload: dict) -> None:
    return None


@pytest.mark.asyncio
async def test_retry_until_success(monkeypatch):
    attempts = {"count": 0}

    class FlakyEngine(WorkflowEngine):
        async def _node_llm(self, execution, node):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise WorkflowError("WORKFLOW_NODE_FAILED", "not yet")
            return "ok"

    definition = {
        "nodes": [
            {"id": "start", "type": "input", "next": "flaky"},
            {
                "id": "flaky",
                "type": "llm",
                "config": {"retry": {"attempts": 3, "backoff_seconds": 0}, "timeout_seconds": 5},
                "next": "done",
            },
            {"id": "done", "type": "output", "config": {"value": "{{nodes.flaky.output}}"}},
        ]
    }

    execution = _execution(definition)
    await FlakyEngine(emit=_noop).execute(execution)

    assert attempts["count"] == 3
    assert execution.nodes["flaky"].attempts == 3
    assert execution.output == "ok"


@pytest.mark.asyncio
async def test_node_timeout_is_reported():
    class SlowEngine(WorkflowEngine):
        async def _node_llm(self, execution, node):
            await asyncio.sleep(0.5)
            return "too late"

    definition = {
        "nodes": [
            {"id": "start", "type": "input", "next": "slow"},
            {"id": "slow", "type": "llm", "config": {"timeout_seconds": 0.05}, "next": "done"},
            {"id": "done", "type": "output"},
        ]
    }

    with pytest.raises(WorkflowError) as excinfo:
        await SlowEngine(emit=_noop).execute(_execution(definition))

    assert excinfo.value.code == "WORKFLOW_NODE_TIMEOUT"


@pytest.mark.asyncio
async def test_parallel_branches_and_loop():
    definition = {
        "nodes": [
            {"id": "start", "type": "input", "next": "fan"},
            {
                "id": "fan",
                "type": "parallel",
                "branches": [["p1"], ["p2"]],
                "next": "repeat",
            },
            {"id": "p1", "type": "llm", "config": {"prompt": "one"}},
            {"id": "p2", "type": "llm", "config": {"prompt": "two"}},
            {
                "id": "repeat",
                "type": "loop",
                "body": ["tick"],
                "config": {"max_iterations": 3, "while": "variables.loop_iteration < 2"},
                "next": "done",
            },
            {"id": "tick", "type": "llm", "config": {"prompt": "tick"}},
            {"id": "done", "type": "output", "config": {"value": "{{nodes.fan.output}}"}},
        ]
    }

    execution = _execution(definition)
    await WorkflowEngine(emit=_noop).execute(execution)

    assert len(execution.nodes["fan"].output["branches"]) == 2
    assert execution.nodes["repeat"].output["iterations"] == 2
    assert execution.nodes["done"].status == "COMPLETED"


@pytest.mark.asyncio
async def test_unknown_node_type_fails_the_run():
    definition = {
        "nodes": [
            {"id": "start", "type": "input", "next": "weird"},
            {"id": "weird", "type": "output"},
        ]
    }
    execution = _execution(definition)
    nodes = {node["id"]: node for node in definition["nodes"]}
    nodes["weird"]["type"] = "input"  # valid type, then force an unsupported one
    engine = WorkflowEngine(emit=_noop)

    async def run():
        nodes["weird"]["type"] = "not-a-type"
        return await engine._run_node(execution, nodes["weird"])

    with pytest.raises(WorkflowError) as excinfo:
        await run()
    assert excinfo.value.code == "WORKFLOW_NODE_TYPE_UNSUPPORTED"
