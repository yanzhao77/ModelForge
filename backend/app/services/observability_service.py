"""Unified trace + metrics overview (V1.8).

Two sources feed one observability view:

* **Trace** — Agent Runs and Workflow Runs are projected into the same
  ``{trace_id, summary, spans[], events[]}`` document (see
  ``services/agent_trace.py`` and ``services/workflow_trace.py``), so a single
  endpoint can list and fetch either kind.
* **Metrics** — per-model aggregate buckets (requests, latency, token
  estimates) plus the live resource snapshot. TTFT is *not* recorded today, so
  it is reported as ``None`` with a reason instead of a fabricated number.
"""

from __future__ import annotations

import json

from models.records import AgentRun, ModelMetricBucket, WorkflowRun


class ObservabilityService:
    def __init__(self, db):
        self.db = db

    # -- traces -------------------------------------------------------------

    def list_traces(self, user_id: int, *, kind: str | None = None, limit: int = 50) -> list[dict]:
        traces: list[dict] = []
        if kind in (None, "", "agent"):
            rows = (
                self.db.query(AgentRun)
                .filter(AgentRun.user_id == user_id)
                .order_by(AgentRun.created_at.desc())
                .limit(max(1, min(limit, 200)))
                .all()
            )
            for row in rows:
                try:
                    metadata = json.loads(row.meta) if row.meta else {}
                except (TypeError, ValueError):
                    metadata = {}
                traces.append(
                    {
                        "trace_id": row.run_id,
                        "kind": "agent",
                        "name": row.agent_id,
                        "status": row.status,
                        "model": row.model,
                        "model_id": metadata.get("model_id") if isinstance(metadata, dict) else None,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    }
                )
        if kind in (None, "", "workflow"):
            rows = (
                self.db.query(WorkflowRun)
                .filter(WorkflowRun.user_id == user_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(max(1, min(limit, 200)))
                .all()
            )
            traces.extend(
                {
                    "trace_id": row.id,
                    "kind": "workflow",
                    "name": row.workflow_id,
                    "status": row.status,
                    "model": None,
                    "model_id": None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                }
                for row in rows
            )
        traces.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return traces[: max(1, min(limit, 200))]

    def get_trace(self, user_id: int, trace_id: str) -> dict | None:
        from services.agent_run_service import AgentRunService
        from services.workflow_service import WorkflowService, WorkflowServiceError

        try:
            return AgentRunService(self.db).trace(trace_id, user_id)
        except Exception:
            pass
        try:
            return WorkflowService(self.db).trace(user_id, trace_id)
        except WorkflowServiceError:
            return None

    # -- metrics ------------------------------------------------------------

    def metrics_overview(self, user_id: int, *, limit: int = 50) -> dict:
        rows = (
            self.db.query(ModelMetricBucket)
            .filter(ModelMetricBucket.user_id == user_id)
            .order_by(ModelMetricBucket.bucket_start.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        models = [self._model_metrics(row) for row in rows]
        total_requests = sum(item["requests"] for item in models)
        total_tokens = sum(item["total_tokens"] for item in models)
        total_latency_ms = sum(item["latency_sum_ms"] for item in models)
        total_success = sum(item["success"] for item in models)
        return {
            "ttft_ms": None,
            "ttft_unavailable_reason": "TTFT is not recorded by the local runtime yet",
            "totals": {
                "requests": total_requests,
                "success": total_success,
                "success_rate": round(total_success / total_requests, 4) if total_requests else None,
                "total_tokens": total_tokens,
                "avg_latency_ms": round(total_latency_ms / total_requests, 2) if total_requests else None,
                "tokens_per_second": (
                    round(total_tokens / (total_latency_ms / 1000), 2)
                    if total_latency_ms > 0 and total_tokens
                    else None
                ),
            },
            "models": models,
        }

    @staticmethod
    def _model_metrics(row: ModelMetricBucket) -> dict:
        latency_sum = float(row.latency_sum_ms or 0.0)
        requests = int(row.request_count or 0)
        tokens = int(row.input_tokens_estimate or 0) + int(row.output_tokens_estimate or 0)
        return {
            "model_ref": row.model_ref,
            "bucket_start": row.bucket_start.isoformat() if row.bucket_start else None,
            "requests": requests,
            "success": int(row.success_count or 0),
            "errors": {
                "4xx": int(row.error_4xx_count or 0),
                "429": int(row.error_429_count or 0),
                "5xx": int(row.error_5xx_count or 0),
                "timeout": int(row.timeout_count or 0),
            },
            "latency_sum_ms": latency_sum,
            "avg_latency_ms": round(latency_sum / requests, 2) if requests else None,
            "input_tokens": int(row.input_tokens_estimate or 0),
            "output_tokens": int(row.output_tokens_estimate or 0),
            "total_tokens": tokens,
            "tokens_per_second": (
                round(tokens / (latency_sum / 1000), 2) if latency_sum > 0 and tokens else None
            ),
        }

    def resource_metrics(self) -> dict:
        from services.model_runtime_manager import get_model_runtime_manager

        manager = get_model_runtime_manager()
        return {
            "resources": manager.resources.status(),
            "instances": manager.instances_payload(),
            "queue": manager.queue_snapshot(),
            "recent_events": manager.recent_events(),
        }
