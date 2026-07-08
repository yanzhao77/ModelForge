"""Model Manager - manages AI model lifecycle (scan, list, info, install, remove)."""
import os
import datetime
from pathlib import Path
from typing import List, Optional, Dict

from sqlalchemy.orm import Session

from core.config import load_config
from models.records import ModelRecord


class ModelManager:
    """Manages local AI models: scan, list, install, remove, info."""

    def __init__(self, db: Session):
        self.db = db
        self.config = load_config()
        self.model_path = Path(self.config.model_path).resolve()

    def scan(self, path: Optional[str] = None) -> List[ModelRecord]:
        """Scan a directory for model files and register them in the database.

        Recognizes common model file extensions: .gguf, .bin, .safetensors, .pt, .pth
        and directories containing model config files.
        """
        scan_path = Path(path).resolve() if path else self.model_path
        discovered: List[ModelRecord] = []

        if not scan_path.exists():
            return discovered

        model_extensions = {".gguf", ".bin", ".safetensors", ".pt", ".pth"}

        for entry in scan_path.iterdir():
            if entry.is_file() and entry.suffix.lower() in model_extensions:
                record = self._register_file_model(entry)
                discovered.append(record)
            elif entry.is_dir() and self._is_model_dir(entry):
                record = self._register_dir_model(entry)
                discovered.append(record)

        self.db.commit()
        return discovered

    def list(self) -> List[ModelRecord]:
        """List all registered models."""
        return self.db.query(ModelRecord).order_by(ModelRecord.created_time.desc()).all()

    def info(self, model_id: int) -> Optional[ModelRecord]:
        """Get detailed info about a specific model."""
        return self.db.query(ModelRecord).filter_by(id=model_id).first()

    def install(self, name: str, provider: str, path: str, size: str = "") -> ModelRecord:
        """Register an installed model."""
        existing = self.db.query(ModelRecord).filter_by(name=name).first()
        if existing:
            existing.path = path
            existing.provider = provider
            existing.size = size
            existing.status = "available"
        else:
            existing = ModelRecord(
                name=name,
                provider=provider,
                path=path,
                size=size,
                status="available",
            )
            self.db.add(existing)
        self.db.commit()
        return existing

    def remove(self, model_id: int) -> bool:
        """Remove a model from the database (does not delete files)."""
        model = self.db.query(ModelRecord).filter_by(id=model_id).first()
        if not model:
            return False
        self.db.delete(model)
        self.db.commit()
        return True

    def _register_file_model(self, filepath: Path) -> ModelRecord:
        """Register a single model file."""
        name = filepath.stem
        existing = self.db.query(ModelRecord).filter_by(name=name).first()
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
        )
        self.db.add(record)
        return record

    def _register_dir_model(self, dirpath: Path) -> ModelRecord:
        """Register a model directory (contains config.json or similar)."""
        name = dirpath.name
        total_size = sum(
            f.stat().st_size for f in dirpath.rglob("*") if f.is_file()
        )
        existing = self.db.query(ModelRecord).filter_by(name=name).first()
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
