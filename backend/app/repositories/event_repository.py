"""EventStore port adapter backed by SQLAlchemy (agent_events table, spec 30)."""
from __future__ import annotations

import datetime
import json
from typing import List

from core.database import SessionLocal
from models.records import AgentEventRecord
from runtime.events.types import AgentEvent


class SQLAlchemyEventStore:
    """Implements the runtime.EventStore protocol (spec 30: events persist to DB)."""

    @staticmethod
    def _to_event(row: AgentEventRecord) -> AgentEvent:
        return AgentEvent(
            id=str(row.id),
            run_id=row.run_id,
            event_type=row.event_type,
            sequence=row.sequence,
            timestamp=row.timestamp,
            payload=json.loads(row.payload) if row.payload else {},
            correlation_id=row.correlation_id,
        )

    def append(self, event: AgentEvent) -> None:
        with SessionLocal() as db:
            db.add(AgentEventRecord(
                run_id=event.run_id,
                event_type=event.event_type,
                sequence=event.sequence,
                timestamp=event.timestamp or datetime.datetime.utcnow(),
                payload=json.dumps(event.payload or {}, ensure_ascii=False),
                correlation_id=event.correlation_id,
            ))
            db.commit()

    def list(self, run_id: str, after_sequence: int = 0, limit: int = 1000) -> List[AgentEvent]:
        with SessionLocal() as db:
            rows = (
                db.query(AgentEventRecord)
                .filter(AgentEventRecord.run_id == run_id, AgentEventRecord.sequence > after_sequence)
                .order_by(AgentEventRecord.sequence.asc())
                .limit(limit)
                .all()
            )
            return [self._to_event(r) for r in rows]

    def last_sequence(self, run_id: str) -> int:
        with SessionLocal() as db:
            row = (
                db.query(AgentEventRecord)
                .filter(AgentEventRecord.run_id == run_id)
                .order_by(AgentEventRecord.sequence.desc())
                .first()
            )
            return row.sequence if row else 0

    def delete_older_than(self, days: int) -> int:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        with SessionLocal() as db:
            n = db.query(AgentEventRecord).filter(AgentEventRecord.timestamp < cutoff).delete()
            db.commit()
            return n