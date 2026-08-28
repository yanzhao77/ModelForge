"""Declarative risk catalogue for control-plane actions.

This module must remain side-effect free.  It describes action policy only and
never calls runtimes, workers, providers, plugins, or persistence services.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RiskTier = Literal["low", "moderate", "high", "critical"]


@dataclass(frozen=True)
class ActionRisk:
    """Reviewable policy metadata for one named control-plane action."""

    action: str
    tier: RiskTier
    requires_confirmation: bool
    object_type: str
    audit_fields: tuple[str, ...]


_COMMON_AUDIT_FIELDS = ("confirmed", "request_id_supplied")


ACTION_RISKS: dict[str, ActionRisk] = {
    "agent.create": ActionRisk("agent.create", "moderate", False, "agent", ("request_id_supplied", "template_bound")),
    "agent.delete": ActionRisk("agent.delete", "high", True, "agent", _COMMON_AUDIT_FIELDS),
    "agent_template.create": ActionRisk("agent_template.create", "low", False, "agent_template", ("request_id_supplied",)),
    "agent_template.delete": ActionRisk("agent_template.delete", "moderate", True, "agent_template", _COMMON_AUDIT_FIELDS),
    "agent.run.create": ActionRisk("agent.run.create", "critical", True, "agent_run", (*_COMMON_AUDIT_FIELDS, "execute_requested", "session_bound")),
    "agent.run.cancel": ActionRisk("agent.run.cancel", "high", True, "agent_run", _COMMON_AUDIT_FIELDS),
    "agent.run.approve": ActionRisk("agent.run.approve", "high", True, "agent_run", _COMMON_AUDIT_FIELDS),
    "agent.run.reject": ActionRisk("agent.run.reject", "high", True, "agent_run", _COMMON_AUDIT_FIELDS),
    "task.retry": ActionRisk("task.retry", "high", True, "task", _COMMON_AUDIT_FIELDS),
    "task.retry_batch": ActionRisk("task.retry_batch", "high", True, "task_batch", (*_COMMON_AUDIT_FIELDS, "requested_count", "accepted_count", "rejected_count")),
    "task.cancel": ActionRisk("task.cancel", "high", True, "task", _COMMON_AUDIT_FIELDS),
    "training.start": ActionRisk("training.start", "critical", True, "training_task", (*_COMMON_AUDIT_FIELDS, "dataset_bound", "method")),
    "training.stop": ActionRisk("training.stop", "high", True, "training_task", _COMMON_AUDIT_FIELDS),
    "training.register_model": ActionRisk("training.register_model", "high", True, "training_task", _COMMON_AUDIT_FIELDS),
    "provider.verify": ActionRisk("provider.verify", "high", True, "remote_provider", _COMMON_AUDIT_FIELDS),
    "model.default.set": ActionRisk("model.default.set", "moderate", False, "model_default", ("request_id_supplied", "provider_bound")),
    "model.default.clear": ActionRisk("model.default.clear", "moderate", True, "model_default", _COMMON_AUDIT_FIELDS),
    "schedule.draft.create": ActionRisk("schedule.draft.create", "low", False, "schedule", ("request_id_supplied",)),
    "schedule.draft.update": ActionRisk("schedule.draft.update", "low", False, "schedule", ("request_id_supplied",)),
    "schedule.enable": ActionRisk("schedule.enable", "high", True, "schedule", _COMMON_AUDIT_FIELDS),
    "schedule.pause": ActionRisk("schedule.pause", "moderate", True, "schedule", _COMMON_AUDIT_FIELDS),
    "schedule.run_now": ActionRisk("schedule.run_now", "critical", True, "schedule", _COMMON_AUDIT_FIELDS),
    "schedule.delete": ActionRisk("schedule.delete", "high", True, "schedule", _COMMON_AUDIT_FIELDS),
    "plugin.install": ActionRisk("plugin.install", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.install_all": ActionRisk("plugin.install_all", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.load": ActionRisk("plugin.load", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.start": ActionRisk("plugin.start", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.stop": ActionRisk("plugin.stop", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.mount": ActionRisk("plugin.mount", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.unmount": ActionRisk("plugin.unmount", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.unload": ActionRisk("plugin.unload", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "plugin.lifecycle": ActionRisk("plugin.lifecycle", "critical", True, "runtime_plugin", (*_COMMON_AUDIT_FIELDS, "operation")),
    "mcp.register": ActionRisk("mcp.register", "moderate", False, "mcp_server", ("request_id_supplied", "configuration_saved")),
    "mcp.unregister": ActionRisk("mcp.unregister", "high", True, "mcp_server", _COMMON_AUDIT_FIELDS),
    "mcp.connect": ActionRisk("mcp.connect", "critical", True, "mcp_server", _COMMON_AUDIT_FIELDS),
    "memory.delete": ActionRisk("memory.delete", "high", True, "memory", _COMMON_AUDIT_FIELDS),
    "memory.update": ActionRisk("memory.update", "moderate", False, "memory", ("request_id_supplied", "value_changed", "importance_changed")),
    "artifact.capture": ActionRisk("artifact.capture", "moderate", False, "run_artifact", ("request_id_supplied", "source_kind", "source_bound", "redacted")),
    "artifact.delete": ActionRisk("artifact.delete", "high", True, "run_artifact", _COMMON_AUDIT_FIELDS),
    "collection.create": ActionRisk("collection.create", "low", False, "knowledge_collection", ("request_id_supplied", "tag_count")),
    "collection.delete": ActionRisk("collection.delete", "high", True, "knowledge_collection", _COMMON_AUDIT_FIELDS),
    "collection.document.add": ActionRisk("collection.document.add", "moderate", True, "knowledge_collection", (*_COMMON_AUDIT_FIELDS, "document_bound")),
    "collection.document.remove": ActionRisk("collection.document.remove", "moderate", True, "knowledge_collection", (*_COMMON_AUDIT_FIELDS, "document_bound")),
    "plugin_profile.delete": ActionRisk("plugin_profile.delete", "high", True, "plugin_profile", _COMMON_AUDIT_FIELDS),
    "plugin_profile.create": ActionRisk("plugin_profile.create", "low", False, "plugin_profile", ("request_id_supplied", "plugin_count", "mcp_server_count")),
    "model_insight_preferences.update": ActionRisk("model_insight_preferences.update", "moderate", True, "model_insight_preference", (*_COMMON_AUDIT_FIELDS, "daily_budget_set", "weekly_budget_set", "price_count")),
    "platform.organization.create": ActionRisk("platform.organization.create", "low", False, "organization", ("name_present",)),
    "platform.project.create": ActionRisk("platform.project.create", "low", False, "api_project", ("environment",)),
    "platform.agent.bind": ActionRisk("platform.agent.bind", "moderate", False, "project_agent_binding", ("agent_bound",)),
    "platform.key.create": ActionRisk("platform.key.create", "high", False, "project_api_key", ("scope_count", "has_expiry")),
    "platform.key.revoke": ActionRisk("platform.key.revoke", "high", True, "project_api_key", ("confirmed",)),
    "platform.quota.update": ActionRisk("platform.quota.update", "high", False, "project_quota", ("max_concurrent_runs", "daily_token_limit", "monthly_token_limit", "per_run_token_limit")),
}


def action_risk(action: str) -> ActionRisk | None:
    """Return policy metadata for a registered action without mutating state."""
    return ACTION_RISKS.get(action)


def requires_confirmation(action: str) -> bool:
    """Return whether a registered action requires explicit user confirmation."""
    item = action_risk(action)
    return bool(item and item.requires_confirmation)
