"""Dataset service: upload, parse, preview, validate, delete training datasets."""
import csv
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from core.config import settings
from models.records import Dataset

ALLOWED_EXTENSIONS = {".jsonl", ".csv", ".json", ".txt"}


class DatasetParser:
    """Parse dataset files into (row_count, columns, sample)."""

    @staticmethod
    def parse(path: str, fmt: str) -> Tuple[int, List[str], List[dict]]:
        if fmt == "jsonl":
            return DatasetParser._parse_jsonl(path)
        if fmt == "csv":
            return DatasetParser._parse_csv(path)
        if fmt == "json":
            return DatasetParser._parse_json(path)
        if fmt == "txt":
            return DatasetParser._parse_txt(path)
        raise ValueError(f"不支持的数据集格式: {fmt}")

    @staticmethod
    def _parse_jsonl(path: str) -> Tuple[int, List[str], List[dict]]:
        rows = []
        columns: List[str] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    if not columns:
                        columns = list(row.keys())
                    rows.append(row)
                elif isinstance(row, (str, int, float)):
                    if not columns:
                        columns = ["text"]
                    rows.append({"text": str(row)})
        return len(rows), columns, rows[:5]

    @staticmethod
    def _parse_csv(path: str) -> Tuple[int, List[str], List[dict]]:
        rows = []
        columns: List[str] = []
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or ["text"]
            for row in reader:
                rows.append({k: v for k, v in row.items()})
        return len(rows), columns, rows[:5]

    @staticmethod
    def _parse_json(path: str) -> Tuple[int, List[str], List[dict]]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        if isinstance(data, list):
            rows = [d for d in data if isinstance(d, dict)]
            columns = list(rows[0].keys()) if rows else []
            return len(rows), columns, rows[:5]
        if isinstance(data, dict):
            # 兼容 {"train": [...]} / {"text": ...} / {"messages": [...]}
            for key in ("train", "data", "examples"):
                if isinstance(data.get(key), list):
                    rows = [d for d in data[key] if isinstance(d, dict)]
                    columns = list(rows[0].keys()) if rows else []
                    return len(rows), columns, rows[:5]
            return 1, list(data.keys()), [data]
        raise ValueError("JSON 数据集必须是对象数组或包含 train 字段的对象")

    @staticmethod
    def _parse_txt(path: str) -> Tuple[int, List[str], List[dict]]:
        lines = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)
        return len(lines), ["text"], [{"text": line_value} for line_value in lines[:5]]


class DatasetService:
    """CRUD for user datasets."""

    def upload(
        self, db: DBSession, user_id: int, original_name: str, content: bytes, name: Optional[str] = None
    ) -> Dataset:
        ext = Path(original_name or "dataset.txt").suffix.lower()
        fmt = ext.lstrip(".")
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型 {ext or '(无扩展名)'}，支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
        if len(content) > settings.max_dataset_size:
            raise ValueError(f"文件过大（{len(content)} 字节），上限 {settings.max_dataset_size} 字节")

        ds_dir = Path(settings.dataset_dir) / str(user_id)
        ds_dir.mkdir(parents=True, exist_ok=True)
        stored = ds_dir / f"{uuid.uuid4().hex[:8]}_{Path(original_name).name}"
        stored.write_bytes(content)

        rec = Dataset(
            user_id=user_id,
            name=(name or Path(original_name).stem).strip() or "dataset",
            file_path=str(stored),
            original_name=original_name,
            format=fmt,
            file_size=len(content),
            status="uploaded",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)

        try:
            row_count, columns, sample = DatasetParser.parse(str(stored), fmt)
            rec.row_count = row_count
            rec.columns = json.dumps(columns, ensure_ascii=False)
            rec.sample = json.dumps(sample, ensure_ascii=False)
            rec.status = "parsed"
        except Exception as e:
            rec.status = "error"
            rec.error = str(e)
        db.commit()
        db.refresh(rec)
        return rec

    def get(self, db: DBSession, dataset_id: int, user_id: int) -> Optional[Dataset]:
        return db.query(Dataset).filter_by(id=dataset_id, user_id=user_id).first()

    def list(self, db: DBSession, user_id: int) -> List[Dataset]:
        return (
            db.query(Dataset)
            .filter_by(user_id=user_id)
            .order_by(Dataset.created_at.desc())
            .all()
        )

    def delete(self, db: DBSession, dataset_id: int, user_id: int) -> bool:
        rec = self.get(db, dataset_id, user_id)
        if not rec:
            return False
        try:
            Path(rec.file_path).unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(rec)
        db.commit()
        return True

    def validate(self, db: DBSession, dataset_id: int, user_id: int) -> Dict:
        rec = self.get(db, dataset_id, user_id)
        if not rec:
            raise ValueError("数据集不存在")
        if rec.status == "error":
            return {"ok": False, "reason": rec.error or "解析失败", "row_count": 0}
        if rec.status != "parsed":
            try:
                row_count, columns, _ = DatasetParser.parse(rec.file_path, rec.format)
                rec.row_count = row_count
                rec.columns = json.dumps(columns, ensure_ascii=False)
                rec.status = "parsed"
                db.commit()
            except Exception as e:
                return {"ok": False, "reason": str(e), "row_count": 0}
        return {"ok": True, "row_count": rec.row_count, "columns": json.loads(rec.columns) if rec.columns else []}