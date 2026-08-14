"""System status API routes."""
import os
import subprocess
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from core.database import get_db
from core.security import get_current_user

router = APIRouter(prefix="/system", tags=["system"])

_started_at = time.time()

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
    tail: int = 100, db: DBSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    log_path = os.path.join(os.getcwd(), "logs", "modelforge.log")
    if not os.path.exists(log_path):
        return {"lines": []}
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return {"lines": lines[-max(1, min(tail, 5000)):]}