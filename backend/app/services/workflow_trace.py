"""Project a Workflow Run into the shared Trace shape (V1.5/V1.8).

Keeping the workflow trace structurally identical to the Agent trace means the
desktop trace viewer, the evaluation service and the observability API all read
one format: ``{trace_id, status, summary, spans[], events[]}``.
"""

from __future__ import annotations

import datetime
from typing import Any


def _parse(value: Any) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _duration_ms(start: Any, end: Any) -> int | None:
    first, second = _parse(start), _parse(end)
    if first is None or second is None:
        return None
    return max(0, int((second - first).total_seconds() * 1000))


def build_workflow_trace(run: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    state = run.get("state") or {}
    nodes = state.get("nodes") or {}
    spans: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        spans.append(
            {
                "span_id": f"node-{node_id}",
                "name": f"workflow.node.{node_id}",
                "type": "node",
                "status": node.get("status", "PENDING"),
                "started_at": node.get("started_at"),
                "ended_at": node.get("finished_at"),
                "duration_ms": _duration_ms(node.get("started_at"), node.get("finished_at")),
                "attributes": {
                    "attempts": node.get("attempts"),
                    "error": node.get("error"),
                },
                "events": [event for event in events if (event.get("payload") or {}).get("node_id") == node_id],
            }
        )
    run_span = {
        "span_id": "workflow-run",
        "name": f"workflow.{run.get('workflow_id')}",
        "type": "run",
        "status": run.get("status"),
        "started_at": run.get("started_at") or run.get("created_at"),
        "ended_at": run.get("finished_at"),
        "duration_ms": _duration_ms(run.get("started_at") or run.get("created_at"), run.get("finished_at")),
        "attributes": {"current_node": run.get("current_node")},
        "events": [event for event in events if not (event.get("payload") or {}).get("node_id")],
    }
    spans.insert(0, run_span)
    counts: dict[str, int] = {}
    for span in spans:
        counts[span["status"]] = counts.get(span["status"], 0) + 1
    return {
        "trace_id": run.get("run_id"),
        "run_id": run.get("run_id"),
        "workflow_id": run.get("workflow_id"),
        "status": run.get("status"),
        "input": run.get("input"),
        "output": run.get("output"),
        "error": run.get("error"),
        "started_at": run.get("started_at") or run.get("created_at"),
        "finished_at": run.get("finished_at"),
        "duration_ms": _duration_ms(run.get("started_at") or run.get("created_at"), run.get("finished_at")),
        "summary": {
            "span_count": len(spans),
            "node_count": len(nodes),
            "status_counts": counts,
            "event_count": len(events),
        },
        "spans": spans,
        "events": sorted(events, key=lambda item: item.get("sequence", 0)),
    }
