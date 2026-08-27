"""Declarative cross-reference for migrated control-plane actions.

This module is deliberately content-free and side-effect free.  It joins the
risk and error catalogues for review; it never authorizes or invokes actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.action_risk import action_risk
from core.control_plane_errors import control_plane_error


OwnershipScope = Literal["current_user", "administrator", "configuration_only"]


@dataclass(frozen=True)
class ControlPlaneContract:
    """Review metadata for one action already covered by a control-plane contract."""

    action: str
    confirmation_error_code: str | None
    unavailable_error_code: str | None
    audit_durability_error_code: str | None
    ownership_scope: OwnershipScope
    preview_supported: bool


CONTROL_PLANE_CONTRACTS: dict[str, ControlPlaneContract] = {
    "agent.run.create": ControlPlaneContract("agent.run.create", "AGENT_RUN_CONFIRMATION_REQUIRED", None, "AGENT_RUN_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "agent.run.cancel": ControlPlaneContract("agent.run.cancel", "AGENT_RUN_CANCEL_CONFIRMATION_REQUIRED", None, "AGENT_RUN_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "agent.run.approve": ControlPlaneContract("agent.run.approve", "AGENT_RUN_APPROVAL_CONFIRMATION_REQUIRED", None, "AGENT_RUN_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "agent.run.reject": ControlPlaneContract("agent.run.reject", "AGENT_RUN_REJECTION_CONFIRMATION_REQUIRED", None, "AGENT_RUN_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "task.retry": ControlPlaneContract("task.retry", "TASK_RETRY_CONFIRMATION_REQUIRED", "TASK_UNAVAILABLE", "TASK_RETRY_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "task.retry_batch": ControlPlaneContract("task.retry_batch", "TASK_RETRY_CONFIRMATION_REQUIRED", "TASK_UNAVAILABLE", "TASK_RETRY_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "task.cancel": ControlPlaneContract("task.cancel", "TASK_CANCEL_CONFIRMATION_REQUIRED", "TASK_UNAVAILABLE", "TASK_CANCEL_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "training.start": ControlPlaneContract("training.start", "TRAINING_START_CONFIRMATION_REQUIRED", None, "TRAINING_START_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "training.stop": ControlPlaneContract("training.stop", "TRAINING_STOP_CONFIRMATION_REQUIRED", None, "TRAINING_STOP_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "training.register_model": ControlPlaneContract("training.register_model", "TRAINING_REGISTER_CONFIRMATION_REQUIRED", None, "TRAINING_REGISTER_AUDIT_DURABILITY_UNKNOWN", "current_user", True),
    "memory.delete": ControlPlaneContract("memory.delete", "MEMORY_DELETE_CONFIRMATION_REQUIRED", "MEMORY_UNAVAILABLE", "MEMORY_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "artifact.delete": ControlPlaneContract("artifact.delete", "ARTIFACT_DELETE_CONFIRMATION_REQUIRED", "WORKSPACE_RESOURCE_UNAVAILABLE", "WORKSPACE_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "collection.document.add": ControlPlaneContract("collection.document.add", "COLLECTION_ASSOCIATION_CONFIRMATION_REQUIRED", "WORKSPACE_RESOURCE_UNAVAILABLE", "WORKSPACE_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "collection.document.remove": ControlPlaneContract("collection.document.remove", "COLLECTION_ASSOCIATION_CONFIRMATION_REQUIRED", "WORKSPACE_RESOURCE_UNAVAILABLE", "WORKSPACE_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "collection.delete": ControlPlaneContract("collection.delete", "COLLECTION_DELETE_CONFIRMATION_REQUIRED", "WORKSPACE_RESOURCE_UNAVAILABLE", "WORKSPACE_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "plugin_profile.delete": ControlPlaneContract("plugin_profile.delete", "PLUGIN_PROFILE_DELETE_CONFIRMATION_REQUIRED", "WORKSPACE_RESOURCE_UNAVAILABLE", "WORKSPACE_AUDIT_DURABILITY_UNKNOWN", "current_user", False),
    "plugin.lifecycle": ControlPlaneContract("plugin.lifecycle", "PLUGIN_CONFIRM_REQUIRED", None, "PLUGIN_AUDIT_DURABILITY_UNKNOWN", "administrator", False),
    "mcp.connect": ControlPlaneContract("mcp.connect", "MCP_CONNECTION_CONFIRMATION_REQUIRED", None, "MCP_AUDIT_DURABILITY_UNKNOWN", "administrator", False),
    "mcp.unregister": ControlPlaneContract("mcp.unregister", "MCP_UNREGISTER_CONFIRMATION_REQUIRED", None, "MCP_AUDIT_DURABILITY_UNKNOWN", "administrator", False),
}


def control_plane_contract(action: str) -> ControlPlaneContract | None:
    """Return review metadata for one migrated action without changing state."""
    return CONTROL_PLANE_CONTRACTS.get(action)


def contract_references_are_known(contract: ControlPlaneContract) -> bool:
    """Statically verify that the catalogued policy and codes exist."""
    if action_risk(contract.action) is None:
        return False
    return all(
        code is None or control_plane_error(code) is not None
        for code in (
            contract.confirmation_error_code,
            contract.unavailable_error_code,
            contract.audit_durability_error_code,
        )
    )
