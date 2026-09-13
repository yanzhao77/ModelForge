"""Observability / evaluation / security API (V1.8)."""

from __future__ import annotations

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, Query
from models.records import User
from pydantic import BaseModel, Field
from services.audit_log import record_operation
from services.evaluation_service import EvaluationError, EvaluationService
from services.observability_service import ObservabilityService
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["observability"])


class EvaluationCase(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    input: str = Field(min_length=1, max_length=20000)
    expected: str | None = Field(default=None, max_length=2000)
    expect_json: bool = False
    input_payload: dict | None = None


class EvaluationDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    cases: list[EvaluationCase] = Field(min_length=1, max_length=200)


class EvaluationRunRequest(BaseModel):
    target_kind: str = Field(default="agent", max_length=16)
    target_id: str = Field(min_length=1, max_length=160)
    timeout_seconds: float = Field(default=60.0, ge=0.1, le=1800)


class EvaluationCompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=8)


def _evaluations(db: DBSession) -> EvaluationService:
    return EvaluationService(db)


def _evaluation_problem(exc: EvaluationError, corr: str):
    return problem(
        exc.http_status, exc.code, exc.message, correlation=corr, details=exc.details or None
    )


@router.get("/traces")
def list_traces(
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Agent + Workflow runs as one trace index."""
    return {"traces": ObservabilityService(db).list_traces(user.id, kind=kind, limit=limit)}


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    document = ObservabilityService(db).get_trace(user.id, trace_id)
    if document is None:
        raise problem(
            404, "TRACE_NOT_FOUND", "Trace not found.", correlation=correlation_id(), details={"trace_id": trace_id}
        )
    return document


@router.get("/metrics/overview")
def metrics_overview(
    limit: int = Query(default=50, ge=1, le=500),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Aggregate model metrics (latency, tokens/sec) for the caller."""
    return ObservabilityService(db).metrics_overview(user.id, limit=limit)


@router.get("/metrics/resources")
def metrics_resources(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    del db, user
    return ObservabilityService.__new__(ObservabilityService).resource_metrics()


@router.get("/security/secrets")
def secret_backend_status(user: User = Depends(get_current_user)):
    """Report the active secret backend; secret values are never returned."""
    del user
    from core.secret_store import get_secret_store

    store = get_secret_store()
    return {
        **store.describe(),
        "provider_credentials": "encrypted-at-rest (Fernet, owner-only key file)",
        "redaction": "request/response logging redacts keys, tokens and prompts",
    }


@router.get("/evaluations")
def list_evaluations(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return {"evaluations": _evaluations(db).list_datasets(user.id)}


@router.post("/evaluations")
def create_evaluation(
    req: EvaluationDatasetRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    corr = correlation_id()
    try:
        dataset = _evaluations(db).create_dataset(
            user.id, req.name, [case.model_dump() for case in req.cases], req.description
        )
    except EvaluationError as exc:
        raise _evaluation_problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="evaluation.create", object_type="evaluation",
        object_id=dataset["evaluation_id"], correlation_id=corr,
        metadata={"case_count": dataset["case_count"]},
    )
    db.commit()
    return operation_result(dataset, corr)


@router.get("/evaluations/runs")
def list_evaluation_runs(
    evaluation_id: str | None = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"runs": _evaluations(db).list_runs(user.id, evaluation_id)}


@router.post("/evaluations/{evaluation_id}/runs")
async def start_evaluation_run(
    evaluation_id: str,
    req: EvaluationRunRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run an evaluation: each case starts a background run and is then scored."""
    corr = correlation_id()
    try:
        result = await _evaluations(db).start_run(
            user.id,
            evaluation_id,
            target_kind=req.target_kind,
            target_id=req.target_id,
            timeout_seconds=req.timeout_seconds,
        )
    except EvaluationError as exc:
        raise _evaluation_problem(exc, corr) from exc
    record_operation(
        db, user_id=user.id, action="evaluation.run", object_type="evaluation_run",
        object_id=result["run_id"], correlation_id=corr,
        metadata={"target_kind": req.target_kind},
    )
    db.commit()
    return operation_result(result, corr)


@router.get("/evaluations/runs/{run_id}")
def get_evaluation_run(
    run_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return _evaluations(db).require_run(user.id, run_id).to_dict()
    except EvaluationError as exc:
        raise _evaluation_problem(exc, correlation_id()) from exc


@router.post("/evaluations/compare")
def compare_evaluations(
    req: EvaluationCompareRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return _evaluations(db).compare(user.id, req.run_ids)
    except EvaluationError as exc:
        raise _evaluation_problem(exc, correlation_id()) from exc


@router.get("/evaluations/{evaluation_id}")
def get_evaluation(
    evaluation_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return _evaluations(db).require_dataset(user.id, evaluation_id).to_dict()
    except EvaluationError as exc:
        raise _evaluation_problem(exc, correlation_id()) from exc


@router.delete("/evaluations/{evaluation_id}")
def delete_evaluation(
    evaluation_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        _evaluations(db).delete_dataset(user.id, evaluation_id)
    except EvaluationError as exc:
        raise _evaluation_problem(exc, correlation_id()) from exc
    return {"ok": True, "evaluation_id": evaluation_id}
