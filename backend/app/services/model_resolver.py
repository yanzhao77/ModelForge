"""Resolve a user-supplied model reference to a ``ModelRecord``.

The chat UI, the OpenAI-compatible API and the runtime page all receive a
*reference* (a numeric ``model_id``, a name, or an alias). This module is the
only place that turns such a reference back into a registry record, so every
entry point agrees on what a model is called.
"""

from __future__ import annotations

from models.records import ModelRecord
from services.model_registry import ModelRegistry
from sqlalchemy.orm import Session as DBSession


class ModelResolver:
    """Name / id / alias resolution on top of :class:`ModelRegistry`."""

    def __init__(self, db: DBSession):
        self.db = db
        self.registry = ModelRegistry(db)

    def resolve(self, reference: object, user_id: int | None = None) -> ModelRecord | None:
        """Return the matching record, or ``None`` when nothing matches."""
        if reference is None:
            return None
        if isinstance(reference, ModelRecord):
            return reference
        if isinstance(reference, int):
            return self.registry.get(reference, user_id)
        text = str(reference).strip()
        if not text:
            return None
        if text.isdigit():
            record = self.registry.get(int(text), user_id)
            if record is not None:
                return record
        return self._match(text, user_id)

    def resolve_or_raise(self, reference: object, user_id: int | None = None) -> ModelRecord:
        from services.model_registry import ModelRegistryError

        record = self.resolve(reference, user_id)
        if record is None:
            raise ModelRegistryError(
                "MODEL_NOT_FOUND",
                "指定的模型不存在或无权访问。",
                {"model": str(reference)},
                http_status=404,
            )
        return record

    def _match(self, text: str, user_id: int | None) -> ModelRecord | None:
        lowered = text.lower()
        candidates = self.registry.list_models(user_id)
        for record in candidates:
            if (record.name or "").lower() == lowered:
                return record
        for record in candidates:
            if (record.display_name or "").lower() == lowered:
                return record
        for record in candidates:
            aliases = record.metadata_dict().get("aliases")
            if isinstance(aliases, list) and any(str(alias).lower() == lowered for alias in aliases):
                return record
        return None
