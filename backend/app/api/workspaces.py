"""User-controlled APIs for artifacts, knowledge collections, extensions and model insights."""
from __future__ import annotations

import datetime
import json
import re
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
    ModelMetricBucket,
    PluginProfile,
    RunArtifact,
    User,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_SENSITIVE = re.compile(r"(?i)(authorization|api[_-]?key|token|password)\s*[:=]\s*[^\s,]+")


def _redact(value: str) -> str:
    return _SENSITIVE.sub(lambda match: match.group(1) + "=[REDACTED]", value or "")


@router.get("/artifacts")
async def list_artifacts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(RunArtifact).filter(RunArtifact.user_id == user.id).order_by(RunArtifact.created_at.desc()).all()
    return {"artifacts": [{"id": row.id, "source_kind": row.source_kind, "source_id": row.source_id, "artifact_type": row.artifact_type, "title": row.title, "redacted": bool(row.redacted), "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]}


@router.post("/artifacts/from-run/{run_id}")
async def capture_run_artifact(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id, AgentRun.user_id == user.id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    payload = {"run_id": run.run_id, "agent_id": run.agent_id, "status": run.status, "output": _redact(run.output or ""), "error": _redact(run.error or ""), "metadata": json.loads(run.meta or "{}")}
    item = RunArtifact(id=uuid.uuid4().hex, user_id=user.id, source_kind="agent_run", source_id=run.run_id, artifact_type="run_summary", title=f"Run {run.run_id}", content_json=json.dumps(payload, ensure_ascii=False), content_text=payload["output"], redacted=True)
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


@router.get("/insights")
async def model_insights(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    after = datetime.datetime.utcnow() - datetime.timedelta(days=max(1, min(days, 365)))
    rows = db.query(ModelMetricBucket).filter(ModelMetricBucket.user_id == user.id, ModelMetricBucket.bucket_start >= after).all()
    aggregate: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = aggregate.setdefault(row.model_ref, {"model_ref": row.model_ref, "request_count": 0, "success_count": 0, "error_count": 0, "latency_sum_ms": 0.0, "cost_estimate": 0.0})
        item["request_count"] += row.request_count
        item["success_count"] += row.success_count
        item["error_count"] += row.error_4xx_count + row.error_429_count + row.error_5xx_count + row.timeout_count
        item["latency_sum_ms"] += row.latency_sum_ms
        item["cost_estimate"] += row.cost_estimate
    for item in aggregate.values():
        item["average_latency_ms"] = round(item.pop("latency_sum_ms") / item["request_count"], 1) if item["request_count"] else None
    return {"days": days, "insights": list(aggregate.values()), "notice": "Only aggregated, redacted metrics are retained."}
