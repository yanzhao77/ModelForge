"""User-controlled APIs for artifacts, knowledge collections, extensions and model insights."""
from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Literal

from core.api_contracts import correlation_id, operation_result, problem
from core.database import get_db
from core.security import get_current_user, get_runtime_admin
from fastapi import APIRouter, Depends
from models.records import (
    AgentRun,
    KnowledgeCollection,
    KnowledgeCollectionDocument,
    KnowledgeDocument,
    ModelInsightPreference,
    ModelMetricBucket,
    OperationAudit,
    PluginProfile,
    RunArtifact,
    TaskRecord,
    User,
)
from pydantic import BaseModel, Field
from services.audit_log import (
    AuditMetadataRejected,
    AuditPersistenceError,
    commit_control_plane_audit,
    record_control_plane_operation,
    record_operation,
    validate_control_plane_audit_metadata,
)
from services.control_plane_budget import control_plane_budget_summary
from services.execution_intent_preview import (
    check_execution_intent_preview,
    create_execution_intent_preview,
)
from services.lifecycle_diagnostics import lifecycle_diagnostics
from services.lifecycle_preview import (
    check_lifecycle_confirmation,
    create_lifecycle_preview,
)
from services.migration_preflight import migration_preflight
from services.redaction import redact_data, redact_text
from services.runtime_diagnostics import runtime_diagnostics
from sqlalchemy.orm import Session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/migration-preflight")
async def get_migration_preflight(_admin: User = Depends(get_runtime_admin)):
    """Return read-only migration diagnostics for a runtime administrator."""
    return migration_preflight()


@router.get("/runtime-diagnostics")
async def get_runtime_diagnostics(
    db: Session = Depends(get_db), _admin: User = Depends(get_runtime_admin)
):
    """Return content-free C3/D4 diagnostics for a runtime administrator."""
    return runtime_diagnostics(db)


@router.get("/lifecycle-diagnostics")
async def get_lifecycle_diagnostics(
    retention_days: int = 30,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_runtime_admin),
):
    """Return lifecycle and retention diagnostics without performing recovery."""
    return lifecycle_diagnostics(db, retention_days=retention_days)


@router.get("/operation-audits")
async def list_operation_audits(
    limit: int = 100,
    user_id: int | None = None,
    action: str | None = None,
    correlation: str | None = None,
    before: datetime.datetime | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_runtime_admin),
):
    """List redacted control-plane audit headers without metadata or request bodies."""
    safe_limit = max(1, min(int(limit), 200))
    query = db.query(OperationAudit)
    if user_id is not None:
        query = query.filter(OperationAudit.user_id == user_id)
    if action:
        query = query.filter(OperationAudit.action == action[:100])
    if correlation:
        query = query.filter(OperationAudit.correlation_id == correlation[:64])
    if before is not None:
        query = query.filter(OperationAudit.created_at < before)
    rows = query.order_by(OperationAudit.created_at.desc(), OperationAudit.id.desc()).limit(safe_limit + 1).all()
    page = rows[:safe_limit]
    return {
        "items": [
            {
                "id": item.id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "user_id": item.user_id,
                "action": item.action,
                "object_type": item.object_type,
                "object_id": item.object_id,
                "correlation_id": item.correlation_id,
            }
            for item in page
        ],
        "limit": safe_limit,
        "has_more": len(rows) > safe_limit,
        "next_before": page[-1].created_at.isoformat() if len(rows) > safe_limit and page[-1].created_at else None,
        "read_only": True,
        "metadata_included": False,
    }


@router.post("/lifecycle-preview")
async def get_lifecycle_preview(
    req: LifecyclePreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_runtime_admin),
):
    """Create a short-lived, read-only lifecycle preview token for an administrator."""
    corr = req.request_id or correlation_id()
    result = create_lifecycle_preview(
        db,
        user_id=user.id,
        retention_days=req.retention_days,
        action=req.action,
        target_id=req.target_id,
    )
    return operation_result(result, corr)


@router.post("/lifecycle-confirmation-check")
async def lifecycle_confirmation_check(
    req: LifecycleConfirmationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_runtime_admin),
):
    """Validate future lifecycle confirmation semantics while blocking execution."""
    corr = req.request_id or correlation_id()
    result = check_lifecycle_confirmation(
        token=req.preview_token,
        user_id=user.id,
        action=req.action,
        confirm=req.confirm,
    )
    return operation_result(result, corr)


@router.post("/execution-intent-preview")
async def get_execution_intent_preview(
    req: ExecutionIntentPreviewRequest,
    user: User = Depends(get_current_user),
):
    """Return a signed, non-persistent summary for a future high-risk user action."""
    corr = req.request_id or correlation_id()
    try:
        result = create_execution_intent_preview(
            user_id=user.id,
            action=req.action,
            target_ids=req.target_ids,
            expected_versions=req.expected_versions,
            expected_versions_by_target=req.expected_versions_by_target,
        )
    except ValueError as exc:
        raise problem(400, "EXECUTION_INTENT_PREVIEW_ACTION_INVALID", "This action cannot be previewed.", correlation=corr) from exc
    return operation_result(result, corr)


@router.post("/execution-intent-confirmation-check")
async def execution_intent_confirmation_check(
    req: ExecutionIntentConfirmationRequest,
    user: User = Depends(get_current_user),
):
    """Validate only the future confirmation contract; execution remains disabled."""
    corr = req.request_id or correlation_id()
    result = check_execution_intent_preview(
        token=req.preview_token,
        user_id=user.id,
        action=req.action,
        confirm=req.confirm,
    )
    return operation_result(result, corr)


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=32)
    request_id: str | None = Field(default=None, max_length=64)


class PluginProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    plugins: list[str] = Field(default_factory=list, max_length=128)
    mcp_servers: list[Any] = Field(default_factory=list, max_length=128)
    tool_allowlist: list[str] = Field(default_factory=list, max_length=256)
    request_id: str | None = Field(default=None, max_length=64)


class ModelInsightPreferenceRequest(BaseModel):
    prices: dict[str, dict[str, float]] = Field(default_factory=dict)
    daily_budget: float | None = Field(default=None, ge=0.0)
    weekly_budget: float | None = Field(default=None, ge=0.0)
    request_id: str | None = Field(default=None, max_length=64)


class LifecyclePreviewRequest(BaseModel):
    retention_days: int = Field(default=30, ge=1, le=3650)
    action: Literal["retention.cleanup", "schedule.recovery", "plugin.compensation", "runtime.shutdown_recovery"] = "retention.cleanup"
    target_id: str | None = Field(default=None, min_length=1, max_length=160)
    request_id: str | None = Field(default=None, max_length=64)


class LifecycleConfirmationRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    preview_token: str = Field(min_length=1, max_length=4096)
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


class ExecutionIntentPreviewRequest(BaseModel):
    action: str = Field(min_length=3, max_length=100)
    target_ids: list[str] = Field(min_length=1, max_length=50)
    expected_versions_by_target: dict[str, int] = Field(default_factory=dict, max_length=50)
    expected_versions: list[int] = Field(default_factory=list, max_length=50)
    request_id: str | None = Field(default=None, max_length=64)


class ExecutionIntentConfirmationRequest(BaseModel):
    action: str = Field(min_length=3, max_length=100)
    preview_token: str = Field(min_length=1, max_length=4096)
    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


class WorkspaceActionRequest(BaseModel):
    """Explicit confirmation for destructive or association-changing user actions."""

    confirm: bool = False
    request_id: str | None = Field(default=None, max_length=64)


def _workspace_unavailable(correlation: str):
    raise problem(404, "WORKSPACE_RESOURCE_UNAVAILABLE", "Workspace resource is unavailable.", correlation=correlation)


def _workspace_audit_or_problem(
    db: Session,
    *,
    user_id: int,
    action: str,
    object_type: str,
    object_id: str,
    correlation: str,
    metadata: dict[str, Any],
) -> None:
    """Stage and commit fixed-summary Workspace audit data without raw DB details."""
    try:
        validate_control_plane_audit_metadata(action, metadata)
        record_control_plane_operation(db, user_id=user_id, action=action, object_type=object_type, object_id=object_id, correlation_id=correlation, metadata=metadata)
        commit_control_plane_audit(db)
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    except AuditPersistenceError as exc:
        raise problem(503, "WORKSPACE_AUDIT_DURABILITY_UNKNOWN", "Workspace action was accepted, but audit durability is unknown.", correlation=correlation) from exc


@router.get("/artifacts")
async def list_artifacts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(RunArtifact).filter(RunArtifact.user_id == user.id).order_by(RunArtifact.created_at.desc()).all()
    return {"artifacts": [{"id": row.id, "source_kind": row.source_kind, "source_id": row.source_id, "artifact_type": row.artifact_type, "title": row.title, "redacted": bool(row.redacted), "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]}


@router.post("/artifacts/from-run/{run_id}")
async def capture_run_artifact(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id, AgentRun.user_id == user.id).first()
    if run is None:
        raise problem(404, "RUN_NOT_FOUND", "Run not found")
    try:
        raw_metadata = json.loads(run.meta or "{}")
    except (TypeError, ValueError):
        raw_metadata = {}
    payload = redact_data({"run_id": run.run_id, "agent_id": run.agent_id, "status": run.status, "output": run.output or "", "error": run.error or "", "metadata": raw_metadata})
    item = RunArtifact(id=uuid.uuid4().hex, user_id=user.id, source_kind="agent_run", source_id=run.run_id, artifact_type="run_summary", title=f"Run {run.run_id}", content_json=json.dumps(payload, ensure_ascii=False), content_text=redact_text(run.output or ""), redacted=True)
    correlation = correlation_id()
    db.add(item)
    record_operation(db, user_id=user.id, action="artifact.capture", object_type="run_artifact", object_id=item.id, correlation_id=correlation, metadata={"source_kind": item.source_kind, "source_id": item.source_id, "redacted": True})
    db.commit()
    return operation_result({"id": item.id, "title": item.title, "redacted": True}, correlation)


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str, req: WorkspaceActionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    correlation = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "ARTIFACT_DELETE_CONFIRMATION_REQUIRED", "Confirm before deleting an artifact.", correlation=correlation)
    try:
        validate_control_plane_audit_metadata("artifact.delete", {"confirmed": True})
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    item = db.query(RunArtifact).filter(RunArtifact.id == artifact_id, RunArtifact.user_id == user.id).first()
    if item is None:
        _workspace_unavailable(correlation)
    db.delete(item)
    _workspace_audit_or_problem(db, user_id=user.id, action="artifact.delete", object_type="run_artifact", object_id=item.id, correlation=correlation, metadata={"confirmed": True})
    return operation_result({"ok": True}, correlation)


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(RunArtifact).filter(RunArtifact.id == artifact_id, RunArtifact.user_id == user.id).first()
    if item is None:
        raise problem(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
    try:
        content = json.loads(item.content_json or "{}")
    except (TypeError, ValueError):
        content = {"text": item.content_text or ""}
    return {
        "id": item.id,
        "title": item.title,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "artifact_type": item.artifact_type,
        "redacted": bool(item.redacted),
        "content": redact_data(content),
        "text": redact_text(item.content_text or ""),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/collections")
async def list_collections(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(KnowledgeCollection).filter(KnowledgeCollection.user_id == user.id).order_by(KnowledgeCollection.created_at.desc()).all()
    result = []
    for row in rows:
        count = db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == row.id).count()
        result.append({"id": row.id, "name": row.name, "description": row.description, "tags": json.loads(row.tags_json or "[]"), "document_count": count})
    return {"collections": result}


@router.post("/collections")
async def create_collection(req: CollectionCreateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = req.name.strip()
    if not name:
        raise problem(422, "COLLECTION_NAME_REQUIRED", "Collection name required")
    correlation = req.request_id or correlation_id()
    item = KnowledgeCollection(id=uuid.uuid4().hex, user_id=user.id, name=name, description=req.description, tags_json=json.dumps(req.tags, ensure_ascii=False))
    db.add(item)
    record_operation(db, user_id=user.id, action="collection.create", object_type="knowledge_collection", object_id=item.id, correlation_id=correlation, metadata={"name": name, "tag_count": len(req.tags)})
    db.commit()
    return operation_result({"id": item.id, "name": item.name}, correlation)


@router.post("/collections/{collection_id}/documents/{document_id}")
async def add_collection_document(collection_id: str, document_id: int, req: WorkspaceActionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    correlation = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "COLLECTION_ASSOCIATION_CONFIRMATION_REQUIRED", "Confirm before changing a collection association.", correlation=correlation)
    try:
        validate_control_plane_audit_metadata("collection.document.add", {"confirmed": True, "document_bound": True})
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == user.id).first()
    if collection is None or document is None:
        _workspace_unavailable(correlation)
    exists = db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection_id, KnowledgeCollectionDocument.document_id == document_id).first()
    if exists is None:
        db.add(KnowledgeCollectionDocument(id=uuid.uuid4().hex, collection_id=collection_id, document_id=document_id))
        _workspace_audit_or_problem(db, user_id=user.id, action="collection.document.add", object_type="knowledge_collection", object_id=collection_id, correlation=correlation, metadata={"confirmed": True, "document_bound": True})
        return operation_result({"ok": True}, correlation)
    return operation_result({"ok": True, "already_member": True}, correlation)


@router.get("/collections/{collection_id}")
async def get_collection(collection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    if collection is None:
        raise problem(404, "COLLECTION_NOT_FOUND", "Collection not found")
    rows = (
        db.query(KnowledgeDocument)
        .join(KnowledgeCollectionDocument, KnowledgeCollectionDocument.document_id == KnowledgeDocument.id)
        .filter(KnowledgeCollectionDocument.collection_id == collection.id, KnowledgeDocument.user_id == user.id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )
    return {"id": collection.id, "name": collection.name, "description": collection.description, "tags": json.loads(collection.tags_json or "[]"), "documents": [row.to_dict() for row in rows]}


@router.delete("/collections/{collection_id}/documents/{document_id}")
async def remove_collection_document(collection_id: str, document_id: int, req: WorkspaceActionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    correlation = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "COLLECTION_ASSOCIATION_CONFIRMATION_REQUIRED", "Confirm before changing a collection association.", correlation=correlation)
    try:
        validate_control_plane_audit_metadata("collection.document.remove", {"confirmed": True, "document_bound": True})
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    if collection is None:
        _workspace_unavailable(correlation)
    membership = db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection.id, KnowledgeCollectionDocument.document_id == document_id).first()
    if membership is None:
        _workspace_unavailable(correlation)
    db.delete(membership)
    _workspace_audit_or_problem(db, user_id=user.id, action="collection.document.remove", object_type="knowledge_collection", object_id=collection.id, correlation=correlation, metadata={"confirmed": True, "document_bound": True})
    return operation_result({"ok": True}, correlation)


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, req: WorkspaceActionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    correlation = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "COLLECTION_DELETE_CONFIRMATION_REQUIRED", "Confirm before deleting a collection.", correlation=correlation)
    try:
        validate_control_plane_audit_metadata("collection.delete", {"confirmed": True})
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    if collection is None:
        _workspace_unavailable(correlation)
    db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection.id).delete(synchronize_session=False)
    db.delete(collection)
    _workspace_audit_or_problem(db, user_id=user.id, action="collection.delete", object_type="knowledge_collection", object_id=collection.id, correlation=correlation, metadata={"confirmed": True})
    return operation_result({"ok": True}, correlation)


@router.get("/plugin-profiles")
async def list_plugin_profiles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(PluginProfile).filter(PluginProfile.user_id == user.id).all()
    return {"profiles": [{"id": row.id, "name": row.name, "profile": json.loads(row.profile_json or "{}"), "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in rows]}


@router.post("/plugin-profiles")
async def create_plugin_profile(req: PluginProfileCreateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = req.name.strip()
    if not name:
        raise problem(422, "PLUGIN_PROFILE_NAME_REQUIRED", "Profile name required")
    profile = {"plugins": req.plugins, "mcp_servers": req.mcp_servers, "tool_allowlist": req.tool_allowlist}
    correlation = req.request_id or correlation_id()
    item = PluginProfile(id=uuid.uuid4().hex, user_id=user.id, name=name, profile_json=json.dumps(profile, ensure_ascii=False))
    db.add(item)
    record_operation(db, user_id=user.id, action="plugin_profile.create", object_type="plugin_profile", object_id=item.id, correlation_id=correlation, metadata={"name": name, "plugin_count": len(req.plugins), "mcp_server_count": len(req.mcp_servers)})
    db.commit()
    return operation_result({"id": item.id, "name": item.name}, correlation)


@router.get("/plugin-profiles/{profile_id}/preview")
async def preview_plugin_profile(profile_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(PluginProfile).filter(PluginProfile.id == profile_id, PluginProfile.user_id == user.id).first()
    if item is None:
        raise problem(404, "PLUGIN_PROFILE_NOT_FOUND", "Plugin profile not found")
    try:
        profile = json.loads(item.profile_json or "{}")
    except (TypeError, ValueError):
        profile = {}
    safe = redact_data(profile if isinstance(profile, dict) else {})
    return {
        "id": item.id,
        "name": item.name,
        "profile": safe,
        "declared_plugin_count": len(safe.get("plugins") or []),
        "declared_mcp_server_count": len(safe.get("mcp_servers") or []),
        "declared_tool_count": len(safe.get("tool_allowlist") or []),
        "notice": "Preview only. This profile is not applied, no plugin is loaded, and no MCP server is started.",
    }


@router.delete("/plugin-profiles/{profile_id}")
async def delete_plugin_profile(profile_id: str, req: WorkspaceActionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    correlation = req.request_id or correlation_id()
    if not req.confirm:
        raise problem(409, "PLUGIN_PROFILE_DELETE_CONFIRMATION_REQUIRED", "Confirm before deleting a plugin profile.", correlation=correlation)
    try:
        validate_control_plane_audit_metadata("plugin_profile.delete", {"confirmed": True})
    except AuditMetadataRejected as exc:
        raise problem(500, "CONTROL_AUDIT_METADATA_REJECTED", "Control-plane audit policy rejected this action.", correlation=correlation) from exc
    item = db.query(PluginProfile).filter(PluginProfile.id == profile_id, PluginProfile.user_id == user.id).first()
    if item is None:
        _workspace_unavailable(correlation)
    db.delete(item)
    _workspace_audit_or_problem(db, user_id=user.id, action="plugin_profile.delete", object_type="plugin_profile", object_id=item.id, correlation=correlation, metadata={"confirmed": True})
    return operation_result({"ok": True}, correlation)


@router.get("/insights")
async def model_insights(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    after = datetime.datetime.utcnow() - datetime.timedelta(days=max(1, min(days, 365)))
    rows = db.query(ModelMetricBucket).filter(ModelMetricBucket.user_id == user.id, ModelMetricBucket.bucket_start >= after).all()
    aggregate: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = aggregate.setdefault(row.model_ref, {"model_ref": row.model_ref, "request_count": 0, "success_count": 0, "error_count": 0, "error_4xx_count": 0, "error_429_count": 0, "error_5xx_count": 0, "timeout_count": 0, "latency_sum_ms": 0.0, "cost_estimate": 0.0})
        item["request_count"] += row.request_count
        item["success_count"] += row.success_count
        item["error_count"] += row.error_4xx_count + row.error_429_count + row.error_5xx_count + row.timeout_count
        item["error_4xx_count"] += row.error_4xx_count
        item["error_429_count"] += row.error_429_count
        item["error_5xx_count"] += row.error_5xx_count
        item["timeout_count"] += row.timeout_count
        item["latency_sum_ms"] += row.latency_sum_ms
        item["cost_estimate"] += row.cost_estimate
    for item in aggregate.values():
        item["average_latency_ms"] = round(item.pop("latency_sum_ms") / item["request_count"], 1) if item["request_count"] else None
    preference = db.query(ModelInsightPreference).filter(ModelInsightPreference.user_id == user.id).one_or_none()
    preferences = preference.to_dict() if preference else {"prices": {}, "daily_budget": None, "weekly_budget": None}
    now = datetime.datetime.utcnow()
    daily_cost = sum(row.cost_estimate for row in rows if row.bucket_start >= now - datetime.timedelta(days=1))
    weekly_cost = sum(row.cost_estimate for row in rows if row.bucket_start >= now - datetime.timedelta(days=7))
    budget_status = {
        "daily_cost_estimate": round(daily_cost, 8),
        "weekly_cost_estimate": round(weekly_cost, 8),
        "daily_budget": preferences["daily_budget"],
        "weekly_budget": preferences["weekly_budget"],
        "daily_exceeded": bool(preferences["daily_budget"] is not None and daily_cost >= preferences["daily_budget"]),
        "weekly_exceeded": bool(preferences["weekly_budget"] is not None and weekly_cost >= preferences["weekly_budget"]),
        "notice": "Informational only. Budget preferences never stop, route, or alter model calls.",
    }
    return {"days": days, "insights": list(aggregate.values()), "preferences": preferences, "budget_status": budget_status, "notice": "Only aggregated, redacted metrics are retained."}


@router.get("/control-plane-budget")
async def get_control_plane_budget(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return a content-free, informational summary of user-scoped control limits."""
    now = datetime.datetime.utcnow()
    rows = db.query(ModelMetricBucket).filter(
        ModelMetricBucket.user_id == user.id,
        ModelMetricBucket.bucket_start >= now - datetime.timedelta(days=7),
    ).all()
    preference = db.query(ModelInsightPreference).filter(ModelInsightPreference.user_id == user.id).one_or_none()
    active_task_count = db.query(TaskRecord).filter(
        TaskRecord.user_id == user.id,
        TaskRecord.status.in_(["QUEUED", "SCHEDULED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED", "RETRYING"]),
    ).count()
    daily_used = sum(row.cost_estimate for row in rows if row.bucket_start >= now - datetime.timedelta(days=1))
    weekly_used = sum(row.cost_estimate for row in rows)
    result = control_plane_budget_summary(
        daily_budget=preference.daily_budget if preference else None,
        weekly_budget=preference.weekly_budget if preference else None,
        daily_used=daily_used,
        weekly_used=weekly_used,
        active_task_count=active_task_count,
    )
    return operation_result(result, correlation_id())


@router.put("/insights/preferences")
async def update_model_insight_preferences(req: ModelInsightPreferenceRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prices = req.prices or {}
    if not isinstance(prices, dict):
        raise problem(422, "INSIGHT_PRICES_INVALID", "Prices must be keyed by non-secret model references")
    safe_prices: dict[str, dict[str, float]] = {}
    for ref, item in prices.items():
        if not isinstance(item, dict) or not str(ref).startswith(("local:", "remote:")):
            raise problem(422, "INSIGHT_MODEL_REF_INVALID", "Price entries must use local:/remote: model references")
        try:
            safe_prices[str(ref)[:255]] = {"input_per_million": max(0.0, float(item.get("input_per_million", 0))), "output_per_million": max(0.0, float(item.get("output_per_million", 0)))}
        except (TypeError, ValueError):
            raise problem(422, "INSIGHT_PRICE_INVALID", "Price values must be non-negative numbers")
    preference = db.query(ModelInsightPreference).filter(ModelInsightPreference.user_id == user.id).one_or_none()
    if preference is None:
        preference = ModelInsightPreference(user_id=user.id)
        db.add(preference)
    preference.prices_json = json.dumps(safe_prices, ensure_ascii=False)
    supplied = getattr(req, "model_fields_set", getattr(req, "__fields_set__", set()))
    for key in ("daily_budget", "weekly_budget"):
        if key in supplied:
            setattr(preference, key, getattr(req, key))
    correlation = req.request_id or correlation_id()
    record_operation(db, user_id=user.id, action="model_insight_preferences.update", object_type="model_insight_preference", object_id=str(user.id), correlation_id=correlation, metadata={"price_count": len(safe_prices), "daily_budget_set": "daily_budget" in supplied, "weekly_budget_set": "weekly_budget" in supplied})
    db.commit()
    return operation_result(preference.to_dict(), correlation)
