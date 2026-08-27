"""Declarative resource-availability semantics for control-plane APIs.

The helpers deliberately do not query persistence.  A route must first scope
its own query to the authenticated user, then use these rules if no row is
available.  That preserves non-enumerability across user boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.api_contracts import problem
from core.control_plane_errors import control_plane_error


OwnershipScope = Literal["current_user", "runtime_administrator"]


@dataclass(frozen=True)
class ResourceAccessPolicy:
    """Content-free ownership and error semantics for one resource category."""

    resource: str
    ownership_scope: OwnershipScope
    unavailable_code: str
    conflict_code: str | None = None


RESOURCE_ACCESS_POLICIES: dict[str, ResourceAccessPolicy] = {
    "agent_run": ResourceAccessPolicy("agent_run", "current_user", "AGENT_RUN_UNAVAILABLE"),
    "task": ResourceAccessPolicy("task", "current_user", "TASK_UNAVAILABLE", "TASK_VERSION_CONFLICT"),
    "training_task": ResourceAccessPolicy("training_task", "current_user", "TRAINING_TASK_UNAVAILABLE"),
    "memory": ResourceAccessPolicy("memory", "current_user", "MEMORY_UNAVAILABLE"),
    "workspace_resource": ResourceAccessPolicy("workspace_resource", "current_user", "WORKSPACE_RESOURCE_UNAVAILABLE"),
    "runtime_plugin": ResourceAccessPolicy("runtime_plugin", "runtime_administrator", "PLUGIN_UNAVAILABLE"),
    "mcp_server": ResourceAccessPolicy("mcp_server", "runtime_administrator", "MCP_SERVER_UNAVAILABLE"),
}


def resource_access_policy(resource: str) -> ResourceAccessPolicy | None:
    """Return static semantics for a resource category without checking it."""
    return RESOURCE_ACCESS_POLICIES.get(resource)


def unavailable_resource_problem(resource: str, *, correlation: str):
    """Build a non-enumerating error after a user-scoped query returned no row."""
    policy = resource_access_policy(resource)
    if policy is None or control_plane_error(policy.unavailable_code) is None:
        return problem(404, "CONTROL_RESOURCE_UNAVAILABLE", "The requested resource is unavailable.", correlation=correlation)
    spec = control_plane_error(policy.unavailable_code)
    return problem(spec.http_status, spec.code, "The requested resource is unavailable.", correlation=correlation)


def resource_conflict_problem(resource: str, *, correlation: str):
    """Build a content-free conflict error without exposing current state."""
    policy = resource_access_policy(resource)
    code = policy.conflict_code if policy else None
    spec = control_plane_error(code) if code else None
    if spec is None:
        return problem(409, "CONTROL_RESOURCE_CONFLICT", "The requested resource cannot be changed now.", correlation=correlation)
    return problem(spec.http_status, spec.code, "The requested resource changed. Refresh and confirm again.", correlation=correlation)
