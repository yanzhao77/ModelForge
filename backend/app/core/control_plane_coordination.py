"""Declarative coordination boundaries for control-plane actions.

This module is a review aid only.  It never opens a transaction, dispatches
work, starts a process, loads a plugin, or contacts an MCP/provider service.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CoordinationKind = Literal[
    "same_session_persistence",
    "post_commit_dispatch",
    "independent_runtime_side_effect",
    "read_only",
]

ReceiptState = Literal["persisted", "accepted", "pending", "durability_unknown", "read_only"]


@dataclass(frozen=True)
class CoordinationBoundary:
    """Content-free statement of an action's persistence and side-effect boundary."""

    action: str
    kind: CoordinationKind
    success_receipt: ReceiptState
    uncertainty_receipt: ReceiptState | None
    safe_to_replay_after_uncertainty: bool


COORDINATION_BOUNDARIES: dict[str, CoordinationBoundary] = {
    "agent.run.create": CoordinationBoundary("agent.run.create", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "agent.run.cancel": CoordinationBoundary("agent.run.cancel", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "agent.run.approve": CoordinationBoundary("agent.run.approve", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "agent.run.reject": CoordinationBoundary("agent.run.reject", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "task.retry": CoordinationBoundary("task.retry", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "task.retry_batch": CoordinationBoundary("task.retry_batch", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "task.cancel": CoordinationBoundary("task.cancel", "post_commit_dispatch", "accepted", "durability_unknown", False),
    "training.start": CoordinationBoundary("training.start", "independent_runtime_side_effect", "accepted", "durability_unknown", False),
    "training.stop": CoordinationBoundary("training.stop", "independent_runtime_side_effect", "accepted", "durability_unknown", False),
    "training.register_model": CoordinationBoundary("training.register_model", "independent_runtime_side_effect", "accepted", "durability_unknown", False),
    "plugin.lifecycle": CoordinationBoundary("plugin.lifecycle", "independent_runtime_side_effect", "accepted", "durability_unknown", False),
    "mcp.connect": CoordinationBoundary("mcp.connect", "independent_runtime_side_effect", "accepted", "durability_unknown", False),
    "memory.update": CoordinationBoundary("memory.update", "same_session_persistence", "persisted", "durability_unknown", False),
    "memory.delete": CoordinationBoundary("memory.delete", "same_session_persistence", "persisted", "durability_unknown", False),
    "artifact.delete": CoordinationBoundary("artifact.delete", "same_session_persistence", "persisted", "durability_unknown", False),
    "collection.document.add": CoordinationBoundary("collection.document.add", "same_session_persistence", "persisted", "durability_unknown", False),
    "collection.document.remove": CoordinationBoundary("collection.document.remove", "same_session_persistence", "persisted", "durability_unknown", False),
    "collection.delete": CoordinationBoundary("collection.delete", "same_session_persistence", "persisted", "durability_unknown", False),
    "plugin_profile.delete": CoordinationBoundary("plugin_profile.delete", "same_session_persistence", "persisted", "durability_unknown", False),
    "execution_intent.preview": CoordinationBoundary("execution_intent.preview", "read_only", "read_only", None, False),
    "control_plane_budget.read": CoordinationBoundary("control_plane_budget.read", "read_only", "read_only", None, False),
}


def coordination_boundary(action: str) -> CoordinationBoundary | None:
    """Return static coordination metadata without invoking the named action."""
    return COORDINATION_BOUNDARIES.get(action)


def safe_coordination_receipt(action: str, *, correlation_id: str, uncertainty: bool = False) -> dict[str, object]:
    """Describe a receipt without asserting that an action executed or rolled back."""
    boundary = coordination_boundary(action)
    if boundary is None:
        return {
            "action": action,
            "coordination": "unclassified",
            "receipt": "durability_unknown",
            "safe_to_replay": False,
            "correlation_id": correlation_id,
        }
    receipt = boundary.uncertainty_receipt if uncertainty else boundary.success_receipt
    return {
        "action": boundary.action,
        "coordination": boundary.kind,
        "receipt": receipt or "durability_unknown",
        "safe_to_replay": False,
        "correlation_id": correlation_id,
    }
