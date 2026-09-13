"""Evaluation datasets, runs and A/B comparison (V1.8).

An evaluation executes each case against an Agent (or Workflow) and scores the
result with deterministic, explainable metrics:

* ``success_rate`` — the target run reached a successful terminal state;
* ``accuracy`` — the expected substring (or JSON field) appeared in the output;
* ``json_validity`` — the output parsed as JSON when the case asks for JSON;
* ``tool_success`` — every tool span in the trace completed;
* ``latency_ms`` — wall-clock duration per case;
* ``token_usage`` — summed from the target run when available.

No LLM-as-judge: every number is reproducible from the run itself.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
import uuid

from models.records import EvaluationDataset, EvaluationRun

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}


class EvaluationError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


class EvaluationService:
    def __init__(self, db, *, agent_runtime=None, run_store=None, workflow_service=None):
        self.db = db
        self._agent_runtime = agent_runtime
        self._run_store = run_store
        self._workflow_service = workflow_service

    # -- datasets -----------------------------------------------------------

    def create_dataset(self, user_id: int, name: str, cases: list[dict], description: str | None = None) -> dict:
        cleaned = str(name or "").strip()
        if not cleaned:
            raise EvaluationError("EVALUATION_NAME_REQUIRED", "Dataset name is required.")
        if not isinstance(cases, list) or not cases:
            raise EvaluationError("EVALUATION_CASES_REQUIRED", "At least one case is required.")
        for index, case in enumerate(cases):
            if not isinstance(case, dict) or not str(case.get("input") or "").strip():
                raise EvaluationError(
                    "EVALUATION_CASE_INVALID",
                    "Each case needs an 'input' string.",
                    {"index": index},
                )
        row = EvaluationDataset(
            id=uuid.uuid4().hex[:32],
            user_id=user_id,
            name=cleaned[:200],
            description=description,
            cases_json=json.dumps(cases, ensure_ascii=False),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row.to_dict()

    def list_datasets(self, user_id: int) -> list[dict]:
        rows = (
            self.db.query(EvaluationDataset)
            .filter(EvaluationDataset.user_id == user_id)
            .order_by(EvaluationDataset.created_at.desc())
            .all()
        )
        return [row.to_dict() for row in rows]

    def require_dataset(self, user_id: int, evaluation_id: str) -> EvaluationDataset:
        row = (
            self.db.query(EvaluationDataset)
            .filter(EvaluationDataset.id == evaluation_id, EvaluationDataset.user_id == user_id)
            .first()
        )
        if row is None:
            raise EvaluationError(
                "EVALUATION_NOT_FOUND",
                "Evaluation dataset not found.",
                {"evaluation_id": evaluation_id},
                http_status=404,
            )
        return row

    def delete_dataset(self, user_id: int, evaluation_id: str) -> bool:
        row = self.require_dataset(user_id, evaluation_id)
        self.db.query(EvaluationRun).filter(EvaluationRun.evaluation_id == evaluation_id).delete(
            synchronize_session=False
        )
        self.db.delete(row)
        self.db.commit()
        return True

    # -- runs ---------------------------------------------------------------

    async def start_run(
        self,
        user_id: int,
        evaluation_id: str,
        *,
        target_kind: str = "agent",
        target_id: str,
        timeout_seconds: float = 60.0,
    ) -> dict:
        """Evaluate every case.

        Async on purpose: each case starts a background Agent/Workflow run on
        the running loop, and the blocking wait happens in a worker thread so
        both sides can make progress.
        """
        dataset = self.require_dataset(user_id, evaluation_id)
        if target_kind not in {"agent", "workflow"}:
            raise EvaluationError(
                "EVALUATION_TARGET_UNSUPPORTED", "target_kind must be agent or workflow."
            )
        row = EvaluationRun(
            id=uuid.uuid4().hex[:32],
            evaluation_id=dataset.id,
            user_id=user_id,
            target_kind=target_kind,
            target_id=str(target_id),
            status="RUNNING",
        )
        self.db.add(row)
        self.db.commit()
        results = []
        for case in dataset.cases():
            results.append(
                await self._evaluate_case(user_id, target_kind, str(target_id), case, timeout_seconds)
            )
        row.metrics_json = json.dumps(_aggregate(results), ensure_ascii=False)
        row.results_json = json.dumps(results, ensure_ascii=False)
        row.status = "COMPLETED"
        row.finished_at = datetime.datetime.utcnow()
        self.db.commit()
        self.db.refresh(row)
        return row.to_dict()

    def list_runs(self, user_id: int, evaluation_id: str | None = None) -> list[dict]:
        query = self.db.query(EvaluationRun).filter(EvaluationRun.user_id == user_id)
        if evaluation_id:
            query = query.filter(EvaluationRun.evaluation_id == evaluation_id)
        rows = query.order_by(EvaluationRun.created_at.desc()).all()
        return [row.to_dict() for row in rows]

    def require_run(self, user_id: int, run_id: str) -> EvaluationRun:
        row = (
            self.db.query(EvaluationRun)
            .filter(EvaluationRun.id == run_id, EvaluationRun.user_id == user_id)
            .first()
        )
        if row is None:
            raise EvaluationError(
                "EVALUATION_RUN_NOT_FOUND", "Evaluation run not found.", {"run_id": run_id}, http_status=404
            )
        return row

    def compare(self, user_id: int, run_ids: list[str]) -> dict:
        if len(run_ids) < 2:
            raise EvaluationError("EVALUATION_COMPARE_NEEDS_TWO", "Provide at least two run ids.")
        runs = [self.require_run(user_id, run_id).to_dict() for run_id in run_ids]
        keys = ("success_rate", "accuracy", "json_validity", "tool_success", "avg_latency_ms", "total_tokens")
        comparison = {}
        for run in runs:
            metrics = run.get("metrics") or {}
            comparison[run["run_id"]] = {
                "target_kind": run["target_kind"],
                "target_id": run["target_id"],
                **{key: metrics.get(key) for key in keys},
            }
        baseline_id, candidate_id = runs[0]["run_id"], runs[1]["run_id"]
        deltas = {}
        for key in keys:
            first = (runs[0].get("metrics") or {}).get(key)
            second = (runs[1].get("metrics") or {}).get(key)
            deltas[key] = (
                round(float(second) - float(first), 4)
                if isinstance(first, (int, float)) and isinstance(second, (int, float))
                else None
            )
        return {"baseline": baseline_id, "candidate": candidate_id, "runs": comparison, "deltas": deltas}

    # -- internals ----------------------------------------------------------

    async def _evaluate_case(self, user_id: int, target_kind: str, target_id: str, case: dict, timeout: float) -> dict:
        started = time.monotonic()
        record: dict = {"case": case.get("name") or case["input"][:40], "status": "FAILED"}
        try:
            output, run_info, trace = await self._execute(user_id, target_kind, target_id, case, timeout)
            record.update(
                {
                    "status": "COMPLETED",
                    "output": output,
                    "run_id": run_info.get("run_id"),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "token_usage": run_info.get("token_usage") or {},
                }
            )
            expected = case.get("expected")
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            record["accuracy"] = expected is None or str(expected) in text
            if case.get("expect_json"):
                try:
                    json.loads(text)
                    record["json_validity"] = True
                except (TypeError, ValueError):
                    record["json_validity"] = False
            else:
                record["json_validity"] = None
            record["tool_success"] = _tools_succeeded(trace)
        except Exception as exc:
            record.update(
                {
                    "status": "FAILED",
                    "error": f"{getattr(exc, 'code', None) or type(exc).__name__}: {exc}"[:400],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "accuracy": False,
                    "json_validity": False,
                    "tool_success": False,
                }
            )
        return record

    async def _execute(self, user_id: int, target_kind: str, target_id: str, case: dict, timeout: float):
        if target_kind == "workflow":
            service = self._workflow_service
            if service is None:
                from services.workflow_service import WorkflowService

                service = WorkflowService(self.db)
            created = service.create_run(
                user_id, target_id, run_input=case.get("input_payload") or {"question": case["input"]}, execute=True
            )
            run = await asyncio.to_thread(
                self._wait, lambda: service.get_run(user_id, created["run_id"]), timeout
            )
            return run.get("output"), run, service.trace(user_id, created["run_id"])

        runtime = self._agent_runtime
        if runtime is None:
            from services.agent_runtime_service import get_agent_runtime

            runtime = get_agent_runtime()
        if runtime is None:
            raise EvaluationError("AGENT_RUNTIME_UNAVAILABLE", "Agent runtime is not initialized.", http_status=503)
        store = self._run_store
        if store is None:
            from repositories.run_repository import SQLAlchemyRunStore

            store = SQLAlchemyRunStore()
        run = runtime.create_run(
            agent_id=target_id,
            input_text=str(case["input"]),
            user_id=user_id,
            execute=True,
            metadata={"evaluation": True},
        )
        final = await asyncio.to_thread(self._wait, lambda: store.get(run.run_id), timeout)
        from services.agent_run_service import AgentRunService

        trace = AgentRunService(self.db, run_store=store).trace(run.run_id, user_id)
        return getattr(final, "output", None), getattr(final, "to_dict", lambda: {})(), trace

    @staticmethod
    def _wait(fetch, timeout: float):
        deadline = time.monotonic() + max(0.1, timeout)
        while True:
            current = fetch()
            status = getattr(current, "status", None) or (current or {}).get("status")
            if status in TERMINAL:
                if status != "COMPLETED":
                    detail = getattr(current, "error", None) or (current or {}).get("error") or ""
                    raise EvaluationError(
                        "EVALUATION_TARGET_FAILED",
                        f"target finished as {status}: {detail}"[:400],
                        {"status": status, "error": detail},
                    )
                return current
            if time.monotonic() > deadline:
                raise EvaluationError("EVALUATION_TIMEOUT", "target did not finish in time")
            time.sleep(0.05)


def _tools_succeeded(trace: dict) -> bool:
    spans = (trace or {}).get("spans") or []
    tool_spans = [span for span in spans if span.get("type") == "tool"]
    if not tool_spans:
        return True
    return all(span.get("status") == "COMPLETED" for span in tool_spans)


def _aggregate(results: list[dict]) -> dict:
    total = len(results) or 1
    successes = sum(1 for item in results if item.get("status") == "COMPLETED")
    accuracy = sum(1 for item in results if item.get("accuracy"))
    json_cases = [item for item in results if item.get("json_validity") is not None]
    tool_ok = sum(1 for item in results if item.get("tool_success"))
    latencies = [item.get("latency_ms") or 0 for item in results]
    tokens = sum(_token_total(item.get("token_usage")) for item in results)
    return {
        "case_count": len(results),
        "success_rate": round(successes / total, 4),
        "accuracy": round(accuracy / total, 4),
        "json_validity": (
            round(sum(1 for item in json_cases if item["json_validity"]) / len(json_cases), 4)
            if json_cases
            else None
        ),
        "tool_success": round(tool_ok / total, 4),
        "avg_latency_ms": round(sum(latencies) / total, 2),
        "total_tokens": tokens,
        "failures": [item.get("error") for item in results if item.get("status") != "COMPLETED"],
    }


def _token_total(usage) -> int:
    if not isinstance(usage, dict):
        return 0
    for key in ("total_tokens", "total"):
        if isinstance(usage.get(key), (int, float)):
            return int(usage[key])
    total = 0
    for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total
