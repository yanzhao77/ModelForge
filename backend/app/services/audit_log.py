"""Minimal redacted operation audit writer for user-initiated control-plane changes."""
from __future__ import annotations

import json
import uuid
from typing import Any

from core.action_risk import action_risk
from models.records import OperationAudit
from services.redaction import redact_data
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class AuditMetadataRejected(ValueError):
    """A control-plane audit summary contains fields outside its fixed policy."""

    def __init__(self, action: str, rejected_fields: set[str]):
        self.action = action
        self.rejected_fields = tuple(sorted(rejected_fields))
        super().__init__(f"Audit metadata rejected for action {action}")


class AuditPersistenceError(RuntimeError):
    """The caller cannot know whether a control-plane action and audit coordinated."""


def validate_control_plane_audit_metadata(action: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a fixed audit summary before any related runtime side effect."""
    risk = action_risk(action)
    supplied = metadata or {}
    if risk is None:
        raise AuditMetadataRejected(action, set(supplied))
    rejected = set(supplied) - set(risk.audit_fields)
    if rejected:
        raise AuditMetadataRejected(action, rejected)
    return supplied


def record_operation(
    db: Session,
    *,
    user_id: int,
    action: str,
    object_type: str,
    object_id: str,
    correlation_id: str,
    metadata: dict[str, Any] | None = None,
) -> OperationAudit:
    """Stage a redacted audit row in the caller's existing transaction."""
    item = OperationAudit(
        id=uuid.uuid4().hex,
        user_id=user_id,
        action=action[:100],
        object_type=object_type[:100],
        object_id=object_id[:255],
        correlation_id=correlation_id[:64],
        metadata_json=json.dumps(redact_data(metadata or {}), ensure_ascii=False),
    )
    db.add(item)
    return item


def record_control_plane_operation(
    db: Session,
    *,
    user_id: int,
    action: str,
    object_type: str,
    object_id: str,
    correlation_id: str,
    metadata: dict[str, Any] | None = None,
) -> OperationAudit:
    """Stage a control-plane audit row after enforcing its action-specific key allowlist.

    The caller owns the transaction boundary.  This function deliberately does
    not commit, launch work, or convert an audit failure into an execution
    success receipt.
    """
    supplied = validate_control_plane_audit_metadata(action, metadata)
    return record_operation(
        db,
        user_id=user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        correlation_id=correlation_id,
        metadata=supplied,
    )


def commit_control_plane_audit(db: Session) -> None:
    """Commit staged state and audit, reporting unknown durability without raw DB details."""
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AuditPersistenceError("control-plane audit durability is unknown") from exc
