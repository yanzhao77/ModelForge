"""Unified model registry: the single source of truth for model assets.

Every other module (model center, runtime manager, chat, training, the
OpenAI-compatible API) resolves a ``model_id`` through this service instead of
passing file paths or display names around. ``ModelManager`` still owns the
persistence primitives (scan / install / remove); the registry adds lifecycle
normalisation, capability detection and query filters on top of it so there is
only ever one model inventory.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from core.api_contracts import problem
from models.records import ModelRecord, UserModelPreference
from services.model_capabilities import (
    READY_STATUSES,
    TRANSIENT_STATUSES,
    ModelCapability,
    infer_capabilities,
    is_ready_status,
    normalize_format,
    normalize_status,
)
from services.model_manager import ModelManager
from services.model_metadata import detect_metadata, directory_size_bytes
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession


class ModelRegistryError(ValueError):
    """Stable, user-facing registry failure (maps 1:1 onto an API problem)."""

    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status

    def to_problem(self, correlation: str | None = None):
        return problem(self.http_status, self.code, self.message, details=self.details or None, correlation=correlation)


def asset_path_available(path: str | None) -> bool:
    """Whether a record's asset still exists on disk.

    Legacy rows may legitimately have no path (a record created before the
    download/scan pipeline stored one). Only a *declared* path that has
    disappeared makes a model invalid, so an unknown path is treated as
    available rather than silently breaking old data.
    """
    if not path:
        return True
    return Path(str(path)).exists()


class ModelRegistry:
    """Query, normalise and register model assets for one database session."""

    def __init__(self, db: DBSession):
        self.db = db
        self.manager = ModelManager(db)

    # -- lookups ------------------------------------------------------------

    def get(self, model_id: int | None, user_id: int | None = None) -> ModelRecord | None:
        if model_id is None:
            return None
        query = self.db.query(ModelRecord).filter_by(id=model_id)
        if user_id is not None:
            query = query.filter(
                or_(ModelRecord.user_id == user_id, ModelRecord.user_id.is_(None))
            )
        return query.first()

    def require(self, model_id: int | None, user_id: int | None = None) -> ModelRecord:
        record = self.get(model_id, user_id)
        if record is None:
            raise ModelRegistryError(
                "MODEL_NOT_FOUND",
                "指定的模型不存在或无权访问。",
                {"model_id": model_id},
                http_status=404,
            )
        return record

    def list_models(
        self,
        user_id: int | None = None,
        *,
        capability: str | None = None,
        status: str | None = None,
        model_format: str | None = None,
        source: str | None = None,
    ) -> list[ModelRecord]:
        """List models, optionally filtered by capability/status/format/source."""
        query = self.db.query(ModelRecord)
        if user_id is not None:
            query = query.filter(
                or_(ModelRecord.user_id == user_id, ModelRecord.user_id.is_(None))
            )
        if status:
            query = query.filter(ModelRecord.status == status.strip().lower())
        if model_format:
            query = query.filter(ModelRecord.format == model_format.strip().lower())
        if source:
            query = query.filter(ModelRecord.provider == source)
        records = query.order_by(ModelRecord.name).all()
        if not capability:
            return records
        wanted = str(capability).strip().upper()
        return [record for record in records if wanted in self.capabilities(record)]

    def default_model(self, user_id: int) -> ModelRecord | None:
        """Return the user's preferred default local model, if it is still usable."""
        preference = self.db.get(UserModelPreference, user_id)
        if preference is None or preference.default_kind != "local":
            return None
        try:
            model_id = int(preference.default_model_ref)
        except (TypeError, ValueError):
            return None
        record = self.get(model_id, user_id)
        return record if record is not None and self.is_ready(record) else None

    # -- capability / lifecycle --------------------------------------------

    def capabilities(self, record: ModelRecord) -> list[str]:
        stored = record.capability_list()
        if stored:
            return stored
        return infer_capabilities(
            model_format=record.format,
            path=record.path,
            provider=record.provider,
            quant=record.quant,
        )

    def supports(self, record: ModelRecord, capability: str) -> bool:
        return str(capability).strip().upper() in self.capabilities(record)

    def require_capability(self, record: ModelRecord, capability: str) -> None:
        if not self.supports(record, capability):
            raise ModelRegistryError(
                "MODEL_CAPABILITY_UNSUPPORTED",
                "该模型不支持所需能力。",
                {
                    "model_id": record.id,
                    "required": str(capability).strip().upper(),
                    "capabilities": self.capabilities(record),
                    "format": record.format,
                },
            )

    def is_ready(self, record: ModelRecord) -> bool:
        if normalize_status(record.status) in TRANSIENT_STATUSES:
            return True
        if not is_ready_status(record.status):
            return False
        return asset_path_available(record.path)

    def require_ready(self, record: ModelRecord) -> None:
        if not asset_path_available(record.path):
            raise ModelRegistryError(
                "MODEL_NOT_READY",
                "模型文件不存在，请重新扫描或下载。",
                {"model_id": record.id, "path_available": False},
            )
        if not is_ready_status(record.status):
            raise ModelRegistryError(
                "MODEL_NOT_READY",
                "模型尚未就绪，无法加载。",
                {"model_id": record.id, "status": record.status},
            )

    def resolve_path(self, record: ModelRecord) -> str:
        """Resolve a model asset to a path contained by the model root."""
        if not record.path:
            raise ModelRegistryError(
                "MODEL_PATH_INVALID",
                "模型记录缺少可用文件路径。",
                {"model_id": record.id},
            )
        try:
            resolved = self.manager._contained_model_path(record.path)
        except ValueError as exc:
            raise ModelRegistryError(
                "MODEL_PATH_INVALID",
                "模型路径不在允许的模型目录内。",
                {"model_id": record.id},
            ) from exc
        if not resolved.exists():
            raise ModelRegistryError(
                "MODEL_NOT_READY",
                "模型文件不存在，请重新扫描或下载。",
                {"model_id": record.id},
            )
        return str(resolved)

    def refresh(self, record: ModelRecord, *, commit: bool = False, detect: bool = True) -> ModelRecord:
        """Normalise format/capabilities/size and settle the lifecycle status."""
        record.format = normalize_format(record.format, record.path)
        if not record.capability_list():
            record.set_capabilities(
                infer_capabilities(
                    model_format=record.format,
                    path=record.path,
                    provider=record.provider,
                    quant=record.quant,
                )
            )
        if record.size_bytes in (None, 0) and record.path:
            size = directory_size_bytes(record.path)
            if size:
                record.size_bytes = size
        if detect and record.path and not record.metadata_dict():
            metadata = detect_metadata(record.path, model_format=record.format)
            if metadata:
                record.set_metadata(metadata)
        current = normalize_status(record.status)
        if record.path and not asset_path_available(record.path):
            record.status = "invalid"
        elif current in {"invalid", "available"} and asset_path_available(record.path):
            # ``available`` is the pre-lifecycle spelling of ``ready``; once a
            # record passes through the registry it is normalised so every page
            # sees the same vocabulary.
            record.status = "ready"
        record.updated_time = datetime.datetime.utcnow()
        if commit:
            self.db.commit()
        return record

    def refresh_capabilities(self, record: ModelRecord, *, commit: bool = False) -> list[str]:
        record.set_capabilities(
            infer_capabilities(
                model_format=record.format,
                path=record.path,
                provider=record.provider,
                quant=record.quant,
            )
        )
        if commit:
            self.db.commit()
        return record.capability_list()

    # -- registration -------------------------------------------------------

    def register(
        self,
        *,
        name: str,
        provider: str,
        path: str,
        size: str = "",
        user_id: int | None = None,
        model_format: str | None = None,
        quant: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict | None = None,
        base_model_id: int | None = None,
        parent_model_id: int | None = None,
        display_name: str | None = None,
        commit: bool = True,
    ) -> ModelRecord:
        """Install-or-update one model record and normalise its metadata."""
        try:
            record = self.manager.install(
                name=name,
                provider=provider,
                path=path,
                size=size,
                user_id=user_id,
                model_format=model_format,
                quant=quant,
            )
        except ValueError as exc:
            raise ModelRegistryError(
                "MODEL_PATH_OUTSIDE_ALLOWED_ROOT",
                "模型路径不在允许的模型目录内。",
                {"path_available": False},
                http_status=403,
            ) from exc
        if display_name:
            record.display_name = display_name
        if base_model_id is not None:
            record.base_model_id = base_model_id
        if parent_model_id is not None:
            record.parent_model_id = parent_model_id
        self.refresh(record, commit=False)
        if capabilities:
            record.set_capabilities(capabilities)
        if metadata:
            merged = record.metadata_dict()
            merged.update(metadata)
            record.set_metadata(merged)
        if normalize_status(record.status) == "invalid" and asset_path_available(record.path):
            record.status = "ready"
        elif not asset_path_available(record.path):
            # Explicitly registered but not yet on disk: record it as
            # "installed" so the model center can explain the state, while
            # ``is_ready`` keeps it out of the usable set until the file lands.
            record.status = "installed"
        if commit:
            self.db.commit()
        return record

    def register_download(
        self,
        *,
        user_id: int,
        repo_id: str,
        target: str | Path,
        filename: str | None = None,
    ) -> list[ModelRecord]:
        """Register the model artefacts a completed download left on disk.

        A repository may contain several quantisations; each recognised artefact
        becomes its own record, and re-running the same download updates the
        existing rows instead of creating duplicates.
        """
        directory = Path(str(target))
        if not directory.exists():
            return []
        candidates = self._artifacts(directory, filename)
        registered: list[ModelRecord] = []
        for artifact in candidates:
            if artifact.is_dir():
                model_format = "safetensors"
                name = artifact.name
                size = _format_size(directory_size_bytes(artifact))
            else:
                model_format = normalize_format(None, str(artifact))
                name = artifact.stem
                size = _format_size(directory_size_bytes(artifact))
            capabilities = infer_capabilities(
                model_format=model_format, path=str(artifact), provider="download"
            )
            record = self.register(
                name=name,
                provider="download",
                path=str(artifact),
                size=size,
                user_id=user_id,
                model_format=model_format,
                capabilities=capabilities,
                metadata={"repo_id": repo_id, "source": "download"},
                commit=False,
            )
            registered.append(record)
        if registered:
            self.db.commit()
        return registered

    @staticmethod
    def _artifacts(directory: Path, filename: str | None) -> list[Path]:
        """Pick the primary model artefacts inside a downloaded repository."""
        if filename:
            explicit = (directory / filename).resolve()
            if explicit.exists() and explicit.is_relative_to(directory.resolve()):
                if explicit.is_dir():
                    return [explicit] if (explicit / "config.json").exists() else []
                if explicit.suffix.lower() in {".gguf", ".ggml", ".safetensors", ".bin"}:
                    return [explicit]
        gguf_files = sorted(item for item in directory.glob("*.gguf") if item.is_file())
        if gguf_files:
            return gguf_files
        for child in sorted(directory.iterdir()):
            if child.is_dir() and (child / "config.json").exists():
                return [child]
        if (directory / "config.json").exists():
            return [directory]
        safetensors = sorted(item for item in directory.glob("*.safetensors") if item.is_file())
        if safetensors:
            return safetensors
        return []

    # -- maintenance --------------------------------------------------------

    def backfill_capabilities(self, user_id: int | None = None) -> int:
        """Fill in capabilities for rows created before the registry existed."""
        query = self.db.query(ModelRecord).filter(
            or_(ModelRecord.capabilities.is_(None), ModelRecord.capabilities == "")
        )
        if user_id is not None:
            query = query.filter(
                or_(ModelRecord.user_id == user_id, ModelRecord.user_id.is_(None))
            )
        updated = 0
        for record in query.all():
            self.refresh_capabilities(record, commit=False)
            updated += 1
        if updated:
            self.db.commit()
        return updated

    def set_default(self, user_id: int, model_id: int) -> ModelRecord:
        """Persist a user's preferred default local model."""
        record = self.require(model_id, user_id)
        self.require_ready(record)
        preference = self.db.get(UserModelPreference, user_id)
        if preference is None:
            preference = UserModelPreference(user_id=user_id)
            self.db.add(preference)
        preference.default_kind = "local"
        preference.default_model_ref = str(record.id)
        preference.default_provider_id = None
        self.db.commit()
        return record


def _format_size(bytes_value: int) -> str:
    amount = float(max(0, int(bytes_value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f}{unit}"
        amount /= 1024
    return f"{amount:.1f}PB"


def get_registry(db: DBSession) -> ModelRegistry:
    """Convenience factory used by the API layer."""
    return ModelRegistry(db)


__all__ = [
    "ModelCapability",
    "ModelRegistry",
    "ModelRegistryError",
    "READY_STATUSES",
    "asset_path_available",
    "get_registry",
]
