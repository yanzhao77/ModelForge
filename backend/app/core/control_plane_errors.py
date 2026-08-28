"""Version-controlled, content-free specifications for control-plane errors."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlPlaneError:
    code: str
    http_status: int
    retryable: bool
    correlation_required: bool = True
    forbidden_fields: tuple[str, ...] = ("input", "prompt", "output", "metadata", "exception", "token", "api_key", "path")


_CONFIRM = ("confirmation", "details")
_AUDIT = ("database", "exception", "traceback", "metadata", "input", "output")
_UNAVAILABLE = ("ownership", "existence", "input", "metadata", "exception")

ERROR_CATALOG: dict[str, ControlPlaneError] = {
    "AGENT_RUN_CONFIRMATION_REQUIRED": ControlPlaneError("AGENT_RUN_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "AGENT_RUN_CANCEL_CONFIRMATION_REQUIRED": ControlPlaneError("AGENT_RUN_CANCEL_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "AGENT_RUN_APPROVAL_CONFIRMATION_REQUIRED": ControlPlaneError("AGENT_RUN_APPROVAL_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "AGENT_RUN_REJECTION_CONFIRMATION_REQUIRED": ControlPlaneError("AGENT_RUN_REJECTION_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "TASK_RETRY_CONFIRMATION_REQUIRED": ControlPlaneError("TASK_RETRY_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "TASK_CANCEL_CONFIRMATION_REQUIRED": ControlPlaneError("TASK_CANCEL_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "TRAINING_START_CONFIRMATION_REQUIRED": ControlPlaneError("TRAINING_START_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "TRAINING_STOP_CONFIRMATION_REQUIRED": ControlPlaneError("TRAINING_STOP_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "TRAINING_REGISTER_CONFIRMATION_REQUIRED": ControlPlaneError("TRAINING_REGISTER_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "MEMORY_DELETE_CONFIRMATION_REQUIRED": ControlPlaneError("MEMORY_DELETE_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "ARTIFACT_DELETE_CONFIRMATION_REQUIRED": ControlPlaneError("ARTIFACT_DELETE_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "COLLECTION_ASSOCIATION_CONFIRMATION_REQUIRED": ControlPlaneError("COLLECTION_ASSOCIATION_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "COLLECTION_DELETE_CONFIRMATION_REQUIRED": ControlPlaneError("COLLECTION_DELETE_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "PLUGIN_PROFILE_DELETE_CONFIRMATION_REQUIRED": ControlPlaneError("PLUGIN_PROFILE_DELETE_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "PLUGIN_CONFIRM_REQUIRED": ControlPlaneError("PLUGIN_CONFIRM_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "MCP_CONNECTION_CONFIRMATION_REQUIRED": ControlPlaneError("MCP_CONNECTION_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "MCP_UNREGISTER_CONFIRMATION_REQUIRED": ControlPlaneError("MCP_UNREGISTER_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=_CONFIRM),
    "RUNTIME_ADMIN_REQUIRED": ControlPlaneError("RUNTIME_ADMIN_REQUIRED", 403, False, forbidden_fields=("administrator_list", "username", "exception", "configuration")),
    "CONTROL_AUDIT_METADATA_REJECTED": ControlPlaneError("CONTROL_AUDIT_METADATA_REJECTED", 500, False, forbidden_fields=_AUDIT),
    "AGENT_RUN_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("AGENT_RUN_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "TASK_RETRY_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("TASK_RETRY_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "TASK_CANCEL_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("TASK_CANCEL_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "TRAINING_START_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("TRAINING_START_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "TRAINING_STOP_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("TRAINING_STOP_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "TRAINING_REGISTER_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("TRAINING_REGISTER_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "WORKSPACE_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("WORKSPACE_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "MEMORY_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("MEMORY_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "PLUGIN_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("PLUGIN_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "MCP_AUDIT_DURABILITY_UNKNOWN": ControlPlaneError("MCP_AUDIT_DURABILITY_UNKNOWN", 503, True, forbidden_fields=_AUDIT),
    "TASK_UNAVAILABLE": ControlPlaneError("TASK_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "AGENT_RUN_UNAVAILABLE": ControlPlaneError("AGENT_RUN_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "TRAINING_TASK_UNAVAILABLE": ControlPlaneError("TRAINING_TASK_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "WORKSPACE_RESOURCE_UNAVAILABLE": ControlPlaneError("WORKSPACE_RESOURCE_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "MEMORY_UNAVAILABLE": ControlPlaneError("MEMORY_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "PLUGIN_UNAVAILABLE": ControlPlaneError("PLUGIN_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "MCP_SERVER_UNAVAILABLE": ControlPlaneError("MCP_SERVER_UNAVAILABLE", 404, False, forbidden_fields=_UNAVAILABLE),
    "TASK_VERSION_CONFLICT": ControlPlaneError("TASK_VERSION_CONFLICT", 409, True, forbidden_fields=("current_state", "other_user", "metadata", "exception")),
    "EXECUTION_INTENT_PREVIEW_ACTION_INVALID": ControlPlaneError("EXECUTION_INTENT_PREVIEW_ACTION_INVALID", 400, False, forbidden_fields=("target_ids", "metadata", "exception")),
    "EXECUTION_INTENT_CONFIRMATION_REQUIRED": ControlPlaneError("EXECUTION_INTENT_CONFIRMATION_REQUIRED", 409, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
    "EXECUTION_INTENT_PREVIEW_EXPIRED": ControlPlaneError("EXECUTION_INTENT_PREVIEW_EXPIRED", 409, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
    "EXECUTION_INTENT_PREVIEW_INVALID": ControlPlaneError("EXECUTION_INTENT_PREVIEW_INVALID", 400, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
    "EXECUTION_INTENT_PREVIEW_SCHEMA_MISMATCH": ControlPlaneError("EXECUTION_INTENT_PREVIEW_SCHEMA_MISMATCH", 409, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
    "EXECUTION_INTENT_PREVIEW_SCOPE_MISMATCH": ControlPlaneError("EXECUTION_INTENT_PREVIEW_SCOPE_MISMATCH", 409, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
    "EXECUTION_INTENT_PREVIEW_ACTION_MISMATCH": ControlPlaneError("EXECUTION_INTENT_PREVIEW_ACTION_MISMATCH", 409, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
    "EXECUTION_INTENT_EXECUTION_DISABLED": ControlPlaneError("EXECUTION_INTENT_EXECUTION_DISABLED", 409, False, forbidden_fields=("token", "target_ids", "target_versions", "metadata", "exception")),
}


def control_plane_error(code: str) -> ControlPlaneError | None:
    """Return a static error specification; this function has no execution side effects."""
    return ERROR_CATALOG.get(code)
