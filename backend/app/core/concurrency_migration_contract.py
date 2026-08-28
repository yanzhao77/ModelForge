"""Static CP7 schema requirements; this module never emits or executes DDL."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConcurrencySchemaRequirement:
    """A reviewable schema fact or future append-only migration requirement."""

    key: str
    table: str
    state: str
    columns: tuple[str, ...]
    uniqueness: tuple[str, ...]
    compatibility: str
    no_go: str


CONCURRENCY_SCHEMA_REQUIREMENTS: tuple[ConcurrencySchemaRequirement, ...] = (
    ConcurrencySchemaRequirement(
        key="agent_run_cas_lease",
        table="agent_runs",
        state="present_in_orm_pending_runtime_validation",
        columns=("state_version", "executor_lease_id", "lease_expires_at", "terminal_event_key"),
        uniqueness=("run_id", "terminal_event_key"),
        compatibility="Existing rows use default state_version=1; lease fields remain nullable until a future authorized claim writer is deployed.",
        no_go="Do not rely on an in-memory executor set as authorization or terminal-state truth.",
    ),
    ConcurrencySchemaRequirement(
        key="agent_event_idempotency",
        table="agent_events",
        state="present_in_orm_pending_runtime_validation",
        columns=("run_id", "sequence", "event_key", "correlation_id"),
        uniqueness=("run_id+event_key",),
        compatibility="Historical records may not have event_key; a future writer must distinguish them from new idempotent events.",
        no_go="Do not backfill event keys from payload or infer event content.",
    ),
    ConcurrencySchemaRequirement(
        key="schedule_occurrence_claim",
        table="schedule_executions",
        state="present_in_orm_pending_runtime_validation",
        columns=("occurrence_key", "claim_token", "claim_expires_at", "state_version", "attempt_count"),
        uniqueness=("schedule_id+occurrence_key",),
        compatibility="Null occurrence keys remain legacy-compatible; new code must not treat multiple nulls as one claimed occurrence.",
        no_go="Do not create or recover occurrences before an authorized claim/CAS implementation is verified.",
    ),
    ConcurrencySchemaRequirement(
        key="task_outbox_delivery",
        table="task_outbox",
        state="present_in_orm_pending_runtime_validation",
        columns=("event_id", "lease_token", "lease_expires_at", "next_attempt_at", "attempts"),
        uniqueness=("event_id",),
        compatibility="Existing event-backed rows retain a nullable delivery lease and must be safely observable before any publisher change.",
        no_go="Do not equate a dispatched timestamp with delivery confirmation or duplicate-safe external publication.",
    ),
    ConcurrencySchemaRequirement(
        key="run_metric_emission",
        table="run_metric_emissions",
        state="present_in_orm_pending_runtime_validation",
        columns=("emission_key", "run_id", "state_version"),
        uniqueness=("emission_key",),
        compatibility="Terminal metric emission remains independent from the primary Run transaction.",
        no_go="Do not make Run terminal state depend on metric aggregation or notification delivery.",
    ),
    ConcurrencySchemaRequirement(
        key="task_request_idempotency",
        table="task_records",
        state="future_append_only_migration_required",
        columns=("user_id", "idempotency_key"),
        uniqueness=("user_id+idempotency_key where key is non-null",),
        compatibility="Legacy null keys remain valid; only newly supplied non-null keys participate in the future uniqueness rule.",
        no_go="Do not deduplicate by task title, summary, input, metadata, error text, path, or other user content.",
    ),
)


def concurrency_schema_requirements() -> tuple[ConcurrencySchemaRequirement, ...]:
    """Return static specifications without inspecting or changing database state."""
    return CONCURRENCY_SCHEMA_REQUIREMENTS
