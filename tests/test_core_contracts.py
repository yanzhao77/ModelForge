"""Tests for core contract, error, risk, and resource-access modules (DEV-006)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.action_risk import ACTION_RISKS, action_risk, requires_confirmation
from core.api_contracts import correlation_id, operation_result, problem
from core.concurrency_migration_contract import (
    CONCURRENCY_SCHEMA_REQUIREMENTS,
    concurrency_schema_requirements,
)
from core.control_plane_contracts import (
    CONTROL_PLANE_CONTRACTS,
    contract_references_are_known,
    control_plane_contract,
)
from core.control_plane_coordination import (
    COORDINATION_BOUNDARIES,
    coordination_boundary,
    safe_coordination_receipt,
)
from core.control_plane_errors import ERROR_CATALOG, control_plane_error
from core.resource_access import (
    RESOURCE_ACCESS_POLICIES,
    resource_access_policy,
    resource_conflict_problem,
    unavailable_resource_problem,
)

# ── action_risk ──────────────────────────────────────────────────────────────

class TestActionRisk:
    def test_all_registered_actions_have_risk(self):
        assert len(ACTION_RISKS) > 0
        for action, risk in ACTION_RISKS.items():
            assert risk.action == action
            assert risk.tier in ("low", "moderate", "high", "critical")

    def test_lookup_known_action(self):
        risk = action_risk("agent.run.create")
        assert risk is not None
        assert risk.tier == "critical"
        assert risk.requires_confirmation is True

    def test_lookup_unknown_action(self):
        assert action_risk("nonexistent.action") is None

    def test_requires_confirmation_true(self):
        assert requires_confirmation("agent.run.create") is True
        assert requires_confirmation("task.retry") is True

    def test_requires_confirmation_false(self):
        assert requires_confirmation("agent.create") is False
        assert requires_confirmation("nonexistent") is False


# ── control_plane_errors ─────────────────────────────────────────────────────

class TestControlPlaneErrors:
    def test_all_errors_have_required_fields(self):
        for code, err in ERROR_CATALOG.items():
            assert err.code == code
            assert 100 <= err.http_status < 600
            assert isinstance(err.retryable, bool)

    def test_lookup_known_error(self):
        err = control_plane_error("AGENT_RUN_CONFIRMATION_REQUIRED")
        assert err is not None
        assert err.http_status == 409
        assert err.retryable is False

    def test_lookup_unknown_error(self):
        assert control_plane_error("NONEXISTENT_ERROR") is None

    def test_forbidden_fields_present(self):
        for err in ERROR_CATALOG.values():
            assert isinstance(err.forbidden_fields, tuple)
            assert len(err.forbidden_fields) > 0


# ── control_plane_contracts ──────────────────────────────────────────────────

class TestControlPlaneContracts:
    def test_all_contracts_have_required_fields(self):
        for action, contract in CONTROL_PLANE_CONTRACTS.items():
            assert contract.action == action
            assert contract.ownership_scope in ("current_user", "administrator", "configuration_only")

    def test_lookup_known_contract(self):
        c = control_plane_contract("agent.run.create")
        assert c is not None
        assert c.confirmation_error_code == "AGENT_RUN_CONFIRMATION_REQUIRED"
        assert c.preview_supported is True

    def test_lookup_unknown_contract(self):
        assert control_plane_contract("nonexistent") is None

    def test_contract_references_are_known_for_all(self):
        for action, contract in CONTROL_PLANE_CONTRACTS.items():
            assert contract_references_are_known(contract), f"broken reference in {action}"

    def test_admin_scoped_actions(self):
        admin_actions = [a for a, c in CONTROL_PLANE_CONTRACTS.items() if c.ownership_scope == "administrator"]
        assert "plugin.lifecycle" in admin_actions
        assert "mcp.connect" in admin_actions
        assert "mcp.unregister" in admin_actions


# ── control_plane_coordination ───────────────────────────────────────────────

class TestControlPlaneCoordination:
    def test_all_boundaries_have_valid_kind(self):
        valid_kinds = {"same_session_persistence", "post_commit_dispatch", "independent_runtime_side_effect", "read_only"}
        for action, boundary in COORDINATION_BOUNDARIES.items():
            assert boundary.kind in valid_kinds, f"{action} has invalid kind"

    def test_lookup_known_boundary(self):
        b = coordination_boundary("agent.run.create")
        assert b is not None
        assert b.kind == "post_commit_dispatch"
        assert b.success_receipt == "accepted"

    def test_lookup_unknown_boundary(self):
        assert coordination_boundary("nonexistent") is None

    def test_receipt_for_known_action(self):
        receipt = safe_coordination_receipt("agent.run.create", correlation_id="test-123")
        assert receipt["action"] == "agent.run.create"
        assert receipt["coordination"] == "post_commit_dispatch"
        assert receipt["correlation_id"] == "test-123"
        assert receipt["safe_to_replay"] is False

    def test_receipt_for_unknown_action(self):
        receipt = safe_coordination_receipt("nonexistent", correlation_id="test-456")
        assert receipt["action"] == "nonexistent"
        assert receipt["coordination"] == "unclassified"
        assert receipt["receipt"] == "durability_unknown"

    def test_receipt_with_uncertainty(self):
        receipt = safe_coordination_receipt("agent.run.create", correlation_id="test-unc", uncertainty=True)
        assert receipt["receipt"] == "durability_unknown"

    def test_read_only_boundary_has_no_uncertainty_receipt(self):
        b = coordination_boundary("execution_intent.preview")
        assert b is not None
        assert b.uncertainty_receipt is None


# ── resource_access ──────────────────────────────────────────────────────────

class TestResourceAccess:
    def test_all_policies_have_valid_scope(self):
        valid_scopes = {"current_user", "runtime_administrator"}
        for resource, policy in RESOURCE_ACCESS_POLICIES.items():
            assert policy.ownership_scope in valid_scopes, f"{resource} invalid scope"

    def test_lookup_known_policy(self):
        p = resource_access_policy("agent_run")
        assert p is not None
        assert p.ownership_scope == "current_user"
        assert p.unavailable_code == "AGENT_RUN_UNAVAILABLE"

    def test_lookup_unknown_policy(self):
        assert resource_access_policy("nonexistent") is None

    def test_unavailable_problem_for_known_resource(self):
        exc = unavailable_resource_problem("agent_run", correlation="corr-1")
        assert exc.status_code == 404
        detail = exc.detail
        assert detail["code"] == "AGENT_RUN_UNAVAILABLE"
        assert detail["correlation_id"] == "corr-1"

    def test_unavailable_problem_for_unknown_resource(self):
        exc = unavailable_resource_problem("nonexistent", correlation="corr-2")
        assert exc.status_code == 404
        assert exc.detail["code"] == "CONTROL_RESOURCE_UNAVAILABLE"

    def test_conflict_problem_for_known_resource(self):
        exc = resource_conflict_problem("task", correlation="corr-3")
        assert exc.status_code == 409
        assert exc.detail["code"] == "TASK_VERSION_CONFLICT"

    def test_conflict_problem_for_unknown_resource(self):
        exc = resource_conflict_problem("nonexistent", correlation="corr-4")
        assert exc.status_code == 409
        assert exc.detail["code"] == "CONTROL_RESOURCE_CONFLICT"

    def test_conflict_problem_for_resource_without_conflict_code(self):
        exc = resource_conflict_problem("agent_run", correlation="corr-5")
        assert exc.status_code == 409
        assert exc.detail["code"] == "CONTROL_RESOURCE_CONFLICT"


# ── concurrency_migration_contract ───────────────────────────────────────────

class TestConcurrencyMigrationContract:
    def test_requirements_are_populated(self):
        reqs = concurrency_schema_requirements()
        assert len(reqs) == len(CONCURRENCY_SCHEMA_REQUIREMENTS)
        assert len(reqs) >= 5

    def test_all_requirements_have_required_fields(self):
        for req in concurrency_schema_requirements():
            assert req.key
            assert req.table
            assert req.state
            assert len(req.columns) > 0
            assert len(req.uniqueness) > 0
            assert req.compatibility
            assert req.no_go

    def test_unique_keys(self):
        keys = [r.key for r in concurrency_schema_requirements()]
        assert len(keys) == len(set(keys))


# ── api_contracts ────────────────────────────────────────────────────────────

class TestApiContracts:
    def test_correlation_id_unique(self):
        ids = {correlation_id() for _ in range(100)}
        assert len(ids) == 100

    def test_problem_returns_http_exception(self):
        exc = problem(400, "TEST_CODE", "test message", correlation="abc")
        assert exc.status_code == 400
        assert exc.detail["code"] == "TEST_CODE"
        assert exc.detail["message"] == "test message"
        assert exc.detail["correlation_id"] == "abc"

    def test_problem_auto_generates_correlation(self):
        exc = problem(500, "X", "Y")
        assert len(exc.detail["correlation_id"]) == 32

    def test_operation_result(self):
        result = operation_result({"run_id": "123"}, "corr-xyz")
        assert result["run_id"] == "123"
        assert result["correlation_id"] == "corr-xyz"
