"""System status API routes."""
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Literal

from core.api_contracts import correlation_id, problem
from core.config import settings
from core.database import get_db
from core.security import get_current_user, get_runtime_admin
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from services.redaction import redact_text
from sqlalchemy.orm import Session as DBSession

router = APIRouter(prefix="/system", tags=["system"])

_started_at = time.time()

OFFICIAL_HF_ENDPOINT = "https://huggingface.co"
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
DOWNLOAD_SOURCES = {
    "official": {"label": "Hugging Face", "endpoint": OFFICIAL_HF_ENDPOINT},
    "hf_mirror": {"label": "HF Mirror 中国大陆镜像", "endpoint": HF_MIRROR_ENDPOINT},
}
RUNTIME_SETTINGS_FILE = "runtime_settings.json"
DEFAULT_MODEL_DIR = "./models"
MODEL_STORAGE_MAX_LENGTH = 1024
MODEL_FILE_SUFFIXES = frozenset({".gguf", ".bin", ".safetensors", ".pt", ".pth"})
# A model directory can hold tens of thousands of files; the settings page only
# needs a rough occupancy signal, so the scan stops at this many entries.
MODEL_DIR_SCAN_LIMIT = 2000


class DownloadSourceRequest(BaseModel):
    source: Literal["official", "hf_mirror"]


class ModelStorageRequest(BaseModel):
    model_dir: str = Field(min_length=1, max_length=MODEL_STORAGE_MAX_LENGTH)


def _normalized_endpoint(endpoint: str | None) -> str:
    return (endpoint or OFFICIAL_HF_ENDPOINT).strip().rstrip("/") or OFFICIAL_HF_ENDPOINT


def _download_source_payload() -> dict:
    endpoint = _normalized_endpoint(settings.hf_endpoint)
    source = next(
        (key for key, item in DOWNLOAD_SOURCES.items() if item["endpoint"] == endpoint),
        "custom",
    )
    return {
        "source": source,
        "endpoint": endpoint,
        "available_sources": [
            {"source": key, "label": item["label"], "endpoint": item["endpoint"]}
            for key, item in DOWNLOAD_SOURCES.items()
        ],
    }


def _project_root() -> Path:
    """Directory the desktop backend treats as the ModelForge installation root."""
    return Path(__file__).resolve().parents[3]


def _resolve_model_dir(raw: str) -> Path:
    """Resolve a user-supplied storage path without trusting the process CWD."""
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = _project_root() / candidate
    return Path(os.path.normpath(str(candidate)))


def _probe_writable_directory(path: Path) -> None:
    """Fail fast when the directory accepts neither new files nor cleanup."""
    handle_fd, probe_name = tempfile.mkstemp(prefix=".modelforge-write-probe-", dir=str(path))
    os.close(handle_fd)
    Path(probe_name).unlink(missing_ok=True)


def _scan_summary(path: Path) -> dict:
    """Bounded top-level occupancy for the directory the user selected."""
    summary = {"entries": 0, "model_files": 0, "truncated": False}
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                if summary["entries"] >= MODEL_DIR_SCAN_LIMIT:
                    summary["truncated"] = True
                    break
                summary["entries"] += 1
                if entry.is_file() and Path(entry.name).suffix.lower() in MODEL_FILE_SUFFIXES:
                    summary["model_files"] += 1
    except OSError:
        pass
    return summary


def _disk_space(path: Path) -> tuple[int, int]:
    """Free/total bytes for the volume holding the directory (0 when unknown)."""
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return 0, 0
    return int(usage.free), int(usage.total)


def _model_storage_payload() -> dict:
    configured = (settings.model_dir or DEFAULT_MODEL_DIR).strip() or DEFAULT_MODEL_DIR
    resolved = _resolve_model_dir(configured)
    default_path = _resolve_model_dir(DEFAULT_MODEL_DIR)
    exists = resolved.is_dir()
    summary = _scan_summary(resolved) if exists else {"entries": 0, "model_files": 0, "truncated": False}
    free_bytes, total_bytes = _disk_space(resolved) if exists else (0, 0)
    return {
        "model_dir": configured,
        "resolved_path": str(resolved),
        "default_path": str(default_path),
        "is_default": resolved == default_path,
        "exists": exists,
        "writable": bool(exists and os.access(resolved, os.W_OK | os.X_OK)),
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "entries": summary["entries"],
        "model_files": summary["model_files"],
        "truncated": summary["truncated"],
    }


def _persist_runtime_settings(updates: dict[str, str]) -> None:
    """Merge desktop-managed process settings into the local runtime file."""
    data_dir = Path(settings.data_dir)
    if not data_dir.is_absolute():
        data_dir = _project_root() / data_dir
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = data_dir / RUNTIME_SETTINGS_FILE
    payload = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload.update(loaded)
        except Exception:
            payload = {}
    payload.update(updates)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@router.get("/download-source")
def get_download_source(user: object = Depends(get_current_user)):
    """Return the Hugging Face-compatible endpoint used for downloads/search."""
    return _download_source_payload()


@router.put("/download-source")
def update_download_source(req: DownloadSourceRequest, user: object = Depends(get_current_user)):
    """Switch between approved Hugging Face download sources for this process."""
    endpoint = DOWNLOAD_SOURCES[req.source]["endpoint"]
    settings.hf_endpoint = endpoint
    os.environ["HF_ENDPOINT"] = endpoint
    _persist_runtime_settings({"hf_endpoint": endpoint})
    return _download_source_payload()


@router.get("/model-storage")
def get_model_storage(user: object = Depends(get_current_user)):
    """Return the directory model downloads land in and model scans start from."""
    return _model_storage_payload()


@router.get("/hardening")
def system_hardening(user: object = Depends(get_runtime_admin)):
    """V1.9 hardening view: recovery, caches, runtime state, migration preflight."""
    del user
    from services.recovery_service import get_recovery_service

    report = get_recovery_service().hardening_report()
    return report


@router.post("/recovery")
def run_recovery(user: object = Depends(get_runtime_admin)):
    """Re-run the idempotent recovery pass (safe to call repeatedly)."""
    del user
    from services.recovery_service import get_recovery_service

    return get_recovery_service().startup_recovery()


@router.put("/model-storage")
def update_model_storage(req: ModelStorageRequest, user: object = Depends(get_current_user)):
    """Point downloads and model scanning at one explicit local directory.

    The two configuration fields are kept in step on purpose: downloads write to
    ``model_dir`` while scanning is rooted at ``model_path``, so pointing only
    one of them at the new directory would hide every freshly downloaded model
    from the model list.
    """
    corr = correlation_id()
    requested = req.model_dir.strip()
    if not requested:
        raise problem(400, "MODEL_DIR_INVALID", "Model directory must not be empty.", correlation=corr)
    target = _resolve_model_dir(requested)
    if target.parent == target:
        raise problem(400, "MODEL_DIR_INVALID", "A filesystem root cannot hold the model directory.", correlation=corr)
    if target.exists() and not target.is_dir():
        raise problem(400, "MODEL_DIR_NOT_A_DIRECTORY", "The model directory path is an existing file.", correlation=corr)
    try:
        target.mkdir(parents=True, exist_ok=True)
        _probe_writable_directory(target)
    except OSError as exc:
        raise problem(400, "MODEL_DIR_NOT_WRITABLE", "The model directory is not writable.", correlation=corr) from exc

    resolved = str(target)
    settings.model_dir = resolved
    settings.model_path = resolved
    os.environ["MODEL_DIR"] = resolved
    os.environ["MODEL_PATH"] = resolved
    try:
        _persist_runtime_settings({"model_dir": resolved, "model_path": resolved})
    except OSError as exc:
        raise problem(500, "MODEL_STORAGE_PERSIST_FAILED", "The model directory could not be persisted.", correlation=corr) from exc
    return _model_storage_payload()

@router.get("/status")
def system_status(
    db: DBSession = Depends(get_db), user: object = Depends(get_current_user),
):
    import psutil
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.getcwd())
    status = {
        "uptime_seconds": int(time.time() - _started_at),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory": {"total": mem.total, "used": mem.used, "percent": mem.percent},
        "disk": {"total": disk.total, "free": disk.free, "percent": disk.percent},
        "python": __import__("sys").version.split()[0],
    }
    # Optional GPU info
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            status["gpu"] = [line.strip() for line in out.stdout.strip().splitlines()]
    except Exception:
        pass
    return status

@router.get("/logs")
def system_logs(
    tail: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: object = Depends(get_runtime_admin),
):
    """Return a bounded, redacted log tail to runtime administrators only."""
    log_path = os.path.join(os.getcwd(), "logs", "modelforge.log")
    if not os.path.exists(log_path):
        return {"lines": [], "offset": offset, "next_offset": None}
    # Keep only the requested tail in memory rather than loading an unbounded
    # production log file. Offset counts lines backwards from the end.
    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
        buffered = deque(handle, maxlen=tail + offset)
    lines = list(buffered)
    if offset:
        lines = lines[:-offset] if offset < len(lines) else []
    selected = lines[-tail:]
    return {
        "lines": [redact_text(line.rstrip("\n")) for line in selected],
        "offset": offset,
        "next_offset": offset + len(selected) if len(selected) == tail else None,
    }
