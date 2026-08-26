"""Minimal redacted operation audit writer for user-initiated control-plane changes."""
from __future__ import annotations

import json
import uuid
from typing import Any

from models.records import OperationAudit
from services.redaction import redact_data
from sqlalchemy.orm import Session


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
