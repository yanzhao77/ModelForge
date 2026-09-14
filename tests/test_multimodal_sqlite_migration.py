from __future__ import annotations

import datetime as dt
import io
import os
import sys
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core import database as database_module  # noqa: E402
from models.records import (  # noqa: E402
    ChatAttemptRecord,
    ChatEventRecord,
    ChatTurnRecord,
    Message,
    MessageAttachment,
    Session,
    User,
)
from services.attachment_service import AttachmentError, AttachmentService  # noqa: E402
from services.chat_turn_service import ChatTurnService  # noqa: E402

from models import records as _records  # noqa: E402,F401


def test_sqlite_multimodal_migration_updates_legacy_messages_table(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER,
                    role VARCHAR(20),
                    content TEXT,
                    timestamp DATETIME
                )
                """
            )
        )

    database_module.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database_module, "engine", engine)

    database_module._apply_schema_migrations()
    database_module._apply_schema_migrations()

    with engine.connect() as conn:
        message_columns = {row._mapping["name"] for row in conn.execute(text("PRAGMA table_info(messages)"))}
        assert {"schema_version", "parts_json", "status", "turn_id", "parent_message_id", "is_pinned", "pinned_at"}.issubset(message_columns)

        tables = {row._mapping["name"] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
        assert {"attachments", "attachment_derivatives", "message_attachments", "chat_turns", "chat_attempts", "chat_events", "artifacts", "artifact_versions"}.issubset(tables)

        indexes = {row._mapping["name"] for row in conn.execute(text("PRAGMA index_list(chat_turns)"))}
        assert "uq_chat_turn_user_idempotency" in indexes

        applied = {row._mapping["version"] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        assert "0008_multimodal_chat_foundation" in applied
        assert "0009_chat_message_pin_search" in applied


def test_attachment_storage_reconcile_reports_orphans_and_expired_tmp(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'attachments.db'}")
    database_module.Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    service = AttachmentService(root=tmp_path / "data", max_bytes=1024 * 1024)
    with session_factory() as db:
        user = User(username="owner", password_hash="hash", email="owner@example.test")
        db.add(user)
        db.commit()
        db.refresh(user)

        rec = service.upload_stream(db, user.id, "known.txt", io.BytesIO(b"hello"), "text/plain")
        known_path = service.path_for(rec)
        assert known_path.exists()

        orphan = service.root / str(user.id) / "att_orphan" / "original"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"orphan")

        expired_tmp = service.root / str(user.id) / "att_tmp" / "tmp" / "upload.part"
        expired_tmp.parent.mkdir(parents=True)
        expired_tmp.write_bytes(b"partial")
        old = time.time() - 120
        os.utime(expired_tmp, (old, old))

        report = service.reconcile_storage(db, max_tmp_age_seconds=1)
        assert str(orphan.relative_to(service.root.parent)) in report["orphan_files"]
        assert str(expired_tmp.relative_to(service.root.parent)) in report["expired_temporary_files"]
        assert rec.storage_key not in report["orphan_files"]
        assert report["missing_files"] == []


def test_attachment_delete_blocks_active_turn_and_cleanup_skips_referenced_files(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}")
    database_module.Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    service = AttachmentService(root=tmp_path / "data", max_bytes=1024 * 1024)
    with session_factory() as db:
        user = User(username="owner", password_hash="hash", email="owner2@example.test")
        db.add(user)
        db.commit()
        db.refresh(user)

        rec = service.upload_stream(db, user.id, "known.txt", io.BytesIO(b"hello"), "text/plain")
        session = Session(user_id=user.id, title="mm")
        db.add(session)
        db.flush()
        turn = ChatTurnRecord(
            id="turn_active",
            user_id=user.id,
            session_id=session.id,
            idempotency_key="idem-active",
            request_hash="abc",
            status="RUNNING",
            mode="chat",
            created_at=dt.datetime.utcnow(),
            updated_at=dt.datetime.utcnow(),
        )
        db.add(turn)
        db.flush()
        message = Message(session_id=session.id, role="user", content="file", turn_id=turn.id, status="completed")
        db.add(message)
        db.flush()
        db.add(MessageAttachment(message_id=message.id, attachment_id=rec.id))
        db.commit()

        summary = service.reference_summary(db, user.id, rec.id)
        assert summary["blocks_delete"] is True
        assert summary["active_turns"][0]["turn_id"] == "turn_active"

        with pytest.raises(AttachmentError) as raised:
            service.delete(db, user.id, rec.id)
        assert raised.value.code == "ATTACHMENT_IN_USE"

        turn.status = "SUCCEEDED"
        turn.finished_at = dt.datetime.utcnow()
        db.commit()
        deleted = service.delete(db, user.id, rec.id)
        assert deleted["references"]["message_count"] == 1
        assert service.path_for(rec).exists()

        cleanup = service.cleanup_unreferenced_deleted(db, user_id=user.id)
        assert cleanup["deleted_files"] == []
        assert cleanup["skipped"] == [{"attachment_id": rec.id, "reason": "REFERENCED_BY_MESSAGE", "message_count": 1}]


def test_chat_turn_startup_reconcile_settles_active_turns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat-recovery.db'}")
    database_module.Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        user = User(username="owner", password_hash="hash", email="owner3@example.test")
        db.add(user)
        db.commit()
        db.refresh(user)

        now = dt.datetime.utcnow()
        turns = [
            ChatTurnRecord(
                id="turn_cancel_requested",
                user_id=user.id,
                idempotency_key="idem-cancel",
                request_hash="abc",
                status="CANCEL_REQUESTED",
                mode="chat",
                created_at=now,
                updated_at=now,
            ),
            ChatTurnRecord(
                id="turn_running",
                user_id=user.id,
                idempotency_key="idem-running",
                request_hash="def",
                status="RUNNING",
                mode="chat",
                created_at=now,
                updated_at=now,
            ),
            ChatTurnRecord(
                id="turn_done",
                user_id=user.id,
                idempotency_key="idem-done",
                request_hash="ghi",
                status="SUCCEEDED",
                mode="chat",
                created_at=now,
                updated_at=now,
                finished_at=now,
            ),
        ]
        db.add_all(turns)
        db.add_all(
            [
                ChatAttemptRecord(id="attempt_cancel", turn_id="turn_cancel_requested", attempt_no=1, status="RUNNING", created_at=now),
                ChatAttemptRecord(id="attempt_running", turn_id="turn_running", attempt_no=1, status="WAITING_INPUT", created_at=now),
                ChatAttemptRecord(id="attempt_done", turn_id="turn_done", attempt_no=1, status="SUCCEEDED", created_at=now, finished_at=now),
            ]
        )
        db.commit()

        report = ChatTurnService().reconcile_orphaned_turns(db)
        assert report == {"settled": 2, "cancelled": 1, "interrupted": 1, "attempts": 2}

        cancelled = db.query(ChatTurnRecord).filter_by(id="turn_cancel_requested").one()
        interrupted = db.query(ChatTurnRecord).filter_by(id="turn_running").one()
        completed = db.query(ChatTurnRecord).filter_by(id="turn_done").one()
        assert cancelled.status == "CANCELLED"
        assert cancelled.finished_at is not None
        assert interrupted.status == "INTERRUPTED"
        assert interrupted.finished_at is not None
        assert completed.status == "SUCCEEDED"

        cancel_attempt = db.query(ChatAttemptRecord).filter_by(id="attempt_cancel").one()
        running_attempt = db.query(ChatAttemptRecord).filter_by(id="attempt_running").one()
        done_attempt = db.query(ChatAttemptRecord).filter_by(id="attempt_done").one()
        assert cancel_attempt.status == "CANCELLED"
        assert cancel_attempt.error_code == "CHAT_TURN_CANCELLED"
        assert running_attempt.status == "INTERRUPTED"
        assert running_attempt.error_code == "CHAT_TURN_STARTUP_RECONCILIATION"
        assert done_attempt.status == "SUCCEEDED"

        events = db.query(ChatEventRecord).order_by(ChatEventRecord.turn_id.asc()).all()
        assert [(event.turn_id, event.type) for event in events] == [
            ("turn_cancel_requested", "turn.finished"),
            ("turn_running", "turn.finished"),
        ]
        assert ChatTurnService().reconcile_orphaned_turns(db) == {"settled": 0, "cancelled": 0, "interrupted": 0, "attempts": 0}
