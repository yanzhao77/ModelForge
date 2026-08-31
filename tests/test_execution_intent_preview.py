"""Tests for execution_intent_preview module (DEV-006 coverage)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

_TEST_JWT_SECRET = "test-secret-key-for-intent-preview-tests-32bytes"

from services.execution_intent_preview import (
    _ALGORITHM,
    _PURPOSE,
    _SUMMARY_SCHEMA_VERSION,
    _digest,
    _safe_targets,
    _safe_version_bindings,
    check_execution_intent_preview,
    create_execution_intent_preview,
)


class TestExecutionIntentPreviewHelpers:
    """Test helper functions."""

    def test_digest_is_stable(self):
        """Test _digest returns stable hash."""
        value = {"a": 1, "b": [2, 3]}
        d1 = _digest(value)
        d2 = _digest(value)
        assert d1 == d2
        assert len(d1) == 64  # SHA256 hex

    def test_digest_order_independent(self):
        """Test _digest is order-independent for dicts."""
        v1 = {"a": 1, "b": 2}
        v2 = {"b": 2, "a": 1}
        assert _digest(v1) == _digest(v2)

    def test_safe_targets_valid(self):
        """Test _safe_targets with valid input."""
        targets = _safe_targets(["target1", "target2"])
        assert targets == ["target1", "target2"]

    def test_safe_targets_deduplicates(self):
        """Test _safe_targets deduplicates."""
        targets = _safe_targets(["target1", "target1", "target2"])
        assert targets == ["target1", "target2"]

    def test_safe_targets_empty_raises(self):
        """Test _safe_targets raises on empty."""
        with pytest.raises(ValueError, match="invalid preview target count"):
            _safe_targets([])

    def test_safe_targets_too_many_raises(self):
        """Test _safe_targets raises on too many targets."""
        targets = [f"t{i}" for i in range(51)]
        with pytest.raises(ValueError, match="invalid preview target count"):
            _safe_targets(targets)

    def test_safe_targets_invalid_id_raises(self):
        """Test _safe_targets raises on invalid ID."""
        with pytest.raises(ValueError, match="invalid preview target"):
            _safe_targets([""])
        with pytest.raises(ValueError, match="invalid preview target"):
            _safe_targets(["x" * 161])

    def test_safe_version_bindings_valid(self):
        """Test _safe_version_bindings with valid input."""
        targets = ["t1", "t2"]
        bindings, digest, complete, legacy_count, legacy_digest = _safe_version_bindings(
            targets, {"t1": 5, "t2": 3}, None
        )
        assert len(bindings) == 2
        assert bindings[0]["target"] == "t1"
        assert bindings[0]["expected_version"] == 5
        assert bindings[1]["target"] == "t2"
        assert bindings[1]["expected_version"] == 3
        assert complete is True
        assert legacy_count == 0

    def test_safe_version_bindings_legacy(self):
        """Test _safe_version_bindings with legacy expected_versions."""
        targets = ["t1", "t2"]
        bindings, digest, complete, legacy_count, legacy_digest = _safe_version_bindings(
            targets, None, [1, 2]
        )
        assert len(bindings) == 2
        assert all(b["expected_version"] is None for b in bindings)
        assert complete is False
        assert legacy_count == 2

    def test_safe_version_bindings_mixed(self):
        """Test _safe_version_bindings with both."""
        targets = ["t1", "t2"]
        bindings, digest, complete, legacy_count, legacy_digest = _safe_version_bindings(
            targets, {"t1": 5}, [1, 2]
        )
        assert bindings[0]["expected_version"] == 5
        assert bindings[1]["expected_version"] is None
        assert legacy_count == 2

    def test_safe_version_bindings_out_of_scope_raises(self):
        """Test _safe_version_bindings raises on unknown target."""
        targets = ["t1"]
        with pytest.raises(ValueError, match="out of scope"):
            _safe_version_bindings(targets, {"t2": 5}, None)

    def test_safe_version_bindings_too_many_raises(self):
        """Test _safe_version_bindings raises on too many."""
        targets = ["t1"]
        with pytest.raises(ValueError, match="too many target version bindings"):
            _safe_version_bindings(targets, {f"t{i}": i for i in range(51)}, None)

    def test_safe_version_bindings_legacy_too_many_raises(self):
        """Test _safe_version_bindings raises on too many legacy."""
        targets = ["t1"]
        with pytest.raises(ValueError, match="too many expected versions"):
            _safe_version_bindings(targets, None, list(range(51)))

    def test_safe_version_bindings_negative_version_raises(self):
        """Test _safe_version_bindings raises on negative version."""
        targets = ["t1"]
        with pytest.raises(ValueError, match="invalid expected version"):
            _safe_version_bindings(targets, {"t1": -1}, None)


class TestCreateExecutionIntentPreview:
    """Test create_execution_intent_preview function."""

    def test_create_preview_valid(self):
        """Test creating a valid preview."""
        result = create_execution_intent_preview(
            user_id=1,
            action="agent.run.create",
            target_ids=["run-1", "run-2"],
            expected_versions_by_target={"run-1": 5},
            ttl_seconds=300,
        )

        assert result["read_only"] is True
        assert result["execution_blocked"] is True
        assert result["requires_confirm"] is True
        assert "preview_token" in result
        assert "expires_at" in result
        assert "summary" in result
        assert "notice" in result

        # Verify summary structure
        summary = result["summary"]
        assert summary["schema_version"] == _SUMMARY_SCHEMA_VERSION
        assert summary["action"] == "agent.run.create"
        assert summary["target_count"] == 2
        assert "target_digest" in summary
        assert "target_version_binding_digest" in summary
        assert "target_version_binding_complete" in summary
        assert summary["legacy_expected_version_count"] == 0

    def test_create_preview_with_legacy_versions(self):
        """Test creating preview with legacy expected_versions."""
        result = create_execution_intent_preview(
            user_id=1,
            action="agent.run.create",
            target_ids=["run-1"],
            expected_versions=[5],
            ttl_seconds=300,
        )

        summary = result["summary"]
        assert summary["legacy_expected_version_count"] == 1
        assert "legacy_expected_version_digest" in summary

    def test_create_preview_invalid_action_raises(self):
        """Test invalid action raises."""
        with pytest.raises(ValueError, match="unsupported execution-intent preview action"):
            create_execution_intent_preview(
                user_id=1,
                action="invalid.action",
                target_ids=["t1"],
            )

    def test_create_preview_no_confirm_action_raises(self):
        """Test action without confirmation requirement raises."""
        with pytest.raises(ValueError, match="unsupported execution-intent preview action"):
            create_execution_intent_preview(
                user_id=1,
                action="agent.create",  # Doesn't require confirmation
                target_ids=["t1"],
            )

    def test_create_preview_invalid_targets_raises(self):
        """Test invalid targets raise."""
        with pytest.raises(ValueError, match="invalid preview target"):
            create_execution_intent_preview(
                user_id=1,
                action="agent.run.create",
                target_ids=[""],
            )

    def test_create_preview_ttl_clamped(self):
        """Test TTL is clamped to 60-900 seconds."""
        # TTL too low
        result = create_execution_intent_preview(
            user_id=1,
            action="agent.run.create",
            target_ids=["t1"],
            ttl_seconds=10,
        )
        # Should be clamped to 60
        from core.config import settings
        claims = jwt.decode(result["preview_token"], settings.jwt_secret, algorithms=[_ALGORITHM])
        assert claims["exp"] - claims["iat"] == 60

        # TTL too high
        result = create_execution_intent_preview(
            user_id=1,
            action="agent.run.create",
            target_ids=["t1"],
            ttl_seconds=10000,
        )
        claims = jwt.decode(result["preview_token"], settings.jwt_secret, algorithms=[_ALGORITHM])
        assert claims["exp"] - claims["iat"] == 900

    def test_preview_token_contains_claims(self):
        """Test preview token contains expected claims."""
        result = create_execution_intent_preview(
            user_id=42,
            action="agent.run.create",
            target_ids=["t1"],
            ttl_seconds=300,
        )

        from core.config import settings
        claims = jwt.decode(result["preview_token"], settings.jwt_secret, algorithms=[_ALGORITHM])
        assert claims["purpose"] == _PURPOSE
        assert claims["schema_version"] == _SUMMARY_SCHEMA_VERSION
        assert claims["sub"] == "42"
        assert claims["action"] == "agent.run.create"
        assert claims["target_count"] == 1


class TestCheckExecutionIntentPreview:
    """Test check_execution_intent_preview function."""

    def create_token(self, user_id=1, action="agent.run.create", expired=False, wrong_user=False, wrong_action=False):
        """Helper to create a test token."""
        claims = {
            "purpose": _PURPOSE,
            "schema_version": _SUMMARY_SCHEMA_VERSION,
            "sub": str(999 if wrong_user else user_id),
            "action": "wrong.action" if wrong_action else action,
            "risk_tier": "critical",
            "object_type": "agent_run",
            "target_count": 1,
            "target_digest": "abc",
            "target_version_binding_digest": "def",
            "target_version_binding_complete": False,
        }
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        if expired:
            claims["exp"] = now - dt.timedelta(seconds=10)
        else:
            claims["exp"] = now + dt.timedelta(seconds=300)
        claims["iat"] = now
        return jwt.encode(claims, _TEST_JWT_SECRET, algorithm=_ALGORITHM)

    def test_check_valid_confirm(self):
        """Test checking valid token with confirmation."""
        token = self.create_token()
        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is True
        assert result["execution_blocked"] is True
        assert result["code"] == "EXECUTION_INTENT_EXECUTION_DISABLED"
        assert "summary" in result

    def test_check_no_confirm_raises(self):
        """Test without confirmation returns error."""
        token = self.create_token()
        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=False,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_CONFIRMATION_REQUIRED"

    def test_check_expired_token(self):
        """Test expired token returns error."""
        token = self.create_token(expired=True)
        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_PREVIEW_EXPIRED"

    def test_check_invalid_token(self):
        """Test invalid token returns error."""
        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token="invalid.token",
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_PREVIEW_INVALID"

    def test_check_wrong_purpose(self):
        """Test token with wrong purpose."""
        token = self.create_token()
        # Decode and modify
        claims = jwt.decode(token, _TEST_JWT_SECRET, algorithms=[_ALGORITHM])
        claims["purpose"] = "wrong"
        token = jwt.encode(claims, _TEST_JWT_SECRET, algorithm=_ALGORITHM)

        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_PREVIEW_SCHEMA_MISMATCH"

    def test_check_wrong_user(self):
        """Test token for different user."""
        token = self.create_token(wrong_user=True)
        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_PREVIEW_SCOPE_MISMATCH"

    def test_check_wrong_action(self):
        """Test token for different action."""
        token = self.create_token(wrong_action=True)
        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_PREVIEW_ACTION_MISMATCH"

    def test_check_wrong_schema_version(self):
        """Test token with wrong schema version."""
        token = self.create_token()
        claims = jwt.decode(token, _TEST_JWT_SECRET, algorithms=[_ALGORITHM])
        claims["schema_version"] = 999
        token = jwt.encode(claims, _TEST_JWT_SECRET, algorithm=_ALGORITHM)

        with patch("services.execution_intent_preview.settings") as mock_settings:
            mock_settings.jwt_secret = _TEST_JWT_SECRET
            result = check_execution_intent_preview(
                token=token,
                user_id=1,
                action="agent.run.create",
                confirm=True,
            )
        assert result["confirmation_valid"] is False
        assert result["code"] == "EXECUTION_INTENT_PREVIEW_SCHEMA_MISMATCH"