"""Phase 1: Runtime Foundation tests (errors / cancellation / state / context / metrics)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import pytest

from runtime.errors import (
    AgentNotFoundError, PolicyDeniedError, RunCancelledError, RunTimeoutError,
    RuntimeError, ToolDeniedError, ERROR_CODES,
)
from runtime.cancellation import CancellationToken
from runtime.state import AgentState
from runtime.types import RunRecord, RunStatus
from runtime.run_context import RunContext, ToolExecutionContext
from runtime.metrics import MetricsRegistry
from runtime.logging import get_logger, log_run


class TestErrors:
    def test_error_dict_shape(self):
        err = AgentNotFoundError("no agent")
        data = err.to_dict()
        assert data["error"]["code"] == "AGENT_NOT_FOUND"
        assert data["error"]["message"] == "no agent"
        assert data["error"]["details"] == {}

    def test_default_message(self):
        err = PolicyDeniedError()
        assert err.code == "POLICY_DENIED"
        assert err.message == "Action denied by policy"

    def test_required_codes_present(self):
        required = [
            "AGENT_NOT_FOUND", "RUN_NOT_FOUND", "RUN_CANCELLED", "RUN_TIMEOUT",
            "TOOL_NOT_FOUND", "TOOL_DENIED", "TOOL_TIMEOUT", "MODEL_NOT_FOUND",
            "MODEL_UNAVAILABLE", "CONTEXT_TOO_LARGE", "POLICY_DENIED",
            "HUMAN_APPROVAL_REQUIRED", "RUNTIME_ERROR",
        ]
        for code in required:
            assert code in ERROR_CODES, f"missing error code: {code}"

    def test_subclass_hierarchy(self):
        assert issubclass(RunTimeoutError, RuntimeError)
        assert issubclass(ToolDeniedError, RuntimeError)


class TestCancellation:
    def test_cancel_flow(self):
        token = CancellationToken()
        assert token.cancelled is False
        token.check()  # no raise
        token.cancel()
        assert token.cancelled is True
        with pytest.raises(RunCancelledError):
            token.check()


class TestAgentState:
    def test_round_trip(self):
        st = AgentState(
            run_id="r1",
            messages=[{"role": "user", "content": "hi"}],
            variables={"x": 1},
            iteration=3,
            status="RUNNING",
        )
        data = st.to_dict()
        st2 = AgentState.from_dict(data)
        assert st2.run_id == "r1"
        assert st2.messages == [{"role": "user", "content": "hi"}]
        assert st2.iteration == 3
        assert st2.status == "RUNNING"

    def test_no_sqlalchemy_dependency(self):
        import runtime.state as st_mod
        import runtime.types as ty_mod
        for mod in (st_mod, ty_mod):
            src = open(mod.__file__, encoding="utf-8").read().lower()
            assert "import sqlalchemy" not in src
            assert "from sqlalchemy" not in src
            assert "import fastapi" not in src
            assert "from fastapi" not in src


class TestRunRecord:
    def test_defaults(self):
        run = RunRecord(run_id="abc", agent_id="agent1")
        assert run.status == "PENDING"
        assert run.tool_call_count == 0
        assert run.iteration_count == 0

    def test_round_trip(self):
        run = RunRecord(
            run_id="r2", agent_id="a", user_id=7, session_id=3,
            status="COMPLETED", input="in", output="out", model="m",
            tool_call_count=2, iteration_count=1,
            token_usage={"total_tokens": 10}, metadata={"k": "v"},
        )
        run2 = RunRecord.from_dict(run.to_dict())
        assert run2.run_id == "r2"
        assert run2.user_id == 7
        assert run2.status == "COMPLETED"
        assert run2.token_usage == {"total_tokens": 10}
        assert run2.metadata == {"k": "v"}
        assert run2.tool_call_count == 2

    def test_all_statuses_defined(self):
        for s in ("PENDING", "RUNNING", "WAITING_TOOL", "WAITING_HUMAN",
                  "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
            assert RunStatus[s] is not None

    def test_terminal_statuses(self):
        assert RunStatus.COMPLETED in RunStatus.terminal()
        assert RunStatus.RUNNING not in RunStatus.terminal()


class TestRunContext:
    def test_timeout_check(self):
        ctx = RunContext(run_id="r", agent_id="a", timeout_seconds=1, started_at=time.monotonic() - 5)
        with pytest.raises(RunTimeoutError):
            ctx.check_timeout()

    def test_no_timeout_within_budget(self):
        ctx = RunContext(run_id="r", agent_id="a", timeout_seconds=60, started_at=time.monotonic())
        ctx.check_timeout()  # no raise

    def test_defaults_from_settings(self):
        from core.config import settings
        ctx = RunContext(run_id="r", agent_id="a")
        assert ctx.max_iterations == 20
        assert ctx.max_tool_calls == 50
        assert ctx.timeout_seconds == 600

    def test_tool_context_cancellation(self):
        token = CancellationToken()
        tctx = ToolExecutionContext(run_id="r", agent_id="a", cancellation_token=token)
        tctx.check_cancelled()
        token.cancel()
        with pytest.raises(RunCancelledError):
            tctx.check_cancelled()


class TestMetrics:
    def test_counters(self):
        m = MetricsRegistry()
        m.inc("agent_runs_total")
        m.inc("agent_runs_total")
        m.inc("tool_calls_total")
        assert m.count("agent_runs_total") == 2
        assert m.count("tool_calls_total") == 1

    def test_durations(self):
        m = MetricsRegistry()
        m.record("agent_run_duration", 0.5)
        m.record("agent_run_duration", 1.5)
        snap = m.snapshot()
        assert snap["agent_run_duration_total"] == 2
        assert snap["agent_run_duration_avg"] == 1.0

    def test_run_finished(self):
        m = MetricsRegistry()
        m.on_run_finished("COMPLETED", 1.0)
        m.on_run_finished("FAILED", 2.0)
        assert m.count("agent_runs_total") == 2
        assert m.count("agent_runs_success") == 1
        assert m.count("agent_runs_failed") == 1

    def test_required_metric_names(self):
        m = MetricsRegistry()
        m.on_run_finished("COMPLETED", 0.1)
        m.on_tool_call(0.2)
        m.on_llm_call(100)
        snap = m.snapshot()
        for name in ("agent_runs_total", "agent_runs_success", "agent_runs_failed",
                     "agent_run_duration", "tool_calls_total", "tool_call_duration",
                     "llm_calls_total", "llm_tokens_total"):
            assert name in snap, f"missing metric: {name}"


class TestLogging:
    def test_log_run_includes_run_id(self, caplog):
        logger = get_logger("test.phase1")
        logger.setLevel(20)  # INFO
        caplog.set_level(20)
        log_run(logger, 20, "hello", run_id="r_42", agent_id="a1")
        assert any("run_id=r_42" in r.message for r in caplog.records)