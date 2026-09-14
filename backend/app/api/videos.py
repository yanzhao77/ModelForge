"""OpenAI-style ModelForge video generation endpoints."""
from __future__ import annotations

import time

from core.api_contracts import correlation_id
from core.database import get_db
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from services.local_api_service import LocalApiError, SCOPE_VIDEOS, authenticate_local_api_key, openai_error_payload
from services.video_generation_service import VideoServiceError, get_video_service
from sqlalchemy.orm import Session as DBSession

router = APIRouter(tags=["videos"])

_MAX_PROMPT_CHARS = 4000


class VideoCreateRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1, max_length=_MAX_PROMPT_CHARS)
    seconds: int = Field(default=6, ge=1, le=30)
    fps: int = Field(default=8, ge=1, le=60)
    size: str = Field(default="720x480", pattern=r"^\d{2,5}x\d{2,5}$")
    num_inference_steps: int | None = Field(default=None, ge=1, le=100)
    seed: int | None = Field(default=None, ge=-(2**63), le=2**63 - 1)


def _headers(correlation: str) -> dict[str, str]:
    return {"X-Request-ID": correlation, "X-Correlation-ID": correlation}


def _openai_error(code: str, message: str, correlation: str) -> dict:
    return {
        "error": {
            "message": message,
            "type": "server_error",
            "code": code,
            "param": None,
        },
        "correlation_id": correlation,
    }


def _auth(db: DBSession, authorization: str | None, correlation: str):
    try:
        return authenticate_local_api_key(db, authorization, required_scope=SCOPE_VIDEOS)
    except LocalApiError as exc:
        return JSONResponse(
            openai_error_payload(exc.code, exc.message, correlation, param=exc.param),
            status_code=exc.status_code,
            headers=_headers(correlation),
        )


def _error_response(exc: VideoServiceError, correlation: str) -> JSONResponse:
    return JSONResponse(
        _openai_error(exc.code, str(exc), correlation),
        status_code=exc.status_code,
        headers=_headers(correlation),
    )


@router.post("/v1/videos")
async def create_video(
    req: VideoCreateRequest,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    del request
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, correlation)
    if isinstance(principal, JSONResponse):
        return principal
    if idempotency_key is not None and len(idempotency_key) > 128:
        return JSONResponse(
            _openai_error("REQUEST_INVALID", "Idempotency-Key is too long.", correlation),
            status_code=422,
            headers=_headers(correlation),
        )
    try:
        job = await get_video_service().submit(
            db,
            user_id=principal.user_id,
            model_id=req.model,
            prompt=req.prompt,
            seconds=req.seconds,
            fps=req.fps,
            size=req.size,
            num_inference_steps=req.num_inference_steps,
            seed=req.seed,
            idempotency_key=idempotency_key,
            correlation_id=correlation,
        )
    except VideoServiceError as exc:
        return _error_response(exc, correlation)
    return JSONResponse(job.to_public_dict(), status_code=202, headers=_headers(correlation))


@router.get("/v1/videos/{video_id}")
def get_video(
    video_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, correlation)
    if isinstance(principal, JSONResponse):
        return principal
    job = get_video_service().get_for_user(db, video_id, principal.user_id)
    if job is None:
        return JSONResponse(_openai_error("VIDEO_JOB_NOT_FOUND", "Video job is unavailable.", correlation), status_code=404, headers=_headers(correlation))
    return JSONResponse(job.to_public_dict(), headers=_headers(correlation))


@router.post("/v1/videos/{video_id}/cancel")
def cancel_video(
    video_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, correlation)
    if isinstance(principal, JSONResponse):
        return principal
    job = get_video_service().get_for_user(db, video_id, principal.user_id)
    if job is None:
        return JSONResponse(_openai_error("VIDEO_JOB_NOT_FOUND", "Video job is unavailable.", correlation), status_code=404, headers=_headers(correlation))
    try:
        job = get_video_service().cancel(db, job)
    except VideoServiceError as exc:
        return _error_response(exc, correlation)
    return JSONResponse(job.to_public_dict(), headers=_headers(correlation))


@router.delete("/v1/videos/{video_id}")
def delete_video_alias(
    video_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    return cancel_video(video_id, authorization=authorization, request_id=request_id, db=db)


@router.get("/v1/videos/{video_id}/content")
def get_video_content(
    video_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: DBSession = Depends(get_db),
):
    correlation = (request_id or correlation_id())[:64]
    principal = _auth(db, authorization, correlation)
    if isinstance(principal, JSONResponse):
        return principal
    job = get_video_service().get_for_user(db, video_id, principal.user_id)
    if job is None:
        return JSONResponse(_openai_error("VIDEO_JOB_NOT_FOUND", "Video job is unavailable.", correlation), status_code=404, headers=_headers(correlation))
    try:
        path = get_video_service().content_path(job)
    except VideoServiceError as exc:
        return _error_response(exc, correlation)
    filename = f"{video_id}.mp4"
    headers = _headers(correlation)
    headers.update({
        "Cache-Control": "private",
        "ETag": f'"{job.output_sha256 or int(time.time())}"',
    })
    return FileResponse(path, media_type="video/mp4", filename=filename, headers=headers)
