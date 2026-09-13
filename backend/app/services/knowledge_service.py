"""Knowledge Base, document and collection management (V1.4).

The retrieval engine lives in :mod:`services.knowledge_base`; this service owns
the *library* around it — named knowledge bases, their documents, ingestion
progress through the unified task center, and the embedding provider choice.
"""

from __future__ import annotations

import json
import uuid

from models.records import (
    KnowledgeCollection,
    KnowledgeCollectionDocument,
    KnowledgeDocument,
)


class KnowledgeServiceError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status


class KnowledgeService:
    """User-scoped CRUD for knowledge bases and their document bindings."""

    def __init__(self, db, kb=None):
        self.db = db
        self.kb = kb

    # -- bases --------------------------------------------------------------

    def list_bases(self, user_id: int) -> list[dict]:
        rows = (
            self.db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.user_id == user_id)
            .order_by(KnowledgeCollection.created_at.desc())
            .all()
        )
        return [self._base_payload(row) for row in rows]

    def create_base(self, user_id: int, name: str, description: str | None = None, tags: list[str] | None = None) -> dict:
        cleaned = str(name or "").strip()
        if not cleaned:
            raise KnowledgeServiceError("KNOWLEDGE_BASE_NAME_REQUIRED", "Knowledge base name is required.")
        row = KnowledgeCollection(
            id=uuid.uuid4().hex,
            user_id=user_id,
            name=cleaned[:160],
            description=description,
            tags_json=json.dumps([str(tag) for tag in (tags or [])][:20], ensure_ascii=False),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._base_payload(row)

    def require_base(self, user_id: int, base_id: str) -> KnowledgeCollection:
        row = (
            self.db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.id == base_id, KnowledgeCollection.user_id == user_id)
            .first()
        )
        if row is None:
            raise KnowledgeServiceError(
                "KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found.", {"knowledge_id": base_id}, http_status=404
            )
        return row

    def get_base(self, user_id: int, base_id: str) -> dict:
        return self._base_payload(self.require_base(user_id, base_id))

    def update_base(self, user_id: int, base_id: str, *, name: str | None = None, description: str | None = None, tags: list[str] | None = None) -> dict:
        row = self.require_base(user_id, base_id)
        if name is not None:
            cleaned = str(name).strip()
            if not cleaned:
                raise KnowledgeServiceError("KNOWLEDGE_BASE_NAME_REQUIRED", "Knowledge base name is required.")
            row.name = cleaned[:160]
        if description is not None:
            row.description = description
        if tags is not None:
            row.tags_json = json.dumps([str(tag) for tag in tags][:20], ensure_ascii=False)
        self.db.commit()
        self.db.refresh(row)
        return self._base_payload(row)

    def delete_base(self, user_id: int, base_id: str) -> bool:
        row = self.require_base(user_id, base_id)
        self.db.query(KnowledgeCollectionDocument).filter(
            KnowledgeCollectionDocument.collection_id == base_id
        ).delete()
        self.db.delete(row)
        self.db.commit()
        return True

    def _base_payload(self, row: KnowledgeCollection) -> dict:
        document_count = (
            self.db.query(KnowledgeCollectionDocument)
            .filter(KnowledgeCollectionDocument.collection_id == row.id)
            .count()
        )
        try:
            tags = json.loads(row.tags_json or "[]")
        except (TypeError, ValueError):
            tags = []
        return {
            "id": row.id,
            "knowledge_id": row.id,
            "name": row.name,
            "description": row.description,
            "tags": tags if isinstance(tags, list) else [],
            "document_count": document_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # -- documents ----------------------------------------------------------

    def attach_document(self, user_id: int, base_id: str, document_id: int) -> dict:
        self.require_base(user_id, base_id)
        document = (
            self.db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.id == int(document_id), KnowledgeDocument.user_id == user_id)
            .first()
        )
        if document is None:
            raise KnowledgeServiceError(
                "KNOWLEDGE_DOCUMENT_NOT_FOUND", "Document not found.", {"document_id": document_id}, http_status=404
            )
        existing = (
            self.db.query(KnowledgeCollectionDocument)
            .filter(
                KnowledgeCollectionDocument.collection_id == base_id,
                KnowledgeCollectionDocument.document_id == document.id,
            )
            .first()
        )
        if existing is None:
            self.db.add(
                KnowledgeCollectionDocument(
                    id=uuid.uuid4().hex, collection_id=base_id, document_id=document.id
                )
            )
            self.db.commit()
        return {"knowledge_id": base_id, "document_id": document.id, "attached": existing is None}

    def detach_document(self, user_id: int, base_id: str, document_id: int) -> bool:
        self.require_base(user_id, base_id)
        removed = (
            self.db.query(KnowledgeCollectionDocument)
            .filter(
                KnowledgeCollectionDocument.collection_id == base_id,
                KnowledgeCollectionDocument.document_id == int(document_id),
            )
            .delete()
        )
        self.db.commit()
        return bool(removed)

    def documents(self, user_id: int, base_id: str) -> list[dict]:
        self.require_base(user_id, base_id)
        rows = (
            self.db.query(KnowledgeDocument)
            .join(
                KnowledgeCollectionDocument,
                KnowledgeCollectionDocument.document_id == KnowledgeDocument.id,
            )
            .filter(
                KnowledgeCollectionDocument.collection_id == base_id,
                KnowledgeDocument.user_id == user_id,
            )
            .order_by(KnowledgeDocument.created_at.desc())
            .all()
        )
        return [row.to_dict() for row in rows]

    def attach_latest(self, user_id: int, base_id: str, filename: str) -> dict | None:
        """Attach the most recent stored copy of ``filename`` to a base."""
        document = (
            self.db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.user_id == user_id, KnowledgeDocument.filename == filename)
            .order_by(KnowledgeDocument.created_at.desc())
            .first()
        )
        if document is None:
            return None
        return self.attach_document(user_id, base_id, document.id)

    # -- ingestion ----------------------------------------------------------

    def index_file(
        self,
        user_id: int,
        *,
        filepath: str,
        filename: str,
        base_id: str | None = None,
    ) -> dict:
        """Ingest one file and (optionally) attach it to a knowledge base."""
        if self.kb is None:
            raise KnowledgeServiceError(
                "KNOWLEDGE_UNAVAILABLE", "Knowledge base is not initialized.", http_status=503
            )
        if base_id:
            self.require_base(user_id, base_id)
        result = self.kb.upload(filepath, db=self.db, user_id=user_id, filename=filename)
        document_id = None
        if result.get("status") == "ingested":
            document = (
                self.db.query(KnowledgeDocument)
                .filter(KnowledgeDocument.user_id == user_id, KnowledgeDocument.filename == filename)
                .order_by(KnowledgeDocument.created_at.desc())
                .first()
            )
            if document is not None:
                document_id = document.id
                if base_id:
                    self.attach_document(user_id, base_id, document.id)
        return {
            "knowledge_id": base_id,
            "filename": filename,
            "document_id": document_id,
            "status": result.get("status"),
            "chunks": result.get("chunks", 0),
            "type": result.get("type"),
        }

    def embedding_status(self, user_id: int, model_id: int | None = None) -> dict:
        """Report which embedding provider would be used (V1.4)."""
        from services.embedding_service import describe_embedding_provider

        return describe_embedding_provider(self.db, user_id, model_id=model_id)
