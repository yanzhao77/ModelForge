"""Model Manager - manages AI model lifecycle (scan, list, info, install, remove)."""
from pathlib import Path

from core.config import load_config
from models.records import ModelRecord
from sqlalchemy.orm import Session


class ModelManager:
    """Manages local AI models: scan, list, install, remove, info.

    user_id is optional for backward compatibility: when None, operations
    apply to global models; when set, results are scoped to that user.
    """

    def __init__(self, db: Session):
        self.db = db
        self.config = load_config()
        self.model_path = Path(self.config.model_path).resolve()

    def _contained_model_path(self, path: str | None) -> Path:
        """Resolve a requested model asset without exposing arbitrary host paths."""
        root = self.model_path.resolve()
        candidate = root if path is None else Path(path).expanduser().resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("MODEL_PATH_OUTSIDE_ALLOWED_ROOT")
        return candidate

    def scan(self, path: str | None = None, user_id: int | None = None) -> list[ModelRecord]:
        """Scan a directory for model files and register them in the database.

        Recognizes common model file extensions: .gguf, .bin, .safetensors, .pt, .pth
        and directories containing model config files. Paths must stay under the
        configured model root.
        """
        scan_path = self._contained_model_path(path)
        discovered: list[ModelRecord] = []

        if not scan_path.exists():
            return discovered

        model_extensions = {".gguf", ".bin", ".safetensors", ".pt", ".pth"}

        for entry in scan_path.iterdir():
            if entry.is_file() and entry.suffix.lower() in model_extensions:
                record = self._register_file_model(entry, user_id)
                discovered.append(record)
            elif entry.is_dir() and self._is_model_dir(entry):
                record = self._register_dir_model(entry, user_id)
                discovered.append(record)

        self.db.commit()
        return discovered

    def list(self, user_id: int | None = None) -> list[ModelRecord]:
        """List all registered models."""
        query = self.db.query(ModelRecord)
        if user_id is not None:
            query = query.filter(
                (ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))
            )
        return query.order_by(ModelRecord.created_time.desc()).all()

    def info(self, model_id: int, user_id: int | None = None) -> ModelRecord | None:
        """Get a model only when it is owned by the caller or intentionally global."""
        query = self.db.query(ModelRecord).filter_by(id=model_id)
        if user_id is not None:
            query = query.filter(
                (ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))
            )
        return query.first()

    def install(
        self, name: str, provider: str, path: str, size: str = "",
        user_id: int | None = None, model_format: str | None = None, quant: str | None = None,
    ) -> ModelRecord:
        """Register an installed model from an already contained model asset."""
        resolved_path = self._contained_model_path(path)
        query = self.db.query(ModelRecord).filter_by(name=name)
        if user_id is not None:
            query = query.filter(
                (ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))
            )
        existing = query.first()
        if existing:
            existing.path = str(resolved_path)
            existing.provider = provider
            existing.size = size
            existing.status = "available"
            if model_format:
                existing.format = model_format
            if quant:
                existing.quant = quant
        else:
            existing = ModelRecord(
                name=name,
                provider=provider,
                path=str(resolved_path),
                size=size,
                status="available",
                user_id=user_id,
                format=model_format,
                quant=quant,
            )
            self.db.add(existing)
        self.db.commit()
        return existing

    def remove(self, model_id: int, user_id: int | None = None) -> bool:
        """Remove a model from the database (does not delete files)."""
        query = self.db.query(ModelRecord).filter_by(id=model_id)
        if user_id is not None:
            query = query.filter(
                (ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))
            )
        model = query.first()
        if not model:
            return False
        self.db.delete(model)
        self.db.commit()
        return True

    def _register_file_model(
        self, filepath: Path, user_id: int | None = None
    ) -> ModelRecord:
        """Register a single model file."""
        name = filepath.stem
        query = self.db.query(ModelRecord).filter_by(name=name)
        if user_id is not None:
            query = query.filter(
                (ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))
            )
        existing = query.first()
        if existing:
            existing.path = str(filepath)
            existing.size = self._format_size(filepath.stat().st_size)
            existing.status = "available"
            return existing

        record = ModelRecord(
            name=name,
            provider="local",
            path=str(filepath),
            size=self._format_size(filepath.stat().st_size),
            status="available",
            user_id=user_id,
            format="gguf" if filepath.suffix.lower() == ".gguf" else None,
        )
        self.db.add(record)
        return record

    def _register_dir_model(
        self, dirpath: Path, user_id: int | None = None
    ) -> ModelRecord:
        """Register a model directory (contains config.json or similar)."""
        name = dirpath.name
        total_size = sum(
            f.stat().st_size for f in dirpath.rglob("*") if f.is_file()
        )
        query = self.db.query(ModelRecord).filter_by(name=name)
        if user_id is not None:
            query = query.filter(
                (ModelRecord.user_id == user_id) | (ModelRecord.user_id.is_(None))
            )
        existing = query.first()
        if existing:
            existing.path = str(dirpath)
            existing.size = self._format_size(total_size)
            existing.status = "available"
            return existing

        record = ModelRecord(
            name=name,
            provider="local",
            path=str(dirpath),
            size=self._format_size(total_size),
            status="available",
            user_id=user_id,
            format="safetensors",
        )
        self.db.add(record)
        return record

    @staticmethod
    def _is_model_dir(path: Path) -> bool:
        """Check if a directory looks like a model directory."""
        indicators = ["config.json", "pytorch_model.bin", "model.safetensors",
                      "tokenizer.json", "tokenizer_config.json"]
        return any((path / ind).exists() for ind in indicators)

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        """Format bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f}{unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f}PB"