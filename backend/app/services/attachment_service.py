"""Managed attachment storage and preview helpers."""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import wave
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree as ET

from core.config import settings
from models.records import (
    AttachmentDerivativeRecord,
    AttachmentRecord,
    ChatTurnRecord,
    Message,
    MessageAttachment,
)
from sqlalchemy.orm import Session as DBSession

TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "application/x-ndjson",
    "text/csv",
    "text/tab-separated-values",
    "text/x-log",
    "text/x-python",
    "text/x-source",
}
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
PDF_MIME_TYPES = {"application/pdf"}
OFFICE_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
AUDIO_MIME_TYPES = {"audio/wav", "audio/x-wav", "audio/wave"}
VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_MIME_TYPES = TEXT_MIME_TYPES | IMAGE_MIME_TYPES | PDF_MIME_TYPES | OFFICE_MIME_TYPES | AUDIO_MIME_TYPES | VIDEO_MIME_TYPES
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".csv", ".tsv", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".css", ".html", ".xml", ".yaml", ".yml", ".toml", ".ini",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {".docx", ".xlsx"}
AUDIO_EXTENSIONS = {".wav"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}
PREVIEW_BYTES = 200 * 1024
CHUNK_SIZE = 1024 * 1024


class AttachmentError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


class AttachmentService:
    def __init__(self, root: str | os.PathLike[str] | None = None, *, max_bytes: int | None = None):
        self.root = Path(root or settings.data_dir) / "attachments"
        self.max_bytes = int(max_bytes or min(settings.max_upload_size, 100 * 1024 * 1024))

    def upload_stream(
        self,
        db: DBSession,
        user_id: int,
        display_name: str,
        stream: BinaryIO,
        content_type: str | None = None,
    ) -> AttachmentRecord:
        name = _sanitize_name(display_name or "attachment")
        suffix = Path(name).suffix.lower()
        attachment_id = f"att_{uuid.uuid4().hex}"
        base_dir = self.root / str(user_id) / attachment_id
        tmp_dir = base_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / "upload.part"
        final_path = base_dir / "original"

        sha = hashlib.sha256()
        total = 0
        first = b""
        try:
            with tmp_path.open("wb") as out:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        chunk = bytes(chunk)
                    if not first:
                        first = chunk[:64]
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise AttachmentError("ATTACHMENT_LIMIT_EXCEEDED", "Attachment exceeds the configured upload limit.")
                    sha.update(chunk)
                    out.write(chunk)
            if total <= 0:
                raise AttachmentError("ATTACHMENT_INVALID", "Attachment is empty.")
            mime_type = _detect_mime(first, suffix, content_type)
            if mime_type not in ALLOWED_MIME_TYPES:
                raise AttachmentError("ATTACHMENT_TYPE_UNSUPPORTED", "Attachment type is not supported.")
            base_dir.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_path, final_path)
        except Exception:
            with contextlib_suppress_oserror():
                tmp_path.unlink()
            raise

        now = dt.datetime.utcnow()
        rec = AttachmentRecord(
            id=attachment_id,
            user_id=user_id,
            display_name=name,
            storage_key=str(final_path.relative_to(self.root.parent)),
            sha256=sha.hexdigest(),
            mime_type=mime_type,
            size_bytes=total,
            state="READY",
            metadata_json=json.dumps(_initial_metadata(mime_type, suffix), ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        db.add(rec)
        db.flush()
        self._create_builtin_preview(db, rec, final_path)
        db.commit()
        db.refresh(rec)
        return rec

    def get(self, db: DBSession, user_id: int, attachment_id: str) -> AttachmentRecord | None:
        return (
            db.query(AttachmentRecord)
            .filter(
                AttachmentRecord.id == attachment_id,
                AttachmentRecord.user_id == user_id,
                AttachmentRecord.deleted_at.is_(None),
            )
            .first()
        )

    def require(self, db: DBSession, user_id: int, attachment_id: str) -> AttachmentRecord:
        rec = self.get(db, user_id, attachment_id)
        if rec is None:
            raise AttachmentError("ATTACHMENT_UNAVAILABLE", "Attachment is not available.")
        return rec

    def path_for(self, rec: AttachmentRecord) -> Path:
        path = self.root.parent / rec.storage_key
        root = self.root.resolve()
        resolved = path.resolve()
        if root not in resolved.parents and resolved != root:
            raise AttachmentError("ATTACHMENT_INVALID", "Attachment storage path is invalid.")
        return resolved

    def derivative_path_for(self, derivative: AttachmentDerivativeRecord) -> Path:
        if not derivative.storage_key:
            raise AttachmentError("ATTACHMENT_UNAVAILABLE", "Attachment derivative has no downloadable content.")
        path = self.root.parent / derivative.storage_key
        root = self.root.resolve()
        resolved = path.resolve()
        if root not in resolved.parents and resolved != root:
            raise AttachmentError("ATTACHMENT_INVALID", "Attachment derivative storage path is invalid.")
        return resolved

    def require_derivative(
        self,
        db: DBSession,
        user_id: int,
        attachment_id: str,
        derivative_id: str,
    ) -> tuple[AttachmentRecord, AttachmentDerivativeRecord]:
        rec = self.require(db, user_id, attachment_id)
        derivative = (
            db.query(AttachmentDerivativeRecord)
            .filter(
                AttachmentDerivativeRecord.id == derivative_id,
                AttachmentDerivativeRecord.source_attachment_id == rec.id,
                AttachmentDerivativeRecord.storage_key.isnot(None),
            )
            .first()
        )
        if derivative is None:
            raise AttachmentError("ATTACHMENT_UNAVAILABLE", "Attachment derivative is not available.")
        return rec, derivative

    def list_for_session(self, db: DBSession, user_id: int, session_id: int) -> list[AttachmentRecord]:
        from models.records import Message, MessageAttachment

        return (
            db.query(AttachmentRecord)
            .join(MessageAttachment, MessageAttachment.attachment_id == AttachmentRecord.id)
            .join(Message, Message.id == MessageAttachment.message_id)
            .filter(
                Message.session_id == session_id,
                AttachmentRecord.user_id == user_id,
                AttachmentRecord.deleted_at.is_(None),
            )
            .order_by(AttachmentRecord.created_at.desc())
            .all()
        )

    def reconcile_storage(self, db: DBSession, *, max_tmp_age_seconds: int = 24 * 60 * 60) -> dict:
        now = time.time()
        known_keys = {row[0] for row in db.query(AttachmentRecord.storage_key).all() if row[0]}
        known_keys.update(row[0] for row in db.query(AttachmentDerivativeRecord.storage_key).all() if row[0])
        orphan_files: list[str] = []
        expired_temporary_files: list[str] = []
        missing_files: list[str] = []
        root = self.root.resolve()
        root_parent = self.root.parent.resolve()
        for key in sorted(known_keys):
            path = root_parent / key
            try:
                resolved = path.resolve()
            except OSError:
                missing_files.append(key)
                continue
            if not resolved.exists():
                missing_files.append(key)
        if not root.exists():
            return {"missing_files": missing_files, "orphan_files": orphan_files, "expired_temporary_files": expired_temporary_files}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel_key = str(path.resolve().relative_to(root_parent))
            except (OSError, ValueError):
                continue
            if rel_key in known_keys:
                continue
            if path.parent.name == "tmp" and now - path.stat().st_mtime > max(0, max_tmp_age_seconds):
                expired_temporary_files.append(rel_key)
            else:
                orphan_files.append(rel_key)
        return {"missing_files": missing_files, "orphan_files": orphan_files, "expired_temporary_files": expired_temporary_files}

    def reference_summary(self, db: DBSession, user_id: int, attachment_id: str) -> dict:
        messages = (
            db.query(Message)
            .join(MessageAttachment, MessageAttachment.message_id == Message.id)
            .filter(MessageAttachment.attachment_id == attachment_id)
            .order_by(Message.timestamp.asc(), Message.id.asc())
            .all()
        )
        message_refs = [
            {
                "message_id": item.id,
                "session_id": item.session_id,
                "role": item.role,
                "turn_id": item.turn_id,
                "status": item.status,
            }
            for item in messages
        ]
        turn_ids = sorted({item.turn_id for item in messages if item.turn_id})
        active_statuses = {"QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"}
        turns = []
        active_turns = []
        if turn_ids:
            turn_rows = (
                db.query(ChatTurnRecord)
                .filter(ChatTurnRecord.user_id == user_id, ChatTurnRecord.id.in_(turn_ids))
                .order_by(ChatTurnRecord.created_at.asc())
                .all()
            )
            for turn in turn_rows:
                item = {
                    "turn_id": turn.id,
                    "session_id": turn.session_id,
                    "status": turn.status,
                    "mode": turn.mode,
                }
                turns.append(item)
                if turn.status in active_statuses:
                    active_turns.append(item)
        return {
            "attachment_id": attachment_id,
            "message_count": len(message_refs),
            "messages": message_refs,
            "turns": turns,
            "active_turns": active_turns,
            "blocks_delete": bool(active_turns),
        }

    def delete(self, db: DBSession, user_id: int, attachment_id: str) -> dict:
        rec = self.require(db, user_id, attachment_id)
        summary = self.reference_summary(db, user_id, rec.id)
        if summary["blocks_delete"]:
            raise AttachmentError("ATTACHMENT_IN_USE", "Attachment is referenced by an active chat turn and cannot be deleted yet.")
        rec.state = "DELETED"
        rec.deleted_at = dt.datetime.utcnow()
        rec.updated_at = dt.datetime.utcnow()
        db.commit()
        return {"attachment": rec.to_dict(), "references": summary, "physical_cleanup": "deferred"}

    def cleanup_unreferenced_deleted(self, db: DBSession, user_id: int | None = None, *, limit: int = 100) -> dict:
        query = db.query(AttachmentRecord).filter(AttachmentRecord.deleted_at.isnot(None))
        if user_id is not None:
            query = query.filter(AttachmentRecord.user_id == user_id)
        rows = query.order_by(AttachmentRecord.deleted_at.asc()).limit(max(1, limit)).all()
        deleted_files: list[str] = []
        skipped: list[dict] = []
        for rec in rows:
            summary = self.reference_summary(db, rec.user_id, rec.id)
            if summary["message_count"]:
                skipped.append({"attachment_id": rec.id, "reason": "REFERENCED_BY_MESSAGE", "message_count": summary["message_count"]})
                continue
            paths = [self.path_for(rec)]
            derivatives = db.query(AttachmentDerivativeRecord).filter(AttachmentDerivativeRecord.source_attachment_id == rec.id).all()
            for derivative in derivatives:
                if derivative.storage_key:
                    paths.append(self.derivative_path_for(derivative))
            for path in paths:
                try:
                    path.unlink()
                    deleted_files.append(str(path.relative_to(self.root.parent)))
                except FileNotFoundError:
                    continue
            for derivative in derivatives:
                db.delete(derivative)
            db.delete(rec)
        db.commit()
        return {"deleted_files": deleted_files, "skipped": skipped}

    def preview(self, db: DBSession, rec: AttachmentRecord) -> dict:
        derivatives = (
            db.query(AttachmentDerivativeRecord)
            .filter(AttachmentDerivativeRecord.source_attachment_id == rec.id)
            .order_by(AttachmentDerivativeRecord.created_at.desc())
            .all()
        )
        payload = {"attachment": rec.to_dict(), "derivatives": [item.to_dict() for item in derivatives]}
        text_derivative = next((item for item in derivatives if item.kind == "text_preview" and item.storage_key), None)
        if text_derivative is not None:
            text_path = self.root.parent / text_derivative.storage_key
            try:
                payload["text"] = text_path.read_text(encoding="utf-8")
            except OSError:
                payload["text"] = ""
        return payload

    def _create_builtin_preview(self, db: DBSession, rec: AttachmentRecord, path: Path) -> None:
        now = dt.datetime.utcnow()
        if rec.mime_type in TEXT_MIME_TYPES:
            preview_path = path.parent / "preview.txt"
            raw = path.read_bytes()[:PREVIEW_BYTES]
            try:
                text = raw.decode("utf-8")
                state = "SUCCEEDED"
                error_code = None
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
                state = "FAILED"
                error_code = "TEXT_ENCODING_REPLACED"
            preview_path.write_text(text, encoding="utf-8")
            metadata = {"bytes": min(rec.size_bytes, PREVIEW_BYTES), "truncated": rec.size_bytes > PREVIEW_BYTES}
            db.add(
                AttachmentDerivativeRecord(
                    id=f"der_{uuid.uuid4().hex}",
                    source_attachment_id=rec.id,
                    kind="text_preview",
                    processor_version="builtin-text-v1",
                    storage_key=str(preview_path.relative_to(self.root.parent)),
                    state=state,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    error_code=error_code,
                    created_at=now,
                )
            )
        elif rec.mime_type in OFFICE_MIME_TYPES:
            preview_path = path.parent / "preview.txt"
            metadata = {"bytes_limit": PREVIEW_BYTES, "truncated": False}
            try:
                text, extra_metadata = _office_text_preview(path, rec.mime_type)
                metadata.update(extra_metadata)
                if len(text.encode("utf-8")) > PREVIEW_BYTES:
                    text = text.encode("utf-8")[:PREVIEW_BYTES].decode("utf-8", errors="ignore")
                    metadata["truncated"] = True
                preview_path.write_text(text, encoding="utf-8")
                state = "SUCCEEDED" if text.strip() else "FAILED"
                error_code = None if text.strip() else "OFFICE_TEXT_EMPTY"
            except AttachmentError:
                raise
            except Exception:
                preview_path.write_text("", encoding="utf-8")
                state = "FAILED"
                error_code = "OFFICE_TEXT_UNAVAILABLE"
            db.add(
                AttachmentDerivativeRecord(
                    id=f"der_{uuid.uuid4().hex}",
                    source_attachment_id=rec.id,
                    kind="text_preview",
                    processor_version="builtin-ooxml-v1",
                    storage_key=str(preview_path.relative_to(self.root.parent)),
                    state=state,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    error_code=error_code,
                    created_at=now,
                )
            )
        elif rec.mime_type in PDF_MIME_TYPES:
            preview_path = path.parent / "preview.txt"
            metadata = {"bytes_limit": PREVIEW_BYTES, "truncated": False}
            try:
                text, extra_metadata = _pdf_text_preview(path)
                metadata.update(extra_metadata)
                if len(text.encode("utf-8")) > PREVIEW_BYTES:
                    text = text.encode("utf-8")[:PREVIEW_BYTES].decode("utf-8", errors="ignore")
                    metadata["truncated"] = True
                preview_path.write_text(text, encoding="utf-8")
                state = "SUCCEEDED" if text.strip() else "FAILED"
                error_code = None if text.strip() else "PDF_TEXT_EMPTY"
            except Exception:
                preview_path.write_text("", encoding="utf-8")
                state = "FAILED"
                error_code = "PDF_TEXT_UNAVAILABLE"
            db.add(
                AttachmentDerivativeRecord(
                    id=f"der_{uuid.uuid4().hex}",
                    source_attachment_id=rec.id,
                    kind="text_preview",
                    processor_version="builtin-pdf-basic-v1",
                    storage_key=str(preview_path.relative_to(self.root.parent)),
                    state=state,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    error_code=error_code,
                    created_at=now,
                )
            )
        else:
            if rec.mime_type in IMAGE_MIME_TYPES:
                kind = "image_preview"
            elif rec.mime_type in AUDIO_MIME_TYPES:
                kind = "audio_metadata"
            elif rec.mime_type in VIDEO_MIME_TYPES:
                kind = "video_metadata"
            else:
                kind = "pdf_placeholder"
            metadata = {"native_preview": rec.mime_type in IMAGE_MIME_TYPES, "playable": rec.mime_type in (AUDIO_MIME_TYPES | VIDEO_MIME_TYPES)}
            if rec.mime_type in IMAGE_MIME_TYPES:
                metadata.update(_image_metadata(path))
                thumbnail_path = path.parent / "thumbnail.jpg"
                metadata.update(_create_image_thumbnail(path, thumbnail_path))
            elif rec.mime_type in AUDIO_MIME_TYPES:
                metadata.update(_wav_metadata(path))
            elif rec.mime_type in VIDEO_MIME_TYPES:
                metadata.update(_video_metadata(path))
            preview_succeeded = rec.mime_type in (IMAGE_MIME_TYPES | AUDIO_MIME_TYPES) or (
                rec.mime_type in VIDEO_MIME_TYPES and "metadata_error" not in metadata
            )
            db.add(
                AttachmentDerivativeRecord(
                    id=f"der_{uuid.uuid4().hex}",
                    source_attachment_id=rec.id,
                    kind=kind,
                    processor_version="builtin-metadata-v1",
                    storage_key=str(thumbnail_path.relative_to(self.root.parent)) if rec.mime_type in IMAGE_MIME_TYPES and thumbnail_path.exists() else None,
                    state="SUCCEEDED" if preview_succeeded else "FAILED",
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    error_code=None if preview_succeeded else "MEDIA_CODEC_UNAVAILABLE" if rec.mime_type in VIDEO_MIME_TYPES else "PROCESSOR_UNAVAILABLE",
                    created_at=now,
                )
            )
            if rec.mime_type in VIDEO_MIME_TYPES:
                frame_path = path.parent / "frame_0001.jpg"
                frame_metadata = _extract_video_frame(path, frame_path, time_ms=0)
                frame_succeeded = frame_path.exists() and "frame_error" not in frame_metadata
                db.add(
                    AttachmentDerivativeRecord(
                        id=f"der_{uuid.uuid4().hex}",
                        source_attachment_id=rec.id,
                        kind="video_frame",
                        processor_version="ffmpeg-frame-v1",
                        storage_key=str(frame_path.relative_to(self.root.parent)) if frame_succeeded else None,
                        state="SUCCEEDED" if frame_succeeded else "FAILED",
                        metadata_json=json.dumps(frame_metadata, ensure_ascii=False),
                        error_code=None if frame_succeeded else str(frame_metadata.get("frame_error", "VIDEO_FRAME_UNAVAILABLE")),
                        created_at=now,
                    )
                )


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", name).strip().strip(".")
    return cleaned[:512] or "attachment"


def _detect_mime(first: bytes, suffix: str, content_type: str | None) -> str:
    hinted = (content_type or "").split(";", 1)[0].strip().lower()
    if first.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if first.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if first.startswith(b"RIFF") and first[8:12] == b"WEBP":
        return "image/webp"
    if first.startswith(b"RIFF") and first[8:12] == b"WAVE":
        return "audio/wav"
    if first.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if len(first) >= 12 and first[4:8] == b"ftyp":
        return "video/quicktime" if suffix == ".mov" else "video/mp4"
    if first.startswith(b"%PDF-"):
        return "application/pdf"
    if first.startswith(b"PK\x03\x04") and suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if first.startswith(b"PK\x03\x04") and suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix in IMAGE_EXTENSIONS:
        raise AttachmentError("ATTACHMENT_INVALID", "Image extension does not match the file header.")
    if suffix in PDF_EXTENSIONS:
        raise AttachmentError("ATTACHMENT_INVALID", "PDF extension does not match the file header.")
    if suffix in OFFICE_EXTENSIONS:
        raise AttachmentError("ATTACHMENT_INVALID", "Office extension does not match the file header.")
    if suffix in AUDIO_EXTENSIONS:
        raise AttachmentError("ATTACHMENT_INVALID", "Audio extension does not match the file header.")
    if suffix in VIDEO_EXTENSIONS:
        raise AttachmentError("ATTACHMENT_INVALID", "Video extension does not match the file header.")
    if suffix in TEXT_EXTENSIONS or hinted in TEXT_MIME_TYPES:
        return _text_mime_for_suffix(suffix, hinted)
    return hinted or "application/octet-stream"


def _text_mime_for_suffix(suffix: str, hinted: str) -> str:
    if suffix == ".md" or suffix == ".markdown":
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".tsv":
        return "text/tab-separated-values"
    if suffix == ".log":
        return "text/x-log"
    return hinted if hinted in TEXT_MIME_TYPES else "text/plain"


def _initial_metadata(mime_type: str, suffix: str) -> dict:
    category = "image" if mime_type in IMAGE_MIME_TYPES else "pdf" if mime_type in PDF_MIME_TYPES else "text"
    if mime_type in OFFICE_MIME_TYPES:
        category = "office"
    if mime_type in AUDIO_MIME_TYPES:
        category = "audio"
    elif mime_type in VIDEO_MIME_TYPES:
        category = "video"
    return {"category": category, "extension": suffix}


def _image_metadata(path: Path) -> dict:
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            pixels = int(width) * int(height)
            if pixels > 40_000_000:
                raise AttachmentError("ATTACHMENT_LIMIT_EXCEEDED", "Image dimensions exceed the configured pixel limit.")
            return {"width": int(width), "height": int(height), "pixels": pixels, "format": image.format}
    except AttachmentError:
        raise
    except Exception:
        return {"metadata_error": "IMAGE_METADATA_UNAVAILABLE"}


def _create_image_thumbnail(path: Path, thumbnail_path: Path) -> dict:
    try:
        from PIL import Image

        with Image.open(path) as image:
            thumb = image.copy()
            thumb.thumbnail((384, 384))
            if thumb.mode not in {"RGB", "L"}:
                thumb = thumb.convert("RGB")
            thumb.save(thumbnail_path, format="JPEG", quality=82, optimize=True)
            return {
                "thumbnail_mime_type": "image/jpeg",
                "thumbnail_width": int(thumb.width),
                "thumbnail_height": int(thumb.height),
            }
    except Exception:
        with contextlib_suppress_oserror():
            thumbnail_path.unlink()
        return {"thumbnail_error": "IMAGE_THUMBNAIL_UNAVAILABLE"}


def _wav_metadata(path: Path) -> dict:
    try:
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            duration_ms = int(frames * 1000 / rate) if rate else 0
            return {
                "duration_ms": duration_ms,
                "sample_rate": rate,
                "channels": audio.getnchannels(),
                "sample_width_bytes": audio.getsampwidth(),
                "frames": frames,
            }
    except Exception:
        return {"metadata_error": "AUDIO_METADATA_UNAVAILABLE"}


def _video_metadata(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"metadata_error": "FFPROBE_UNAVAILABLE"}
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"metadata_error": "VIDEO_METADATA_UNAVAILABLE"}
    if completed.returncode != 0:
        return {"metadata_error": "VIDEO_METADATA_UNAVAILABLE"}
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"metadata_error": "VIDEO_METADATA_UNAVAILABLE"}
    streams = payload.get("streams") if isinstance(payload, dict) else None
    video_stream = next((item for item in streams or [] if item.get("codec_type") == "video"), {})
    audio_stream = next((item for item in streams or [] if item.get("codec_type") == "audio"), {})
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    metadata: dict[str, int | float | str | bool] = {
        "has_video": bool(video_stream),
        "has_audio": bool(audio_stream),
    }
    if video_stream.get("width") is not None:
        metadata["width"] = int(video_stream["width"])
    if video_stream.get("height") is not None:
        metadata["height"] = int(video_stream["height"])
    if video_stream.get("codec_name"):
        metadata["video_codec"] = str(video_stream["codec_name"])
    if audio_stream.get("codec_name"):
        metadata["audio_codec"] = str(audio_stream["codec_name"])
    if fmt.get("duration"):
        metadata["duration_ms"] = int(float(fmt["duration"]) * 1000)
    if fmt.get("bit_rate"):
        metadata["bit_rate"] = int(float(fmt["bit_rate"]))
    return metadata


def _extract_video_frame(path: Path, frame_path: Path, *, time_ms: int = 0) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"frame_error": "FFMPEG_UNAVAILABLE", "time_ms": time_ms}
    with contextlib_suppress_oserror():
        frame_path.unlink()
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0, time_ms) / 1000:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-y",
                str(frame_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"frame_error": "VIDEO_FRAME_UNAVAILABLE", "time_ms": time_ms}
    if completed.returncode != 0 or not frame_path.exists():
        return {"frame_error": "VIDEO_FRAME_UNAVAILABLE", "time_ms": time_ms}
    metadata = {"time_ms": time_ms, "mime_type": "image/jpeg"}
    metadata.update(_image_metadata(frame_path))
    return metadata


def _pdf_text_preview(path: Path) -> tuple[str, dict]:
    raw = path.read_bytes()
    if len(raw) > 50 * 1024 * 1024:
        raise AttachmentError("ATTACHMENT_LIMIT_EXCEEDED", "PDF exceeds the configured processing limit.")
    page_count = len(re.findall(rb"/Type\s*/Page\b", raw))
    streams = list(_pdf_streams(raw))[:200]
    texts: list[tuple[int, str]] = []
    decoded_streams = 0
    for stream, compressed in streams:
        payload = stream
        if compressed:
            try:
                payload = zlib.decompress(stream)
            except zlib.error:
                continue
        decoded_streams += 1
        text = _pdf_text_from_content_stream(payload)
        if text:
            texts.append((len(texts) + 1, text))
    combined = "\n\n".join(f"[Page {page}]\n{text}" for page, text in texts)
    return combined, {
        "processor": "builtin-pdf-basic",
        "pages_detected": page_count or len(texts),
        "content_streams": len(streams),
        "decoded_streams": decoded_streams,
        "ocr_required": not bool(combined.strip()),
    }


def _pdf_streams(raw: bytes):
    for match in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", raw, flags=re.S):
        dictionary = match.group(1)
        stream = match.group(2)
        compressed = b"/FlateDecode" in dictionary
        yield stream, compressed


def _pdf_text_from_content_stream(stream: bytes) -> str:
    data = stream.decode("latin-1", errors="ignore")
    values: list[str] = []
    for array in re.findall(r"\[(.*?)\]\s*TJ", data, flags=re.S):
        values.extend(_decode_pdf_literal(value) for value in _pdf_literal_strings(array))
    for value in re.findall(r"(\((?:\\.|[^\\()])*\))\s*(?:'|\"|Tj)", data, flags=re.S):
        values.append(_decode_pdf_literal(value))
    return " ".join(item for item in values if item).strip()


def _pdf_literal_strings(data: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(data):
        if data[index] != "(":
            index += 1
            continue
        start = index
        index += 1
        depth = 1
        escaped = False
        while index < len(data) and depth:
            char = data[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        if depth == 0:
            values.append(data[start:index])
    return values


def _decode_pdf_literal(value: str) -> str:
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    out: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= len(value):
            break
        esc = value[index]
        mapping = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}
        if esc in mapping:
            out.append(mapping[esc])
            index += 1
        elif esc in "01234567":
            octal = esc
            index += 1
            for _ in range(2):
                if index < len(value) and value[index] in "01234567":
                    octal += value[index]
                    index += 1
            out.append(chr(int(octal, 8)))
        elif esc in {"\n", "\r"}:
            index += 1
            if esc == "\r" and index < len(value) and value[index] == "\n":
                index += 1
        else:
            out.append(esc)
            index += 1
    return "".join(out)


def _office_text_preview(path: Path, mime_type: str) -> tuple[str, dict]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) > 1000:
            raise AttachmentError("ATTACHMENT_LIMIT_EXCEEDED", "Office document contains too many package entries.")
        total_uncompressed = sum(item.file_size for item in archive.infolist())
        if total_uncompressed > 50 * 1024 * 1024:
            raise AttachmentError("ATTACHMENT_LIMIT_EXCEEDED", "Office document expands beyond the configured processing limit.")
        has_macros = any(name.lower().endswith("vbaproject.bin") for name in names)
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = _docx_text(archive)
            return text, {"processor": "builtin-ooxml-docx", "has_macros": has_macros}
        text = _xlsx_text(archive)
        return text, {"processor": "builtin-ooxml-xlsx", "has_macros": has_macros}


def _docx_text(archive: zipfile.ZipFile) -> str:
    try:
        raw = archive.read("word/document.xml")
    except KeyError as exc:
        raise AttachmentError("ATTACHMENT_INVALID", "DOCX package is missing word/document.xml.") from exc
    root = ET.fromstring(raw)
    lines: list[str] = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        parts = [node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        text = "".join(parts).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _xlsx_text(archive: zipfile.ZipFile) -> str:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
            value = "".join(node.text or "" for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
            shared.append(value)
    lines: list[str] = []
    for name in sorted(item for item in archive.namelist() if item.startswith("xl/worksheets/") and item.endswith(".xml"))[:20]:
        root = ET.fromstring(archive.read(name))
        values: list[str] = []
        for cell in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
            cell_type = cell.attrib.get("t")
            value_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
            inline_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
            if cell_type == "s" and value_node is not None and value_node.text:
                index = int(value_node.text)
                if 0 <= index < len(shared):
                    values.append(shared[index])
            elif inline_node is not None:
                values.append("".join(node.text or "" for node in inline_node.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
            elif value_node is not None and value_node.text:
                values.append(value_node.text)
        if values:
            lines.append(f"[{Path(name).stem}] " + "\t".join(values[:200]))
    return "\n".join(lines)


def processing_dependency_status() -> dict:
    def module_available(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    return {
        "image_metadata": {"available": module_available("PIL"), "provider": "Pillow"},
        "wav_metadata": {"available": True, "provider": "python-wave"},
        "video_metadata": {"available": bool(shutil.which("ffprobe")), "provider": "ffprobe"},
        "pdf_text": {"available": module_available("pypdf") or module_available("PyPDF2") or module_available("pdfplumber"), "providers": ["pypdf", "PyPDF2", "pdfplumber"]},
        "office_text": {"available": True, "providers": ["builtin-ooxml", "python-docx", "openpyxl"]},
        "asr": {"available": module_available("whisper"), "providers": ["whisper"]},
        "video_frames": {"available": bool(shutil.which("ffmpeg")), "providers": ["ffmpeg"]},
    }


class contextlib_suppress_oserror:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, OSError)
