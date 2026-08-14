"""Training API routes: start/status/stream/stop/register/templates/tasks."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from core.database import get_db
from core.security import get_current_user
from models.records import User
from services.training import TrainingService, get_log_tail

router = APIRouter(prefix="/train", tags=["train"])


class TrainStartRequest(BaseModel):
    dataset_id: Optional[int] = None
    dataset_path: Optional[str] = None
    base_model: str
    method: str = "lora"  # full | lora
    epochs: int = 3
    learning_rate: float = 2e-5
    batch_size: int = 2
    lora_r: Optional[int] = 8
    lora_alpha: Optional[int] = 32
    target_modules: Optional[list] = None
    output_dir: str = "./outputs"


def _task_or_404(db, task_id, user):
    row = TrainingService().get(db, task_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


@router.post("/start")
def train_start(
    req: TrainStartRequest, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        row = TrainingService().start(db, user.id, req.model_dump())
        return row.to_dict()
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks")
def train_tasks(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return [t.to_dict() for t in TrainingService().list(db, user.id)]


@router.get("/status/{task_id}")
def train_status(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _task_or_404(db, task_id, user)
    data = row.to_dict()
    data["log_tail"] = get_log_tail(row.log_path)
    return data


@router.get("/stream/{task_id}")
async def train_stream(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _task_or_404(db, task_id, user)
    log_path = row.log_path or ""
    state_path = ""
    if row.output_dir:
        import os
        state_path = os.path.join(row.output_dir, "state.json")

    async def event_generator():
        last_pos = 0
        last_state = None
        while True:
            # tail log
            if log_path:
                import os
                if os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos)
                        new_lines = f.read()
                        last_pos = f.tell()
                    if new_lines:
                        for line in new_lines.splitlines():
                            yield f"data: {json.dumps({'type': 'log', 'data': line}, ensure_ascii=False)}\n\n"
            # state
            state = {}
            if state_path:
                import os
                if os.path.exists(state_path):
                    try:
                        with open(state_path, "r", encoding="utf-8") as f:
                            state = json.load(f)
                    except Exception:
                        state = {}
            if state != last_state and state:
                last_state = state
                yield f"data: {json.dumps({'type': 'progress', 'data': state}, ensure_ascii=False)}\n\n"
            # terminal?
            cur = row.status
            if cur in ("done", "error", "stopped"):
                yield f"data: {json.dumps({'type': 'done', 'data': {'status': cur}}, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stop/{task_id}")
def train_stop(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _task_or_404(db, task_id, user)
    ok = TrainingService().stop(db, task_id, user.id)
    return {"ok": ok}


@router.post("/{task_id}/register-model")
def train_register_model(
    task_id: str, db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        model = TrainingService().register_model(db, task_id, user.id)
        return model
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/templates")
def train_templates(
    db: DBSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return TrainingService.templates()