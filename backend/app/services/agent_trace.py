"""Assemble a Trace (spans + events) from a persisted Agent Run.

V1.1 requires "Trace 完整": run, model calls, tool calls, tool results, memory
retrieval, final output, error and timestamps. The Agent runtime already emits
every one of those as a durable event, so the trace is a *projection* of the
event stream rather than a second source of truth.

Span shape (V1.8 keeps the same structure and adds evaluation/metadata)::

    {"span_id", "name", "type", "status", "started_at", "ended_at",
     "duration_ms", "attributes", "events": [...]}
"""

from __future__ import annotations

import datetime
from typing import Any

_TERMINAL_STATUS = {
    "run.completed": "COMPLETED",
    "run.failed": "FAILED",
    "run.cancelled": "CANCELLED",
    "run.timeout": "TIMEOUT",
}

_SPAN_SPECS: tuple[tuple[str, str, str], ...] = (
    ("model.request.started", "model.request.completed", "model"),
    ("tool.call.started", "tool.call.completed", "tool"),
    ("knowledge.search.started", "knowledge.search.completed", "retrieval"),
    ("human.approval.required", "human.approval.granted", "approval"),
)

_FAILURE_TYPES = {
    "model.request.failed": "model.request.started",
    "tool.call.failed": "tool.call.started",
    "human.approval.denied": "human.approval.required",
    "run.failed": "run.started",
    "run.timeout": "run.started",
    "run.cancelled": "run.started",
}


def _parse_timestamp(value: Any) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _duration_ms(started: Any, ended: Any) -> int | None:
    start, end = _parse_timestamp(started), _parse_timestamp(ended)
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _span_name(event_type: str, payload: dict) -> str:
    if event_type == "model.request.started":
        return f"model.call[{payload.get('iteration', 0)}]"
    if event_type == "tool.call.started":
        return f"tool.{payload.get('tool', 'unknown')}"
    if event_type == "knowledge.search.started":
        return "knowledge.search"
    if event_type == "human.approval.required":
        return f"approval.{payload.get('tool', 'human')}"
    return event_type


def build_trace(run: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Project one run plus its events into a complete trace document."""
    ordered = sorted(events, key=lambda item: item.get("sequence", 0))
    spans: list[dict[str, Any]] = []
    open_spans: dict[str, dict[str, Any]] = {}

    def start_span(event: dict, *, span_type: str) -> str:
        key = f"{span_type}:{event.get('event_type')}:{event.get('sequence')}"
        span = {
            "span_id": f"span-{event.get('sequence')}",
            "name": _span_name(event.get("event_type", ""), event.get("payload") or {}),
            "type": span_type,
            "status": "RUNNING",
            "started_at": event.get("timestamp"),
            "ended_at": None,
            "duration_ms": None,
            "attributes": dict(event.get("payload") or {}),
            "events": [event],
        }
        spans.append(span)
        open_spans[key] = span
        open_spans[f"latest:{span_type}"] = span
        return key

    def close_span(span: dict, event: dict, status: str) -> None:
        span["status"] = status
        span["ended_at"] = event.get("timestamp")
        span["duration_ms"] = _duration_ms(span["started_at"], span["ended_at"])
        span["events"].append(event)
        payload = event.get("payload") or {}
        if isinstance(payload, dict):
            for key in ("output", "error", "result"):
                if key in payload and payload[key] is not None:
                    span["attributes"][key] = payload[key]
            if "duration" in payload and span["duration_ms"] is None and isinstance(payload["duration"], (int, float)):
                span["duration_ms"] = int(float(payload["duration"]) * 1000)

    for event in ordered:
        event_type = event.get("event_type", "")
        start_type = _FAILURE_TYPES.get(event_type)
        if event_type in {"run.created", "run.started"}:
            if "latest:run" not in open_spans:
                start_span(event, span_type="run")
            else:
                open_spans["latest:run"]["events"].append(event)
            continue
        spec = next((item for item in _SPAN_SPECS if item[0] == event_type), None)
        if spec is not None:
            start_span(event, span_type=spec[2])
            continue
        if start_type is not None:
            span = open_spans.get(f"latest:{_span_type_for(start_type)}")
            if span is not None:
                status = {
                    "model.request.failed": "FAILED",
                    "tool.call.failed": "FAILED",
                    "human.approval.denied": "DENIED",
                }.get(event_type, "FAILED")
                close_span(span, event, status)
            continue
        if event_type in {"model.request.completed", "tool.call.completed", "knowledge.search.completed", "human.approval.granted"}:
            span = open_spans.get(f"latest:{_span_type_for(event_type)}")
            if span is not None:
                close_span(span, event, "COMPLETED")
            continue
        if event_type in {"memory.read", "memory.write"}:
            spans.append({
                "span_id": f"span-{event.get('sequence')}",
                "name": event_type,
                "type": "memory",
                "status": "COMPLETED",
                "started_at": event.get("timestamp"),
                "ended_at": event.get("timestamp"),
                "duration_ms": 0,
                "attributes": dict(event.get("payload") or {}),
                "events": [event],
            })
            continue
        # Any remaining event (agent.response, runtime.error, …) is attached to
        # the enclosing run span so no fact is lost.
        run_span = open_spans.get("latest:run")
        if run_span is not None:
            run_span["events"].append(event)

    for status_event, status in _TERMINAL_STATUS.items():
        matched = [event for event in ordered if event.get("event_type") == status_event]
        if matched:
            run_span = open_spans.get("latest:run")
            if run_span is not None and run_span["status"] == "RUNNING":
                close_span(run_span, matched[-1], status)
            break

    if not spans:
        spans.append({
            "span_id": "span-run",
            "name": "agent.run",
            "type": "run",
            "status": run.get("status", "PENDING"),
            "started_at": run.get("started_at") or run.get("created_at"),
            "ended_at": run.get("finished_at"),
            "duration_ms": _duration_ms(run.get("started_at") or run.get("created_at"), run.get("finished_at")),
            "attributes": {},
            "events": [],
        })

    model_calls = [span for span in spans if span["type"] == "model"]
    tool_calls = [span for span in spans if span["type"] == "tool"]
    retrievals = [span for span in spans if span["type"] == "retrieval"]
    total_ms = sum(span["duration_ms"] or 0 for span in spans)
    return {
        "trace_id": run.get("run_id"),
        "run_id": run.get("run_id"),
        "agent_id": run.get("agent_id"),
        "model_id": run.get("metadata", {}).get("model_id") if isinstance(run.get("metadata"), dict) else None,
        "model": run.get("model"),
        "status": run.get("status"),
        "input": run.get("input"),
        "output": run.get("output"),
        "error": run.get("error"),
        "started_at": run.get("started_at") or run.get("created_at"),
        "finished_at": run.get("finished_at"),
        "duration_ms": _duration_ms(run.get("started_at") or run.get("created_at"), run.get("finished_at")),
        "token_usage": run.get("token_usage") or {},
        "summary": {
            "span_count": len(spans),
            "model_calls": len(model_calls),
            "tool_calls": len(tool_calls),
            "retrievals": len(retrievals),
            "iteration_count": run.get("iteration_count") or 0,
            "tool_call_count": run.get("tool_call_count") or 0,
            "traced_duration_ms": total_ms,
        },
        "spans": spans,
        "events": ordered,
    }


def _span_type_for(event_type: str) -> str:
    if event_type.startswith("model.request"):
        return "model"
    if event_type.startswith("tool.call"):
        return "tool"
    if event_type.startswith("knowledge.search"):
        return "retrieval"
    if event_type.startswith("human.approval"):
        return "approval"
    if event_type.startswith("run."):
        return "run"
    return "run"
