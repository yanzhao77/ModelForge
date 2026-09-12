"""Model metric buckets must persist, including the first record of an hour."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

_tmp_db = tempfile.mkdtemp(prefix="mf_metrics_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_db, "test.db")
os.environ.setdefault("JWT_SECRET", "model-metrics-test-secret-0123456789")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import models.records  # noqa: F401,E402  (register ORM tables)
from core.database import SessionLocal, init_db  # noqa: E402
from models.records import ModelMetricBucket, User  # noqa: E402
from services.model_metrics import ModelMetricRecorder  # noqa: E402

init_db()


def _user_id() -> int:
    """Foreign keys are enforced, so metrics need a real owning account."""
    db = SessionLocal()
    try:
        user = User(username=f"metrics-{uuid.uuid4().hex[:10]}", password_hash="hash")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


class _Status429(Exception):
    status_code = 429


def _rows(user_id: int) -> list[ModelMetricBucket]:
    db = SessionLocal()
    try:
        return db.query(ModelMetricBucket).filter_by(user_id=user_id).all()
    finally:
        db.close()


def test_first_success_writes_a_bucket():
    user_id = _user_id()
    ModelMetricRecorder.record(
        user_id=user_id,
        model="metrics-model",
        remote=False,
        latency_ms=12.5,
        success=True,
        token_usage={"input_tokens": 5, "output_tokens": 7},
    )

    rows = _rows(user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.request_count == 1
    assert row.success_count == 1
    assert row.input_tokens_estimate == 5
    assert row.output_tokens_estimate == 7
    assert row.latency_sum_ms == 12.5


def test_failures_are_classified_and_emission_is_idempotent():
    user_id = _user_id()
    for _ in range(2):
        ModelMetricRecorder.record(
            user_id=user_id,
            model="metrics-model",
            remote=True,
            latency_ms=5.0,
            success=False,
            error=_Status429("rate limited"),
            emission_key="run-1:2",
            run_id="run-1",
            state_version=2,
        )

    rows = _rows(user_id)
    assert len(rows) == 1
    # The second call replays the same terminal emission, so it is not counted.
    assert rows[0].request_count == 1
    assert rows[0].error_429_count == 1
