"""User-controlled APIs for artifacts, knowledge collections, extensions and model insights."""
from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from core.database import get_db
from core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from models.records import (
    AgentRun,
    KnowledgeCollection,
    KnowledgeCollectionDocument,
    KnowledgeDocument,
    ModelInsightPreference,
    ModelMetricBucket,
    PluginProfile,
    RunArtifact,
    User,
)
from services.redaction import redact_data, redact_text
from sqlalchemy.orm import Session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/artifacts")
async def list_artifacts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(RunArtifact).filter(RunArtifact.user_id == user.id).order_by(RunArtifact.created_at.desc()).all()
    return {"artifacts": [{"id": row.id, "source_kind": row.source_kind, "source_id": row.source_id, "artifact_type": row.artifact_type, "title": row.title, "redacted": bool(row.redacted), "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]}


@router.post("/artifacts/from-run/{run_id}")
async def capture_run_artifact(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id, AgentRun.user_id == user.id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        raw_metadata = json.loads(run.meta or "{}")
    except (TypeError, ValueError):
        raw_metadata = {}
    payload = redact_data({"run_id": run.run_id, "agent_id": run.agent_id, "status": run.status, "output": run.output or "", "error": run.error or "", "metadata": raw_metadata})
    item = RunArtifact(id=uuid.uuid4().hex, user_id=user.id, source_kind="agent_run", source_id=run.run_id, artifact_type="run_summary", title=f"Run {run.run_id}", content_json=json.dumps(payload, ensure_ascii=False), content_text=redact_text(run.output or ""), redacted=True)
    db.add(item)
    db.commit()
    return {"id": item.id, "title": item.title, "redacted": True}


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(RunArtifact).filter(RunArtifact.id == artifact_id, RunArtifact.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(RunArtifact).filter(RunArtifact.id == artifact_id, RunArtifact.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
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
async def create_collection(req: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = str(req.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Collection name required")
    item = KnowledgeCollection(id=uuid.uuid4().hex, user_id=user.id, name=name, description=req.get("description"), tags_json=json.dumps(req.get("tags") or [], ensure_ascii=False))
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name}


@router.post("/collections/{collection_id}/documents/{document_id}")
async def add_collection_document(collection_id: str, document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == user.id).first()
    if collection is None or document is None:
        raise HTTPException(status_code=404, detail="Collection or document not found")
    exists = db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection_id, KnowledgeCollectionDocument.document_id == document_id).first()
    if exists is None:
        db.add(KnowledgeCollectionDocument(id=uuid.uuid4().hex, collection_id=collection_id, document_id=document_id))
        db.commit()
    return {"ok": True}


@router.get("/collections/{collection_id}")
async def get_collection(collection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    rows = (
        db.query(KnowledgeDocument)
        .join(KnowledgeCollectionDocument, KnowledgeCollectionDocument.document_id == KnowledgeDocument.id)
        .filter(KnowledgeCollectionDocument.collection_id == collection.id, KnowledgeDocument.user_id == user.id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )
    return {"id": collection.id, "name": collection.name, "description": collection.description, "tags": json.loads(collection.tags_json or "[]"), "documents": [row.to_dict() for row in rows]}


@router.delete("/collections/{collection_id}/documents/{document_id}")
async def remove_collection_document(collection_id: str, document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    membership = db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection.id, KnowledgeCollectionDocument.document_id == document_id).first()
    if membership is None:
        raise HTTPException(status_code=404, detail="Collection document not found")
    db.delete(membership)
    db.commit()
    return {"ok": True}


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id, KnowledgeCollection.user_id == user.id).first()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    db.query(KnowledgeCollectionDocument).filter(KnowledgeCollectionDocument.collection_id == collection.id).delete(synchronize_session=False)
    db.delete(collection)
    db.commit()
    return {"ok": True}


@router.get("/plugin-profiles")
async def list_plugin_profiles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(PluginProfile).filter(PluginProfile.user_id == user.id).all()
    return {"profiles": [{"id": row.id, "name": row.name, "profile": json.loads(row.profile_json or "{}"), "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in rows]}


@router.post("/plugin-profiles")
async def create_plugin_profile(req: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = str(req.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Profile name required")
    profile = {"plugins": req.get("plugins") or [], "mcp_servers": req.get("mcp_servers") or [], "tool_allowlist": req.get("tool_allowlist") or []}
    item = PluginProfile(id=uuid.uuid4().hex, user_id=user.id, name=name, profile_json=json.dumps(profile, ensure_ascii=False))
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name}


@router.get("/plugin-profiles/{profile_id}/preview")
async def preview_plugin_profile(profile_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(PluginProfile).filter(PluginProfile.id == profile_id, PluginProfile.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Plugin profile not found")
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
async def delete_plugin_profile(profile_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(PluginProfile).filter(PluginProfile.id == profile_id, PluginProfile.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Plugin profile not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


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


@router.put("/insights/preferences")
async def update_model_insight_preferences(req: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prices = req.get("prices") or {}
    if not isinstance(prices, dict):
        raise HTTPException(status_code=422, detail="prices must be an object keyed by non-secret model references")
    safe_prices: dict[str, dict[str, float]] = {}
    for ref, item in prices.items():
        if not isinstance(item, dict) or not str(ref).startswith(("local:", "remote:")):
            raise HTTPException(status_code=422, detail="price entries must use local:/remote: model references")
        try:
            safe_prices[str(ref)[:255]] = {"input_per_million": max(0.0, float(item.get("input_per_million", 0))), "output_per_million": max(0.0, float(item.get("output_per_million", 0)))}
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="price values must be non-negative numbers")
    preference = db.query(ModelInsightPreference).filter(ModelInsightPreference.user_id == user.id).one_or_none()
    if preference is None:
        preference = ModelInsightPreference(user_id=user.id)
        db.add(preference)
    preference.prices_json = json.dumps(safe_prices, ensure_ascii=False)
    for key in ("daily_budget", "weekly_budget"):
        if key in req:
            value = req.get(key)
            try:
                value = None if value is None else max(0.0, float(value))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{key} must be a non-negative number or null")
            setattr(preference, key, value)
    db.commit()
    return preference.to_dict()
