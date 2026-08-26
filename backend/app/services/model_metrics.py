"""Privacy-preserving, best-effort persistence for per-user model aggregates."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from core.database import SessionLocal
from models.records import ModelInsightPreference, ModelMetricBucket, RunMetricEmission
from sqlalchemy.exc import IntegrityError


def model_ref(model: object, *, remote: bool = False) -> str:
    """Return a non-secret aggregate key; provider URLs and credentials never enter it."""
    return ("remote:" if remote else "local:") + str(model or "unknown")[:240]


def _bucket_start(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.utcnow()
    return now.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def _tokens(value: Any) -> tuple[int, int]:
    raw = value if isinstance(value, dict) else {}
    input_tokens = raw.get("input_tokens", raw.get("prompt_tokens", raw.get("prompt", 0)))
    output_tokens = raw.get("output_tokens", raw.get("completion_tokens", raw.get("completion", 0)))
    try:
        return max(0, int(input_tokens or 0)), max(0, int(output_tokens or 0))
    except (TypeError, ValueError):
        return 0, 0


def _error_kind(error: BaseException | object | None) -> str:
    if error is None:
        return ""
    status = getattr(getattr(error, "response", None), "status_code", None) or getattr(error, "status_code", None)
    if status == 429:
        return "429"
    if isinstance(status, int) and 400 <= status < 500:
        return "4xx"
    if isinstance(status, int) and status >= 500:
        return "5xx"
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "timeout"
    return "5xx" if "provider" in name else "4xx"


class ModelMetricRecorder:
    """Writes aggregate buckets in an isolated DB session and swallows failures."""

    @staticmethod
    def record(
        *,
        user_id: int | None,
        model: object,
        remote: bool,
        latency_ms: float,
        success: bool,
        token_usage: dict[str, Any] | None = None,
        error: BaseException | object | None = None,
        emission_key: str | None = None,
        run_id: str | None = None,
        state_version: int | None = None,
    ) -> None:
        if user_id is None:
            return
        db = SessionLocal()
        try:
            if emission_key:
                emission = RunMetricEmission(
                    id=uuid.uuid4().hex,
                    emission_key=emission_key[:160],
                    run_id=(run_id or "")[:64],
                    state_version=max(1, int(state_version or 1)),
                    user_id=user_id,
                )
                db.add(emission)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    return
            ref = model_ref(model, remote=remote)
            start = _bucket_start()
            row = (
                db.query(ModelMetricBucket)
                .filter(ModelMetricBucket.user_id == user_id, ModelMetricBucket.model_ref == ref, ModelMetricBucket.bucket_start == start)
                .one_or_none()
            )
            if row is None:
                row = ModelMetricBucket(id=uuid.uuid4().hex, user_id=user_id, model_ref=ref, bucket_start=start)
                db.add(row)
            input_tokens, output_tokens = _tokens(token_usage)
            row.request_count += 1
            row.latency_sum_ms += max(0.0, float(latency_ms or 0.0))
            row.input_tokens_estimate += input_tokens
            row.output_tokens_estimate += output_tokens
            if success:
                row.success_count += 1
            else:
                kind = _error_kind(error)
                if kind == "429":
                    row.error_429_count += 1
                elif kind == "timeout":
                    row.timeout_count += 1
                elif kind == "5xx":
                    row.error_5xx_count += 1
                else:
                    row.error_4xx_count += 1
            preference = db.query(ModelInsightPreference).filter(ModelInsightPreference.user_id == user_id).one_or_none()
            if preference is not None:
                row.cost_estimate += preference.estimate_cost(ref, input_tokens, output_tokens)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
