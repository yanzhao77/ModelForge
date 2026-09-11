"""System status API routes."""
import json
import os
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Literal

from core.config import settings
from core.database import get_db
from core.security import get_current_user, get_runtime_admin
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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


class DownloadSourceRequest(BaseModel):
    source: Literal["official", "hf_mirror"]


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


def _persist_hf_endpoint(endpoint: str) -> None:
    data_dir = Path(settings.data_dir)
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parents[3] / data_dir
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
    payload["hf_endpoint"] = endpoint
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
    _persist_hf_endpoint(endpoint)
    return _download_source_payload()

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