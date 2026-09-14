"""Structured chat turn lifecycle service."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import uuid

from models.records import (
    ChatAttemptRecord,
    ChatEventRecord,
    ChatTurnRecord,
    Message,
    MessageAttachment,
    ModelRecord,
    User,
)
from schemas.multimodal_chat import (
    AudioPart,
    ChatTurnCreate,
    FilePart,
    ImagePart,
    PageSelection,
    TextPart,
    TextSelection,
    TimeSelection,
    VideoPart,
    part_dicts,
)
from services.artifact_service import ArtifactService
from services.attachment_service import (
    AUDIO_MIME_TYPES,
    IMAGE_MIME_TYPES,
    PDF_MIME_TYPES,
    TEXT_MIME_TYPES,
    VIDEO_MIME_TYPES,
    AttachmentError,
    AttachmentService,
    processing_dependency_status,
)
from services.chat_service import complete_chat
from services.memory_store import MemoryStore
from services.session_service import SessionService
from sqlalchemy.orm import Session as DBSession


class ChatTurnError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.details = details or {}


class ChatTurnService:
    ACTIVE_STATUSES = {"QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"}
    TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "PARTIAL", "CANCELLED", "TIMED_OUT", "INTERRUPTED"}

    def preflight(self, db: DBSession, user: User, req: ChatTurnCreate) -> dict:
        if req.mode != "chat":
            raise ChatTurnError("SANDBOX_UNAVAILABLE", "Agent mode requires the sandbox milestone and is not enabled in this build.")
        if req.session_id is not None and SessionService.get_session_by_id(db, req.session_id, user.id) is None:
            raise ChatTurnError("SESSION_NOT_FOUND", "Session was not found.")
        attachment_service = AttachmentService()
        inputs: list[dict] = []
        blockers: list[dict] = []
        estimate = {"text_characters": 0, "estimated_prompt_characters": 0, "attachments": 0, "selected_parts": 0}
        excluded_attachment_ids = set(req.context.excluded_attachment_ids)
        for part in req.message.parts:
            if isinstance(part, TextPart):
                estimate["text_characters"] += len(part.text)
                estimate["estimated_prompt_characters"] += len(part.text)
                inputs.append({"type": "text", "characters": len(part.text)})
            elif isinstance(part, FilePart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                if rec.id in excluded_attachment_ids:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_EXCLUDED", "message": "This attachment is explicitly excluded from the turn context."})
                item = {"type": "file", "attachment": rec.to_dict(), "processing": part.processing, "selection": part.selection.model_dump() if part.selection else None}
                preview = attachment_service.preview(db, rec)
                text = preview.get("text")
                estimate["attachments"] += 1
                if part.selection is not None:
                    estimate["selected_parts"] += 1
                if rec.mime_type not in TEXT_MIME_TYPES and not (isinstance(text, str) and text.strip()):
                    blockers.append({"attachment_id": rec.id, "code": "PROCESSOR_UNAVAILABLE", "message": "Only text-like file extraction is enabled in this milestone."})
                elif isinstance(part.selection, TextSelection):
                    if isinstance(text, str) and part.selection.end_line > max(1, len(text.splitlines())):
                        blockers.append({"attachment_id": rec.id, "code": "SELECTION_OUT_OF_RANGE", "message": "Selected line range exceeds the extracted text preview."})
                    if isinstance(text, str):
                        lines = text.splitlines()
                        estimate["estimated_prompt_characters"] += len("\n".join(lines[part.selection.start_line - 1:part.selection.end_line]))
                elif isinstance(part.selection, PageSelection):
                    pages_detected = _attachment_pages_detected(preview)
                    if rec.mime_type not in PDF_MIME_TYPES:
                        blockers.append({"attachment_id": rec.id, "code": "SELECTION_UNSUPPORTED", "message": "Page selection is only enabled for PDF attachments in this milestone."})
                    elif pages_detected is None:
                        blockers.append({"attachment_id": rec.id, "code": "PROCESSOR_UNAVAILABLE", "message": "PDF page count is not available for this attachment."})
                    elif max(part.selection.pages) > pages_detected:
                        blockers.append({"attachment_id": rec.id, "code": "SELECTION_OUT_OF_RANGE", "message": "Selected PDF pages exceed the detected page count."})
                    if isinstance(text, str):
                        estimate["estimated_prompt_characters"] += len(_select_pdf_pages(text, part.selection.pages))
                elif isinstance(text, str):
                    estimate["estimated_prompt_characters"] += len(text)
                inputs.append(item)
            elif isinstance(part, ImagePart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                if rec.id in excluded_attachment_ids:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_EXCLUDED", "message": "This attachment is explicitly excluded from the turn context."})
                item = {"type": "image", "attachment": rec.to_dict(), "detail": part.detail}
                estimate["attachments"] += 1
                if part.selection is not None:
                    estimate["selected_parts"] += 1
                if rec.mime_type not in IMAGE_MIME_TYPES:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_TYPE_UNSUPPORTED", "message": "Image part must reference PNG, JPEG, or WebP."})
                if req.target.provider_id is None:
                    blockers.append({"attachment_id": rec.id, "code": "MODEL_INPUT_UNSUPPORTED", "message": "Native image input requires a remote provider target in this milestone."})
                inputs.append(item)
            elif isinstance(part, AudioPart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                if rec.id in excluded_attachment_ids:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_EXCLUDED", "message": "This attachment is explicitly excluded from the turn context."})
                item = {"type": "audio", "attachment": rec.to_dict(), "processing": part.processing, "selection": part.selection.model_dump() if part.selection else None}
                estimate["attachments"] += 1
                if part.selection is not None:
                    estimate["selected_parts"] += 1
                if rec.mime_type not in AUDIO_MIME_TYPES:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_TYPE_UNSUPPORTED", "message": "Audio part must reference a supported audio attachment."})
                if isinstance(part.selection, TimeSelection):
                    duration_ms = _attachment_duration_ms(attachment_service.preview(db, rec))
                    if duration_ms is not None and part.selection.end_ms > duration_ms:
                        blockers.append({"attachment_id": rec.id, "code": "SELECTION_OUT_OF_RANGE", "message": "Selected audio time range exceeds the attachment duration."})
                blockers.append({"attachment_id": rec.id, "code": "PROCESSOR_UNAVAILABLE", "message": "ASR and native audio input adapters are not enabled in this build."})
                inputs.append(item)
            elif isinstance(part, VideoPart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                if rec.id in excluded_attachment_ids:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_EXCLUDED", "message": "This attachment is explicitly excluded from the turn context."})
                item = {"type": "video", "attachment": rec.to_dict(), "processing": part.processing, "selection": part.selection.model_dump() if part.selection else None}
                estimate["attachments"] += 1
                if part.selection is not None:
                    estimate["selected_parts"] += 1
                if rec.mime_type not in VIDEO_MIME_TYPES:
                    blockers.append({"attachment_id": rec.id, "code": "ATTACHMENT_TYPE_UNSUPPORTED", "message": "Video part must reference a supported video attachment."})
                if isinstance(part.selection, TimeSelection):
                    duration_ms = _attachment_duration_ms(attachment_service.preview(db, rec))
                    if duration_ms is not None and part.selection.end_ms > duration_ms:
                        blockers.append({"attachment_id": rec.id, "code": "SELECTION_OUT_OF_RANGE", "message": "Selected video time range exceeds the attachment duration."})
                blockers.append({"attachment_id": rec.id, "code": "PROCESSOR_UNAVAILABLE", "message": "Video frame extraction, ASR, and native video input adapters are not enabled in this build."})
                inputs.append(item)
        capability = self.capabilities(db, user, req.target.model_id, req.target.provider_id)
        return {
            "ok": not blockers,
            "mode": req.mode,
            "target": req.target.model_dump(exclude_none=True),
            "inputs": inputs,
            "blockers": blockers,
            "capability_snapshot": capability,
            "context_estimate": estimate,
            "requested_outputs": [item.model_dump(exclude_none=True) for item in req.requested_outputs],
        }

    def capabilities(self, db: DBSession, user: User, model_id: int | None = None, provider_id: int | None = None) -> dict:
        if model_id is not None:
            rec = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
            if rec is None or (rec.user_id is not None and rec.user_id != user.id):
                raise ChatTurnError("MODEL_NOT_FOUND", "Model was not found.")
            caps = rec.capability_list()
            return {
                "source": "model_registry",
                "model_id": rec.id,
                "capabilities": caps,
                "input": {
                    "text": "CHAT" in caps or "INFERENCE" in caps,
                    "file_text_conversion": True,
                    "image_native": False,
                    "audio_native": False,
                    "video_native": False,
                },
                "output": {"text": True, "artifact_text": True, "image": "IMAGE" in caps, "audio": "AUDIO" in caps, "video": "VIDEO" in caps},
                "dependencies": processing_dependency_status(),
                "evidence": "declared_registry_capabilities",
            }
        if provider_id is not None:
            return {
                "source": "remote_provider_config",
                "provider_id": provider_id,
                "capabilities": ["CHAT"],
                "input": {"text": True, "file_text_conversion": True, "image_native": True, "audio_native": False, "video_native": False},
                "output": {"text": True, "artifact_text": True},
                "dependencies": processing_dependency_status(),
                "evidence": "provider_config_unverified_multimodal_payload",
            }
        return {
            "source": "legacy_runtime",
            "capabilities": ["CHAT"],
            "input": {"text": True, "file_text_conversion": True, "image_native": False, "audio_native": False, "video_native": False},
            "output": {"text": True, "artifact_text": True},
            "dependencies": processing_dependency_status(),
            "evidence": "legacy_runtime_text_only",
        }

    def create(self, db: DBSession, user: User, req: ChatTurnCreate) -> dict:
        preflight = self.preflight(db, user, req)
        if not preflight["ok"]:
            raise ChatTurnError("MODEL_INPUT_UNSUPPORTED", "The draft cannot be sent with the selected target.", details={"blockers": preflight["blockers"]})
        request_hash = _request_hash(req)
        existing = db.query(ChatTurnRecord).filter(ChatTurnRecord.user_id == user.id, ChatTurnRecord.idempotency_key == req.idempotency_key).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ChatTurnError("IDEMPOTENCY_CONFLICT", "Idempotency key was already used with a different request.")
            snapshot = self.snapshot(db, user, existing.id)
            snapshot["execution"] = {"created": False, "scheduled": False}
            return snapshot

        session = None
        if req.session_id is not None:
            session = SessionService.get_session_by_id(db, req.session_id, user.id)
            if session is None:
                raise ChatTurnError("SESSION_NOT_FOUND", "Session was not found.")

        turn_id = f"turn_{uuid.uuid4().hex}"
        attempt_id = f"attempt_{uuid.uuid4().hex}"
        now = dt.datetime.utcnow()
        manifest = self._context_manifest(db, user, req)
        turn = ChatTurnRecord(
            id=turn_id,
            user_id=user.id,
            session_id=req.session_id,
            idempotency_key=req.idempotency_key,
            request_hash=request_hash,
            status="RUNNING",
            mode=req.mode,
            context_manifest_json=json.dumps(manifest, ensure_ascii=False),
            capability_snapshot_json=json.dumps(preflight["capability_snapshot"], ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        db.add(turn)
        db.flush()
        user_message = None
        if session is not None:
            user_message = SessionService.add_message(
                db,
                session.id,
                "user",
                req.message.content,
                token_count=len(req.message.content),
                parts=part_dicts(req.message.parts),
                schema_version=req.schema_version,
                status="completed",
                turn_id=turn_id,
            )
            turn.user_message_id = user_message.id
            for attachment_id in _attachment_ids(req):
                SessionService.link_message_attachment(db, user_message.id, attachment_id)
        attempt = ChatAttemptRecord(id=attempt_id, turn_id=turn_id, attempt_no=1, status="RUNNING", created_at=now)
        db.add(attempt)
        self._event(db, turn_id, None, "turn.created", {"status": "RUNNING"}, "turn.created")
        if user_message is not None:
            self._event(db, turn_id, None, "message.created", {"message": user_message.to_dict()}, "message.user.created")
        db.commit()
        snapshot = self.snapshot(db, user, turn_id)
        snapshot["execution"] = {"created": True, "scheduled": False}
        return snapshot

    async def create_and_run(self, db: DBSession, runtime, user: User, req: ChatTurnCreate, *, provider: dict | None = None) -> dict:
        snapshot = self.create(db, user, req)
        turn_id = snapshot["turn"]["id"]
        attempt = snapshot["attempts"][-1]
        await self.run_attempt(db, runtime, user.id, turn_id, req, attempt["id"], attempt["attempt_no"], provider=provider)
        return self.snapshot(db, user, turn_id)

    async def run_attempt(
        self,
        db: DBSession,
        runtime,
        user_id: int,
        turn_id: str,
        req: ChatTurnCreate,
        attempt_id: str,
        attempt_no: int,
        *,
        provider: dict | None = None,
    ) -> None:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise ChatTurnError("USER_NOT_FOUND", "User was not found.")
        turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id, ChatTurnRecord.user_id == user_id).first()
        attempt = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.id == attempt_id, ChatAttemptRecord.turn_id == turn_id).first()
        if turn is None or attempt is None:
            raise ChatTurnError("CHAT_TURN_NOT_FOUND", "Chat turn was not found.")
        if turn.status == "CANCEL_REQUESTED":
            self._mark_cancelled(db, turn, attempt, attempt_no, before_execution=True)
            return

        history: list[dict] = []
        if req.session_id is not None:
            session = SessionService.get_session_by_id(db, req.session_id, user.id)
            if session is None:
                raise ChatTurnError("SESSION_NOT_FOUND", "Session was not found.")
            history = self._history_messages(db, req, exclude_turn_id=turn_id)

        memory = self._memory_messages(db, user, req)
        if req.target.provider_id is not None:
            full_messages = memory + history + [{"role": "user", "content": self._model_content_parts(db, user, req)}]
        else:
            full_messages = memory + history + [{"role": "user", "content": self._model_input(db, user, req)}]
        try:
            result = await complete_chat(
                db,
                runtime,
                req.target.model or "default",
                full_messages,
                user=user,
                provider=provider,
                model_id=req.target.model_id,
                runtime_id=req.target.runtime,
            )
            turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id).one()
            attempt = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.id == attempt_id).one()
            if turn.status == "CANCEL_REQUESTED":
                self._mark_cancelled(db, turn, attempt, attempt_no, before_execution=False)
                return
            response = result.get("content", "")
            assistant_message = None
            if session is not None:
                assistant_message = SessionService.add_message(
                    db,
                    session.id,
                    "assistant",
                    response,
                    token_count=len(response),
                    parts=[{"type": "text", "text": response}],
                    schema_version=1,
                    status="completed",
                    turn_id=turn_id,
                )
                if SessionService.get_session_message_count(db, session.id) == 2:
                    SessionService.auto_generate_title(db, session.id)
            artifacts = []
            if any(item.type == "artifact" for item in req.requested_outputs) and response:
                artifact, version = ArtifactService().create_text_artifact(
                    db,
                    user_id=user.id,
                    session_id=req.session_id,
                    message_id=assistant_message.id if assistant_message else None,
                    name="chat-response",
                    content=response,
                    producer_ref=turn_id,
                )
                artifacts.append({"artifact": artifact.to_dict(), "version": version.to_dict()})
            turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id).one()
            attempt = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.id == attempt_id).one()
            turn.status = "SUCCEEDED"
            turn.finished_at = dt.datetime.utcnow()
            attempt.status = "SUCCEEDED"
            attempt.output_message_id = assistant_message.id if assistant_message else None
            attempt.usage_json = json.dumps(result.get("usage") or result.get("token_usage") or {}, ensure_ascii=False)
            attempt.finished_at = dt.datetime.utcnow()
            self._event(db, turn_id, attempt_id, "message.completed", {"message_id": attempt.output_message_id, "content": response}, "message.assistant.completed")
            for item in artifacts:
                self._event(db, turn_id, attempt_id, "artifact.created", item, f"artifact.{item['artifact']['id']}.created")
            self._event(db, turn_id, attempt_id, "turn.finished", {"status": "SUCCEEDED"}, "turn.finished")
            db.commit()
        except Exception as exc:
            turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id).one()
            attempt = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.id == attempt_id).one()
            turn.status = "FAILED"
            turn.finished_at = dt.datetime.utcnow()
            attempt.status = "FAILED"
            attempt.error_code = exc.__class__.__name__
            attempt.finished_at = dt.datetime.utcnow()
            self._event(db, turn_id, attempt_id, "error", {"code": attempt.error_code, "message": "Chat turn failed."}, "turn.error")
            db.commit()
            raise

    def snapshot(self, db: DBSession, user: User, turn_id: str) -> dict:
        turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id, ChatTurnRecord.user_id == user.id).first()
        if turn is None:
            raise ChatTurnError("CHAT_TURN_NOT_FOUND", "Chat turn was not found.")
        attempts = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.turn_id == turn_id).order_by(ChatAttemptRecord.attempt_no.asc()).all()
        messages = db.query(Message).filter(Message.turn_id == turn_id).order_by(Message.timestamp.asc(), Message.id.asc()).all()
        return {"turn": turn.to_dict(), "attempts": [item.to_dict() for item in attempts], "messages": [item.to_dict() for item in messages]}

    def events(self, db: DBSession, user: User, turn_id: str, after_sequence: int = 0) -> list[dict]:
        if db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id, ChatTurnRecord.user_id == user.id).first() is None:
            raise ChatTurnError("CHAT_TURN_NOT_FOUND", "Chat turn was not found.")
        rows = (
            db.query(ChatEventRecord)
            .filter(ChatEventRecord.turn_id == turn_id, ChatEventRecord.sequence > after_sequence)
            .order_by(ChatEventRecord.sequence.asc())
            .all()
        )
        return [row.to_dict() for row in rows]

    def cancel(self, db: DBSession, user: User, turn_id: str) -> dict:
        turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id, ChatTurnRecord.user_id == user.id).first()
        if turn is None:
            raise ChatTurnError("CHAT_TURN_NOT_FOUND", "Chat turn was not found.")
        if turn.status in self.TERMINAL_STATUSES:
            snapshot = self.snapshot(db, user, turn_id)
            snapshot["cancellation"] = {"accepted": False, "reason": "TURN_ALREADY_TERMINAL", "status": turn.status}
            return snapshot
        turn.status = "CANCEL_REQUESTED"
        turn.updated_at = dt.datetime.utcnow()
        self._event(db, turn_id, None, "turn.status_changed", {"status": "CANCEL_REQUESTED"}, "turn.cancel_requested")
        db.commit()
        snapshot = self.snapshot(db, user, turn_id)
        snapshot["cancellation"] = {"accepted": True, "status": "CANCEL_REQUESTED"}
        return snapshot

    async def retry_and_run(self, db: DBSession, runtime, user: User, turn_id: str, req: ChatTurnCreate, *, provider: dict | None = None) -> dict:
        turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id, ChatTurnRecord.user_id == user.id).first()
        if turn is None:
            raise ChatTurnError("CHAT_TURN_NOT_FOUND", "Chat turn was not found.")
        if turn.status in self.ACTIVE_STATUSES:
            raise ChatTurnError("CHAT_TURN_ACTIVE", "Chat turn is still active and cannot be retried yet.")
        if _request_hash(req) != turn.request_hash:
            raise ChatTurnError("IDEMPOTENCY_CONFLICT", "Retry request does not match the original chat turn payload.")
        preflight = self.preflight(db, user, req)
        if not preflight["ok"]:
            raise ChatTurnError("MODEL_INPUT_UNSUPPORTED", "The retry payload cannot be sent with the selected target.", details={"blockers": preflight["blockers"]})

        attempts = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.turn_id == turn_id).order_by(ChatAttemptRecord.attempt_no.desc()).all()
        next_attempt_no = (attempts[0].attempt_no if attempts else 0) + 1
        attempt_id = f"attempt_{uuid.uuid4().hex}"
        now = dt.datetime.utcnow()
        turn.status = "RUNNING"
        turn.finished_at = None
        turn.updated_at = now
        turn.capability_snapshot_json = json.dumps(preflight["capability_snapshot"], ensure_ascii=False)
        attempt = ChatAttemptRecord(id=attempt_id, turn_id=turn_id, attempt_no=next_attempt_no, status="RUNNING", created_at=now)
        db.add(attempt)
        self._event(db, turn_id, attempt_id, "turn.status_changed", {"status": "RUNNING", "attempt_no": next_attempt_no}, f"attempt.{next_attempt_no}.started")
        db.commit()

        history: list[dict] = []
        if req.session_id is not None:
            session = SessionService.get_session_by_id(db, req.session_id, user.id)
            if session is None:
                raise ChatTurnError("SESSION_NOT_FOUND", "Session was not found.")
            history = self._history_messages(db, req, exclude_turn_id=turn_id)
        memory = self._memory_messages(db, user, req)
        if req.target.provider_id is not None:
            full_messages = memory + history + [{"role": "user", "content": self._model_content_parts(db, user, req)}]
        else:
            full_messages = memory + history + [{"role": "user", "content": self._model_input(db, user, req)}]
        try:
            result = await complete_chat(
                db,
                runtime,
                req.target.model or "default",
                full_messages,
                user=user,
                provider=provider,
                model_id=req.target.model_id,
                runtime_id=req.target.runtime,
            )
            response = result.get("content", "")
            assistant_message = None
            if req.session_id is not None:
                assistant_message = SessionService.add_message(
                    db,
                    req.session_id,
                    "assistant",
                    response,
                    token_count=len(response),
                    parts=[{"type": "text", "text": response}],
                    schema_version=1,
                    status="completed",
                    turn_id=turn_id,
                )
            artifacts = []
            if any(item.type == "artifact" for item in req.requested_outputs) and response:
                artifact, version = ArtifactService().create_text_artifact(
                    db,
                    user_id=user.id,
                    session_id=req.session_id,
                    message_id=assistant_message.id if assistant_message else None,
                    name="chat-response",
                    content=response,
                    producer_ref=turn_id,
                )
                artifacts.append({"artifact": artifact.to_dict(), "version": version.to_dict()})
            turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id).one()
            attempt = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.id == attempt_id).one()
            turn.status = "SUCCEEDED"
            turn.finished_at = dt.datetime.utcnow()
            attempt.status = "SUCCEEDED"
            attempt.output_message_id = assistant_message.id if assistant_message else None
            attempt.usage_json = json.dumps(result.get("usage") or result.get("token_usage") or {}, ensure_ascii=False)
            attempt.finished_at = dt.datetime.utcnow()
            self._event(db, turn_id, attempt_id, "message.completed", {"message_id": attempt.output_message_id, "content": response}, f"attempt.{next_attempt_no}.message.assistant.completed")
            for item in artifacts:
                self._event(db, turn_id, attempt_id, "artifact.created", item, f"attempt.{next_attempt_no}.artifact.{item['artifact']['id']}.created")
            self._event(db, turn_id, attempt_id, "turn.finished", {"status": "SUCCEEDED", "attempt_no": next_attempt_no}, f"attempt.{next_attempt_no}.finished")
            db.commit()
        except Exception as exc:
            turn = db.query(ChatTurnRecord).filter(ChatTurnRecord.id == turn_id).one()
            attempt = db.query(ChatAttemptRecord).filter(ChatAttemptRecord.id == attempt_id).one()
            turn.status = "FAILED"
            turn.finished_at = dt.datetime.utcnow()
            attempt.status = "FAILED"
            attempt.error_code = exc.__class__.__name__
            attempt.finished_at = dt.datetime.utcnow()
            self._event(db, turn_id, attempt_id, "error", {"code": attempt.error_code, "message": "Chat turn retry failed."}, f"attempt.{next_attempt_no}.error")
            db.commit()
            raise
        return self.snapshot(db, user, turn_id)

    def reconcile_orphaned_turns(self, db: DBSession) -> dict:
        """Settle structured chat turns left active by a process restart.

        Structured chat execution currently runs in FastAPI's in-process
        background tasks. After a service restart there is no worker that can
        finish those rows, so recovery must make the interrupted state explicit
        and unblock attachment cleanup/retry flows.
        """
        rows = (
            db.query(ChatTurnRecord)
            .filter(ChatTurnRecord.status.in_(self.ACTIVE_STATUSES))
            .order_by(ChatTurnRecord.created_at.asc(), ChatTurnRecord.id.asc())
            .all()
        )
        now = dt.datetime.utcnow()
        summary = {"settled": 0, "cancelled": 0, "interrupted": 0, "attempts": 0}
        for turn in rows:
            target_status = "CANCELLED" if turn.status == "CANCEL_REQUESTED" else "INTERRUPTED"
            error_code = "CHAT_TURN_CANCELLED" if target_status == "CANCELLED" else "CHAT_TURN_STARTUP_RECONCILIATION"
            attempts = (
                db.query(ChatAttemptRecord)
                .filter(ChatAttemptRecord.turn_id == turn.id, ChatAttemptRecord.status.in_(self.ACTIVE_STATUSES))
                .order_by(ChatAttemptRecord.attempt_no.asc())
                .all()
            )
            turn.status = target_status
            turn.finished_at = now
            turn.updated_at = now
            for attempt in attempts:
                attempt.status = target_status
                attempt.error_code = error_code
                attempt.finished_at = now
            self._event(
                db,
                turn.id,
                attempts[-1].id if attempts else None,
                "turn.finished",
                {"status": target_status, "reason": "startup_reconciliation"},
                "turn.startup_reconciliation",
            )
            summary["settled"] += 1
            summary["attempts"] += len(attempts)
            if target_status == "CANCELLED":
                summary["cancelled"] += 1
            else:
                summary["interrupted"] += 1
        db.commit()
        return summary

    def _mark_cancelled(self, db: DBSession, turn: ChatTurnRecord, attempt: ChatAttemptRecord, attempt_no: int, *, before_execution: bool) -> None:
        now = dt.datetime.utcnow()
        turn.status = "CANCELLED"
        turn.finished_at = now
        turn.updated_at = now
        attempt.status = "CANCELLED"
        attempt.error_code = "CHAT_TURN_CANCELLED"
        attempt.finished_at = now
        reason = "cancelled_before_execution" if before_execution else "cancelled_after_model_returned"
        self._event(
            db,
            turn.id,
            attempt.id,
            "turn.finished",
            {"status": "CANCELLED", "attempt_no": attempt_no, "reason": reason},
            f"attempt.{attempt_no}.cancelled",
        )
        db.commit()

    def _context_manifest(self, db: DBSession, user: User, req: ChatTurnCreate) -> dict:
        entries = []
        for part in req.message.parts:
            if isinstance(part, TextPart):
                entries.append({"type": "text", "characters": len(part.text)})
            elif isinstance(part, (FilePart, ImagePart, AudioPart, VideoPart)):
                rec = AttachmentService().require(db, user.id, part.attachment_id)
                entries.append({"type": part.type, "attachment_id": rec.id, "sha256": rec.sha256, "mime_type": rec.mime_type, "selection": getattr(part, "selection", None).model_dump() if getattr(part, "selection", None) else None})
        return {
            "schema_version": 1,
            "inputs": entries,
            "excluded_message_ids": list(req.context.excluded_message_ids),
            "excluded_attachment_ids": list(req.context.excluded_attachment_ids),
            "use_memory": req.context.use_memory,
        }

    def _history_messages(self, db: DBSession, req: ChatTurnCreate, *, exclude_turn_id: str | None = None) -> list[dict]:
        if req.session_id is None:
            return []
        excluded_message_ids = set(req.context.excluded_message_ids)
        excluded_attachment_ids = set(req.context.excluded_attachment_ids)
        rows = SessionService.get_recent_session_messages(db, req.session_id, limit=50)
        if excluded_attachment_ids:
            linked_rows = (
                db.query(MessageAttachment.message_id)
                .filter(MessageAttachment.attachment_id.in_(excluded_attachment_ids))
                .all()
            )
            linked_message_ids = {row[0] for row in linked_rows}
            excluded_message_ids.update(linked_message_ids)
            linked_turns = (
                db.query(Message.turn_id)
                .filter(Message.id.in_(linked_message_ids), Message.turn_id.isnot(None))
                .all()
            ) if linked_message_ids else []
            excluded_turn_ids = {row[0] for row in linked_turns if row[0]}
        else:
            excluded_turn_ids = set()
        messages = []
        for msg in rows:
            if exclude_turn_id is not None and msg.turn_id == exclude_turn_id:
                continue
            if msg.turn_id in excluded_turn_ids:
                continue
            if msg.id in excluded_message_ids:
                continue
            messages.append(msg.to_dict())
        return messages

    def _memory_messages(self, db: DBSession, user: User, req: ChatTurnCreate) -> list[dict]:
        if not req.context.use_memory:
            return []
        try:
            memories = MemoryStore.get_relevant_memories_for_query(db, user.id, req.message.content, limit=3)
            memory_context = MemoryStore.format_memories_for_context(memories)
            MemoryStore.extract_memories_from_message(db, user.id, req.message.content, req.session_id)
        except Exception:
            return []
        if not memory_context:
            return []
        return [{"role": "system", "content": memory_context}]

    def _model_input(self, db: DBSession, user: User, req: ChatTurnCreate) -> str:
        attachment_service = AttachmentService()
        chunks: list[str] = []
        for part in req.message.parts:
            if isinstance(part, TextPart):
                chunks.append(part.text)
            elif isinstance(part, FilePart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                preview = attachment_service.preview(db, rec)
                text = preview.get("text")
                if not isinstance(text, str):
                    raise ChatTurnError("PROCESSOR_UNAVAILABLE", "File text extraction is not available for this attachment.")
                if isinstance(part.selection, TextSelection):
                    lines = text.splitlines()
                    text = "\n".join(lines[part.selection.start_line - 1:part.selection.end_line])
                elif isinstance(part.selection, PageSelection):
                    text = _select_pdf_pages(text, part.selection.pages)
                chunks.append(f"\n[Attachment {rec.display_name} extracted text]\n{text}")
            elif isinstance(part, ImagePart):
                raise ChatTurnError("MODEL_INPUT_UNSUPPORTED", "Native image input is not enabled for chat turns yet.")
            elif isinstance(part, (AudioPart, VideoPart)):
                raise ChatTurnError("PROCESSOR_UNAVAILABLE", "Media processing is not enabled for chat turns yet.")
        return "\n".join(chunk for chunk in chunks if chunk)

    def _model_content_parts(self, db: DBSession, user: User, req: ChatTurnCreate) -> list[dict]:
        attachment_service = AttachmentService()
        content: list[dict] = []
        for part in req.message.parts:
            if isinstance(part, TextPart):
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, FilePart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                preview = attachment_service.preview(db, rec)
                text = preview.get("text")
                if not isinstance(text, str):
                    raise ChatTurnError("PROCESSOR_UNAVAILABLE", "File text extraction is not available for this attachment.")
                if isinstance(part.selection, TextSelection):
                    lines = text.splitlines()
                    text = "\n".join(lines[part.selection.start_line - 1:part.selection.end_line])
                elif isinstance(part.selection, PageSelection):
                    text = _select_pdf_pages(text, part.selection.pages)
                content.append({"type": "text", "text": f"\n[Attachment {rec.display_name} extracted text]\n{text}"})
            elif isinstance(part, ImagePart):
                rec = attachment_service.require(db, user.id, part.attachment_id)
                path = attachment_service.path_for(rec)
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{rec.mime_type};base64,{encoded}"},
                        "detail": part.detail,
                    }
                )
            elif isinstance(part, (AudioPart, VideoPart)):
                raise ChatTurnError("PROCESSOR_UNAVAILABLE", "Media processing is not enabled for chat turns yet.")
        return content

    def _event(self, db: DBSession, turn_id: str, attempt_id: str | None, event_type: str, payload: dict, event_key: str) -> None:
        db.flush()
        last = (
            db.query(ChatEventRecord.sequence)
            .filter(ChatEventRecord.turn_id == turn_id)
            .order_by(ChatEventRecord.sequence.desc())
            .first()
        )
        sequence = (last[0] if last else 0) + 1
        db.add(
            ChatEventRecord(
                id=f"evt_{uuid.uuid4().hex}",
                turn_id=turn_id,
                attempt_id=attempt_id,
                sequence=sequence,
                event_key=event_key,
                type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at=dt.datetime.utcnow(),
            )
        )


def _request_hash(req: ChatTurnCreate) -> str:
    payload = req.model_dump(mode="json")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _attachment_ids(req: ChatTurnCreate) -> list[str]:
    ids: list[str] = []
    for part in req.message.parts:
        if isinstance(part, (FilePart, ImagePart, AudioPart, VideoPart)) and part.attachment_id not in ids:
            ids.append(part.attachment_id)
    return ids


def _attachment_duration_ms(preview: dict) -> int | None:
    for derivative in preview.get("derivatives") or []:
        metadata = derivative.get("metadata") if isinstance(derivative, dict) else None
        if isinstance(metadata, dict) and isinstance(metadata.get("duration_ms"), int):
            return metadata["duration_ms"]
    return None


def _attachment_pages_detected(preview: dict) -> int | None:
    for derivative in preview.get("derivatives") or []:
        metadata = derivative.get("metadata") if isinstance(derivative, dict) else None
        if isinstance(metadata, dict) and isinstance(metadata.get("pages_detected"), int):
            return metadata["pages_detected"]
    return None


def _select_pdf_pages(text: str, pages: list[int]) -> str:
    wanted = set(pages)
    current_page: int | None = None
    selected: list[str] = []
    saw_page_marker = False
    for line in text.splitlines():
        match = re.match(r"^\[Page (\d+)]$", line.strip())
        if match:
            saw_page_marker = True
            current_page = int(match.group(1))
            if current_page in wanted:
                selected.append(line)
            continue
        if current_page in wanted:
            selected.append(line)
    if saw_page_marker:
        return "\n".join(selected).strip()
    return text
