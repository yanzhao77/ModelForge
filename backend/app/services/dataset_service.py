"""Dataset service: upload, parse, preview, validate, delete training datasets."""
import csv
import json
import uuid
from pathlib import Path

from core.config import settings
from models.records import Dataset
from sqlalchemy.orm import Session as DBSession

ALLOWED_EXTENSIONS = {".jsonl", ".csv", ".json", ".txt"}

# Stable, path-free code returned to clients when a dataset cannot be parsed.
PARSE_FAILED_CODE = "DATASET_PARSE_FAILED"
PARSE_FAILED_MESSAGE = "数据集解析失败，请检查文件格式与编码"


def _parse_failure_detail(exc: Exception) -> str:
    """Keep the failure diagnosable without echoing paths or file contents."""
    return f"{PARSE_FAILED_CODE}:{type(exc).__name__}"


class DatasetParser:
    """Parse dataset files into (row_count, columns, sample)."""

    SAMPLE_ROWS = 5

    @staticmethod
    def parse(path: str, fmt: str) -> tuple[int, list[str], list[dict]]:
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
    def _parse_jsonl(path: str) -> tuple[int, list[str], list[dict]]:
        count = 0
        sample: list[dict] = []
        columns: list[str] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    count += 1
                    if not columns:
                        columns = list(row.keys())
                    if len(sample) < DatasetParser.SAMPLE_ROWS:
                        sample.append(row)
                elif isinstance(row, (str, int, float)):
                    count += 1
                    if not columns:
                        columns = ["text"]
                    if len(sample) < DatasetParser.SAMPLE_ROWS:
                        sample.append({"text": str(row)})
        return count, columns, sample

    @staticmethod
    def _parse_csv(path: str) -> tuple[int, list[str], list[dict]]:
        count = 0
        sample: list[dict] = []
        columns: list[str] = []
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or ["text"]
            for row in reader:
                count += 1
                if len(sample) < DatasetParser.SAMPLE_ROWS:
                    sample.append({k: v for k, v in row.items()})
        return count, columns, sample

    @staticmethod
    def _parse_json(path: str) -> tuple[int, list[str], list[dict]]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        if isinstance(data, list):
            return DatasetParser._count_and_sample(data)
        if isinstance(data, dict):
            # 兼容 {"train": [...]} / {"text": ...} / {"messages": [...]}
            for key in ("train", "data", "examples"):
                if isinstance(data.get(key), list):
                    return DatasetParser._count_and_sample(data[key])
            return 1, list(data.keys()), [data]
        raise ValueError("JSON 数据集必须是对象数组或包含 train 字段的对象")

    @staticmethod
    def _count_and_sample(items: list) -> tuple[int, list[str], list[dict]]:
        """Count object rows without materialising a second copy of the list."""
        count = 0
        sample: list[dict] = []
        for item in items:
            if isinstance(item, dict):
                count += 1
                if len(sample) < DatasetParser.SAMPLE_ROWS:
                    sample.append(item)
        columns = list(sample[0].keys()) if sample else []
        return count, columns, sample

    @staticmethod
    def _parse_txt(path: str) -> tuple[int, list[str], list[dict]]:
        count = 0
        sample: list[dict] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    count += 1
                    if len(sample) < DatasetParser.SAMPLE_ROWS:
                        sample.append({"text": line})
        return count, ["text"], sample


class DatasetService:
    """CRUD for user datasets."""

    def _upload_path(self, user_id: int, original_name: str) -> tuple[Path, str]:
        ext = Path(original_name or "dataset.txt").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型 {ext or '(无扩展名)'}，支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
        ds_dir = Path(settings.dataset_dir) / str(user_id)
        ds_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe_name = Path(original_name or "dataset").name
        return ds_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}", ext.lstrip(".")

    def _persist_and_parse(
        self,
        db: DBSession,
        user_id: int,
        original_name: str,
        name: str | None,
        stored: Path,
        fmt: str,
        file_size: int,
    ) -> Dataset:
        rec = Dataset(
            user_id=user_id,
            name=(name or Path(original_name).stem).strip() or "dataset",
            file_path=str(stored),
            original_name=Path(original_name).name,
            format=fmt,
            file_size=file_size,
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
        except Exception as exc:
            rec.status = "error"
            rec.error = _parse_failure_detail(exc)
        db.commit()
        db.refresh(rec)
        return rec

    def upload_stream(
        self,
        db: DBSession,
        user_id: int,
        original_name: str,
        stream,
        name: str | None = None,
        chunk_size: int = 64 * 1024,
    ) -> Dataset:
        """Store an uploaded stream while enforcing the byte ceiling incrementally."""
        stored, fmt = self._upload_path(user_id, original_name)
        total = 0
        try:
            with stored.open("wb") as handle:
                while chunk := stream.read(chunk_size):
                    total += len(chunk)
                    if total > settings.max_dataset_size:
                        raise ValueError("DATASET_FILE_TOO_LARGE")
                    handle.write(chunk)
        except Exception:
            stored.unlink(missing_ok=True)
            raise
        return self._persist_and_parse(db, user_id, original_name, name, stored, fmt, total)

    def upload(
        self, db: DBSession, user_id: int, original_name: str, content: bytes, name: str | None = None
    ) -> Dataset:
        """Backward-compatible byte input for internal callers; HTTP uses upload_stream."""
        from io import BytesIO

        return self.upload_stream(db, user_id, original_name, BytesIO(content), name)

    def get(self, db: DBSession, dataset_id: int, user_id: int) -> Dataset | None:
        return db.query(Dataset).filter_by(id=dataset_id, user_id=user_id).first()

    def list(self, db: DBSession, user_id: int) -> list[Dataset]:
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

    def validate(self, db: DBSession, dataset_id: int, user_id: int) -> dict:
        rec = self.get(db, dataset_id, user_id)
        if not rec:
            raise ValueError("数据集不存在")
        if rec.status == "error":
            return {
                "ok": False,
                "reason": PARSE_FAILED_MESSAGE,
                "code": PARSE_FAILED_CODE,
                "detail": rec.error or PARSE_FAILED_CODE,
                "row_count": 0,
            }
        if rec.status != "parsed":
            try:
                row_count, columns, _ = DatasetParser.parse(rec.file_path, rec.format)
                rec.row_count = row_count
                rec.columns = json.dumps(columns, ensure_ascii=False)
                rec.status = "parsed"
                db.commit()
            except Exception as e:
                return {
                    "ok": False,
                    "reason": PARSE_FAILED_MESSAGE,
                    "code": PARSE_FAILED_CODE,
                    "detail": _parse_failure_detail(e),
                    "row_count": 0,
                }
        return {"ok": True, "row_count": rec.row_count, "columns": json.loads(rec.columns) if rec.columns else []}
