from __future__ import annotations

import asyncio
import base64
import io
import os
import shutil
import subprocess
import sys
import uuid
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from main import app  # noqa: E402
from services.runtime_registry import RuntimeRegistry  # noqa: E402

_ONE_BY_ONE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _auth(client: TestClient, label: str = "mm") -> dict[str, str]:
    username = f"{label}-{uuid.uuid4().hex[:10]}"
    created = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "email": f"{username}@example.test"},
    )
    assert created.status_code == 200, created.text
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "secret123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_attachment_upload_preview_download_and_cross_user_block():
    with TestClient(app) as client:
        owner = _auth(client, "owner")
        other = _auth(client, "other")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=owner,
            files={"file": ("notes.md", b"# Title\nhello", "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]
        assert uploaded.json()["mime_type"] == "text/markdown"

        preview = client.get(f"/api/v1/attachments/{attachment_id}/preview", headers=owner)
        assert preview.status_code == 200, preview.text
        assert preview.json()["text"].startswith("# Title")

        content = client.get(f"/api/v1/attachments/{attachment_id}/content", headers=owner)
        assert content.status_code == 200
        assert content.content == b"# Title\nhello"

        ranged = client.get(
            f"/api/v1/attachments/{attachment_id}/content",
            headers={**owner, "Range": "bytes=2-6"},
        )
        assert ranged.status_code == 206
        assert ranged.headers["content-range"] == "bytes 2-6/13"
        assert ranged.content == b"Title"

        head = client.head(f"/api/v1/attachments/{attachment_id}/content", headers=owner)
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["content-length"] == "13"

        blocked = client.get(f"/api/v1/attachments/{attachment_id}", headers=other)
        assert blocked.status_code == 404
        assert blocked.json()["detail"]["code"] == "ATTACHMENT_UNAVAILABLE"

        deleted = client.delete(f"/api/v1/attachments/{attachment_id}", headers=owner)
        assert deleted.status_code == 200
        assert deleted.json()["references"]["message_count"] == 0
        assert deleted.json()["physical_cleanup"] == "deferred"
        gone = client.get(f"/api/v1/attachments/{attachment_id}", headers=owner)
        assert gone.status_code == 404
        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=owner, json=payload)
        assert preflight.status_code == 404
        assert preflight.json()["detail"]["code"] == "ATTACHMENT_UNAVAILABLE"


def test_chat_turn_accepts_text_file_parts_and_replays_events(monkeypatch):
    async def fake_chat(self, model, messages, **kwargs):
        return {"model": model, "content": f"seen:{messages[-1]['content']}"}

    monkeypatch.setattr(RuntimeRegistry, "chat", fake_chat)

    with TestClient(app) as client:
        headers = _auth(client, "turn")
        session = client.post("/api/v1/sessions", headers=headers, json={"title": "mm"})
        assert session.status_code == 200, session.text
        session_id = session.json()["id"]

        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("data.txt", b"alpha\nbeta", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]

        payload = {
            "schema_version": 1,
            "session_id": session_id,
            "target": {"kind": "legacy", "model": "mock"},
            "mode": "chat",
            "message": {
                "parts": [
                    {"type": "text", "text": "summarize"},
                    {"type": "file", "attachment_id": attachment_id, "processing": "extract_text"},
                ]
            },
            "requested_outputs": [{"type": "text"}, {"type": "artifact", "format": "txt"}],
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }

        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is True
        estimate = preflight.json()["context_estimate"]
        assert estimate["text_characters"] == len("summarize")
        assert estimate["attachments"] == 1
        assert estimate["estimated_prompt_characters"] >= len("alpha\nbeta")

        capabilities = client.get("/api/v1/chat/capabilities", headers=headers)
        assert capabilities.status_code == 200, capabilities.text
        assert capabilities.json()["capabilities"]["dependencies"]["wav_metadata"]["available"] is True

        out_of_range = {
            **payload,
            "message": {
                "parts": [
                    {"type": "file", "attachment_id": attachment_id, "processing": "extract_text", "selection": {"kind": "lines", "start_line": 1, "end_line": 9}}
                ]
            },
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        bad_selection = client.post("/api/v1/chat/preflight", headers=headers, json=out_of_range)
        assert bad_selection.status_code == 200, bad_selection.text
        assert bad_selection.json()["ok"] is False
        assert any(item["code"] == "SELECTION_OUT_OF_RANGE" for item in bad_selection.json()["blockers"])

        created = client.post("/api/v1/chat/turns", headers=headers, json=payload)
        assert created.status_code == 202, created.text
        body = created.json()
        turn_id = body["turn"]["id"]
        assert body["turn"]["status"] == "RUNNING"
        assert any(message["role"] == "user" for message in body["messages"])

        completed = client.get(f"/api/v1/chat/turns/{turn_id}", headers=headers)
        assert completed.status_code == 200, completed.text
        assert completed.json()["turn"]["status"] == "SUCCEEDED"
        assert any(message["role"] == "assistant" and "alpha" in message["content"] for message in completed.json()["messages"])

        repeated = client.post("/api/v1/chat/turns", headers=headers, json=payload)
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["turn"]["id"] == turn_id

        cancel_terminal = client.post(f"/api/v1/chat/turns/{turn_id}/cancel", headers=headers)
        assert cancel_terminal.status_code == 200, cancel_terminal.text
        assert cancel_terminal.json()["turn"]["status"] == "SUCCEEDED"
        assert cancel_terminal.json()["cancellation"] == {
            "accepted": False,
            "reason": "TURN_ALREADY_TERMINAL",
            "status": "SUCCEEDED",
        }

        retried = client.post(f"/api/v1/chat/turns/{turn_id}/retry", headers=headers, json=payload)
        assert retried.status_code == 202, retried.text
        retry_body = retried.json()
        assert [attempt["attempt_no"] for attempt in retry_body["attempts"]] == [1, 2]
        assert retry_body["turn"]["status"] == "SUCCEEDED"
        assert sum(1 for message in retry_body["messages"] if message["role"] == "user") == 1
        assert sum(1 for message in retry_body["messages"] if message["role"] == "assistant") == 2

        conflicting_retry = client.post(
            f"/api/v1/chat/turns/{turn_id}/retry",
            headers=headers,
            json={**payload, "message": {"parts": [{"type": "text", "text": "different"}]}},
        )
        assert conflicting_retry.status_code == 409
        assert conflicting_retry.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

        conflicting_payload = {**payload, "message": {"parts": [{"type": "text", "text": "different"}]}}
        conflict = client.post("/api/v1/chat/turns", headers=headers, json=conflicting_payload)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

        events = client.get(f"/api/v1/chat/turns/{turn_id}/events", headers=headers)
        assert events.status_code == 200, events.text
        event_types = [event["type"] for event in events.json()["events"]]
        assert "turn.created" in event_types
        assert "turn.finished" in event_types
        assert "artifact.created" in event_types
        assert any(event["attempt_id"] == retry_body["attempts"][1]["id"] and event["type"] == "turn.status_changed" for event in events.json()["events"])

        attachments = client.get(f"/api/v1/sessions/{session_id}/attachments", headers=headers)
        assert attachments.status_code == 200
        assert any(item["id"] == attachment_id for item in attachments.json())

        artifacts = client.get(f"/api/v1/sessions/{session_id}/artifacts", headers=headers)
        assert artifacts.status_code == 200
        assert len(artifacts.json()) == 2
        artifact_id = artifacts.json()[0]["id"]
        versions = client.get(f"/api/v1/artifacts/{artifact_id}/versions", headers=headers)
        assert versions.status_code == 200
        assert versions.json()[0]["version"] == 1
        downloaded = client.get(f"/api/v1/artifacts/{artifact_id}/versions/1/content", headers=headers)
        assert downloaded.status_code == 200
        assert b"seen:" in downloaded.content
        artifact_range = client.get(
            f"/api/v1/artifacts/{artifact_id}/versions/1/content",
            headers={**headers, "Range": "bytes=0-4"},
        )
        assert artifact_range.status_code == 206
        assert artifact_range.content == b"seen:"
        artifact_head = client.head(f"/api/v1/artifacts/{artifact_id}/versions/1/content", headers=headers)
        assert artifact_head.status_code == 200
        assert artifact_head.content == b""

        new_version = client.post(
            f"/api/v1/artifacts/{artifact_id}/versions",
            headers=headers,
            json={"expected_version": 1, "content": "updated artifact", "mime_type": "text/plain"},
        )
        assert new_version.status_code == 201, new_version.text
        assert new_version.json()["artifact"]["current_version"] == 2
        assert new_version.json()["version"]["version"] == 2
        assert new_version.json()["version"]["parent_version"] == 1
        versions_after_update = client.get(f"/api/v1/artifacts/{artifact_id}/versions", headers=headers)
        assert [item["version"] for item in versions_after_update.json()] == [1, 2]
        original_after_update = client.get(f"/api/v1/artifacts/{artifact_id}/versions/1/content", headers=headers)
        assert original_after_update.status_code == 200
        assert b"seen:" in original_after_update.content
        updated_download = client.get(f"/api/v1/artifacts/{artifact_id}/versions/2/content", headers=headers)
        assert updated_download.status_code == 200
        assert updated_download.content == b"updated artifact"
        version_conflict = client.post(
            f"/api/v1/artifacts/{artifact_id}/versions",
            headers=headers,
            json={"expected_version": 1, "content": "stale update", "mime_type": "text/plain"},
        )
        assert version_conflict.status_code == 409
        assert version_conflict.json()["detail"]["code"] == "ARTIFACT_VERSION_CONFLICT"


def test_chat_turn_cancel_before_background_execution_marks_cancelled(monkeypatch):
    from api import chat as chat_api

    captured = {}
    original_background = chat_api._run_chat_turn_background

    async def hold_background(*args):
        captured["args"] = args

    monkeypatch.setattr(chat_api, "_run_chat_turn_background", hold_background)

    with TestClient(app) as client:
        headers = _auth(client, "cancel-turn")
        payload = {
            "message": {"parts": [{"type": "text", "text": "cancel me"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        created = client.post("/api/v1/chat/turns", headers=headers, json=payload)
        assert created.status_code == 202, created.text
        turn_id = created.json()["turn"]["id"]
        assert created.json()["execution"] == {"created": True, "scheduled": True}
        assert created.json()["turn"]["status"] == "RUNNING"

        cancelled = client.post(f"/api/v1/chat/turns/{turn_id}/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["cancellation"] == {"accepted": True, "status": "CANCEL_REQUESTED"}
        assert cancelled.json()["turn"]["status"] == "CANCEL_REQUESTED"

        retry_active = client.post(f"/api/v1/chat/turns/{turn_id}/retry", headers=headers, json=payload)
        assert retry_active.status_code == 409
        assert retry_active.json()["detail"]["code"] == "CHAT_TURN_ACTIVE"

        assert "args" in captured
        asyncio.run(original_background(*captured["args"]))

        snapshot = client.get(f"/api/v1/chat/turns/{turn_id}", headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["turn"]["status"] == "CANCELLED"
        assert snapshot.json()["attempts"][0]["status"] == "CANCELLED"


def test_chat_turn_rejects_image_until_native_serializer_exists():
    with TestClient(app) as client:
        headers = _auth(client, "image")
        other = _auth(client, "image-other")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("sample.png", _ONE_BY_ONE_PNG, "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        preview = client.get(f"/api/v1/attachments/{uploaded.json()['id']}/preview", headers=headers)
        assert preview.status_code == 200
        image_preview = next(item for item in preview.json()["derivatives"] if item["kind"] == "image_preview")
        assert image_preview["metadata"]["width"] == 1
        assert image_preview["metadata"]["height"] == 1
        thumbnail = client.get(
            f"/api/v1/attachments/{uploaded.json()['id']}/derivatives/{image_preview['id']}/content",
            headers=headers,
        )
        assert thumbnail.status_code == 200, thumbnail.text
        assert thumbnail.headers["content-type"].startswith("image/jpeg")
        assert thumbnail.content.startswith(b"\xff\xd8")
        thumbnail_head = client.head(
            f"/api/v1/attachments/{uploaded.json()['id']}/derivatives/{image_preview['id']}/content",
            headers=headers,
        )
        assert thumbnail_head.status_code == 200
        assert thumbnail_head.content == b""
        blocked_thumbnail = client.get(
            f"/api/v1/attachments/{uploaded.json()['id']}/derivatives/{image_preview['id']}/content",
            headers=other,
        )
        assert blocked_thumbnail.status_code == 404
        payload = {
            "message": {"parts": [{"type": "image", "attachment_id": uploaded.json()["id"]}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is False
        created = client.post("/api/v1/chat/turns", headers=headers, json=payload)
        assert created.status_code == 422
        assert created.json()["detail"]["code"] == "MODEL_INPUT_UNSUPPORTED"


def test_unknown_content_part_is_rejected():
    with TestClient(app) as client:
        headers = _auth(client, "bad-part")
        payload = {
            "message": {"parts": [{"type": "binary", "attachment_id": "att_missing"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        rejected = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert rejected.status_code == 422


def test_chat_turn_sends_image_parts_to_remote_provider(monkeypatch):
    from services.runtimes.openai_api_runtime import OpenAIRuntime

    captured = {}

    async def fake_remote_chat(self, model, messages, **kwargs):
        captured["model"] = model
        captured["messages"] = messages
        return {"model": model, "content": "vision ok"}

    monkeypatch.setattr(OpenAIRuntime, "chat", fake_remote_chat)

    with TestClient(app) as client:
        headers = _auth(client, "remote-image")
        provider = client.post(
            "/api/v1/providers",
            headers=headers,
            json={
                "name": "local-test-provider",
                "base_url": "http://localhost:9999/v1",
                "protocol": "responses",
                "default_model": "gpt-vision",
                "api_key": "sk-test",
            },
        )
        assert provider.status_code == 200, provider.text
        provider_id = provider.json()["id"]
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("sample.png", _ONE_BY_ONE_PNG, "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        payload = {
            "target": {"kind": "remote", "model": "gpt-vision", "provider_id": provider_id},
            "message": {
                "parts": [
                    {"type": "text", "text": "describe"},
                    {"type": "image", "attachment_id": uploaded.json()["id"], "detail": "low"},
                ]
            },
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is True

        created = client.post("/api/v1/chat/turns", headers=headers, json=payload)
        assert created.status_code == 202, created.text
        assert captured["model"] == "gpt-vision"
        content = captured["messages"][-1]["content"]
        assert content[0] == {"type": "text", "text": "describe"}
        assert content[1]["type"] == "image_url"
        assert content[1]["detail"] == "low"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_wav_upload_exposes_metadata_but_requires_audio_processing():
    with TestClient(app) as client:
        headers = _auth(client, "wav")
        wav = _tiny_wav_bytes()
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("tone.wav", wav, "audio/wav")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["metadata"]["category"] == "audio"
        attachment_id = uploaded.json()["id"]
        preview = client.get(f"/api/v1/attachments/{attachment_id}/preview", headers=headers)
        assert preview.status_code == 200, preview.text
        derivative = next(item for item in preview.json()["derivatives"] if item["kind"] == "audio_metadata")
        assert derivative["metadata"]["sample_rate"] == 8000
        assert derivative["metadata"]["channels"] == 1
        assert derivative["metadata"]["duration_ms"] == 100

        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is False
        assert preflight.json()["blockers"][0]["code"] == "PROCESSOR_UNAVAILABLE"

        audio_payload = {
            "message": {"parts": [{"type": "audio", "attachment_id": attachment_id, "processing": "asr", "selection": {"kind": "time", "start_ms": 0, "end_ms": 50}}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        audio_preflight = client.post("/api/v1/chat/preflight", headers=headers, json=audio_payload)
        assert audio_preflight.status_code == 200, audio_preflight.text
        assert audio_preflight.json()["ok"] is False
        assert audio_preflight.json()["inputs"][0]["type"] == "audio"
        assert audio_preflight.json()["blockers"][0]["code"] == "PROCESSOR_UNAVAILABLE"

        out_of_range_audio = {
            "message": {"parts": [{"type": "audio", "attachment_id": attachment_id, "processing": "asr", "selection": {"kind": "time", "start_ms": 0, "end_ms": 500}}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        out_of_range_preflight = client.post("/api/v1/chat/preflight", headers=headers, json=out_of_range_audio)
        assert out_of_range_preflight.status_code == 200, out_of_range_preflight.text
        assert any(item["code"] == "SELECTION_OUT_OF_RANGE" for item in out_of_range_preflight.json()["blockers"])


def test_preflight_context_estimate_counts_selected_file_text():
    with TestClient(app) as client:
        headers = _auth(client, "ctx")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("lines.txt", b"one\ntwo\nthree", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        payload = {
            "schema_version": 1,
            "target": {"kind": "legacy", "model": "mock"},
            "mode": "chat",
            "message": {
                "parts": [
                    {"type": "text", "text": "read"},
                    {"type": "file", "attachment_id": uploaded.json()["id"], "processing": "extract_text", "selection": {"kind": "lines", "start_line": 2, "end_line": 3}},
                ]
            },
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }

        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)

    assert preflight.status_code == 200, preflight.text
    estimate = preflight.json()["context_estimate"]
    assert estimate == {
        "text_characters": 4,
        "estimated_prompt_characters": len("read") + len("two\nthree"),
        "attachments": 1,
        "selected_parts": 1,
    }


def test_chat_turn_context_exclusions_remove_messages_and_attachment_sources(monkeypatch):
    captured: list[list[dict]] = []

    async def fake_chat(self, model, messages, **kwargs):
        captured.append(list(messages))
        return {"model": model, "content": f"seen:{messages[-1]['content']}"}

    monkeypatch.setattr(RuntimeRegistry, "chat", fake_chat)

    with TestClient(app) as client:
        headers = _auth(client, "ctx-exclude")
        session_id = client.post("/api/v1/sessions", headers=headers, json={"title": "ctx"}).json()["id"]
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("source.txt", b"secret source", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]

        first_payload = {
            "schema_version": 1,
            "session_id": session_id,
            "target": {"kind": "legacy", "model": "mock"},
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        first = client.post("/api/v1/chat/turns", headers=headers, json=first_payload)
        assert first.status_code == 202, first.text
        first_turn_id = first.json()["turn"]["id"]
        first_snapshot = client.get(f"/api/v1/chat/turns/{first_turn_id}", headers=headers)
        assert first_snapshot.status_code == 200, first_snapshot.text
        assert "secret source" in first_snapshot.text

        second_payload = {
            "schema_version": 1,
            "session_id": session_id,
            "target": {"kind": "legacy", "model": "mock"},
            "message": {"parts": [{"type": "text", "text": "continue"}]},
            "context": {"excluded_message_ids": [], "excluded_attachment_ids": [attachment_id], "use_memory": False},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        second = client.post("/api/v1/chat/turns", headers=headers, json=second_payload)

    assert second.status_code == 202, second.text
    second_messages = captured[-1]
    assert [message["content"] for message in second_messages] == ["continue"]
    assert second.json()["turn"]["context_manifest"]["excluded_attachment_ids"] == [attachment_id]


def test_chat_turn_rejects_current_attachment_when_explicitly_excluded():
    with TestClient(app) as client:
        headers = _auth(client, "ctx-current-exclude")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("notes.txt", b"not allowed", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]
        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text"}]},
            "context": {"excluded_message_ids": [], "excluded_attachment_ids": [attachment_id], "use_memory": False},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }

        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)

    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["ok"] is False
    assert any(item["code"] == "ATTACHMENT_EXCLUDED" for item in preflight.json()["blockers"])


def test_session_message_search_and_pin_are_scoped_to_session():
    with TestClient(app) as client:
        headers = _auth(client, "message-workflow")
        session_a = client.post("/api/v1/sessions", headers=headers, json={"title": "a"}).json()["id"]
        session_b = client.post("/api/v1/sessions", headers=headers, json={"title": "b"}).json()["id"]
        alpha = client.post(
            f"/api/v1/sessions/{session_a}/messages",
            headers=headers,
            json={"role": "user", "content": "alpha searchable"},
        )
        assert alpha.status_code == 200, alpha.text
        beta = client.post(
            f"/api/v1/sessions/{session_b}/messages",
            headers=headers,
            json={"role": "user", "content": "alpha other session"},
        )
        assert beta.status_code == 200, beta.text

        found = client.get(f"/api/v1/sessions/{session_a}/messages/search", headers=headers, params={"q": "alpha"})
        assert found.status_code == 200, found.text
        assert [item["id"] for item in found.json()] == [alpha.json()["id"]]

        pinned = client.patch(
            f"/api/v1/sessions/{session_a}/messages/{alpha.json()['id']}/pin",
            headers=headers,
            json={"pinned": True},
        )
        assert pinned.status_code == 200, pinned.text
        assert pinned.json()["is_pinned"] is True
        assert pinned.json()["pinned_at"] is not None

        pinned_only = client.get(
            f"/api/v1/sessions/{session_a}/messages/search",
            headers=headers,
            params={"q": "", "pinned_only": True},
        )
        assert [item["id"] for item in pinned_only.json()] == [alpha.json()["id"]]

        wrong_session_pin = client.patch(
            f"/api/v1/sessions/{session_a}/messages/{beta.json()['id']}/pin",
            headers=headers,
            json={"pinned": True},
        )
        assert wrong_session_pin.status_code == 404


def test_session_export_storage_usage_and_deleted_attachment_cleanup(monkeypatch):
    async def fake_chat(self, model, messages, **kwargs):
        return {"model": model, "content": "artifact body"}

    monkeypatch.setattr(RuntimeRegistry, "chat", fake_chat)

    with TestClient(app) as client:
        headers = _auth(client, "export")
        session_id = client.post("/api/v1/sessions", headers=headers, json={"title": "export"}).json()["id"]
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("source.txt", b"source bytes", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]
        payload = {
            "session_id": session_id,
            "target": {"kind": "legacy", "model": "mock"},
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text"}]},
            "requested_outputs": [{"type": "text"}, {"type": "artifact", "format": "txt"}],
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        created = client.post("/api/v1/chat/turns", headers=headers, json=payload)
        assert created.status_code == 202, created.text

        exported = client.get(f"/api/v1/sessions/{session_id}/export", headers=headers)
        assert exported.status_code == 200, exported.text
        export_body = exported.json()
        assert export_body["privacy"] == {
            "includes_raw_attachment_bytes": False,
            "includes_internal_storage_paths": False,
            "includes_credentials": False,
        }
        assert export_body["messages"]
        assert export_body["attachments"][0]["id"] == attachment_id
        assert export_body["artifacts"]
        assert export_body["artifact_versions"]
        assert "storage_key" not in str(export_body)
        assert "source bytes" not in str(export_body)

        usage = client.get(f"/api/v1/sessions/{session_id}/storage", headers=headers)
        assert usage.status_code == 200, usage.text
        assert usage.json()["input_attachment_count"] == 1
        assert usage.json()["artifact_count"] == 1
        assert usage.json()["managed_bytes"] >= uploaded.json()["size_bytes"]

        deleted = client.delete(f"/api/v1/attachments/{attachment_id}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        cleanup = client.post("/api/v1/attachments/cleanup-deleted", headers=headers, params={"limit": 10})
        assert cleanup.status_code == 200, cleanup.text
        assert cleanup.json()["deleted_files"] == []
        assert cleanup.json()["skipped"][0]["attachment_id"] == attachment_id


def test_office_ooxml_upload_exposes_safe_text_preview_and_can_preflight():
    with TestClient(app) as client:
        headers = _auth(client, "office")
        uploaded_docx = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={
                "file": (
                    "notes.docx",
                    _minimal_docx_bytes("Hello DOCX", "Second paragraph"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert uploaded_docx.status_code == 200, uploaded_docx.text
        assert uploaded_docx.json()["metadata"]["category"] == "office"
        preview_docx = client.get(f"/api/v1/attachments/{uploaded_docx.json()['id']}/preview", headers=headers)
        assert preview_docx.status_code == 200, preview_docx.text
        assert "Hello DOCX" in preview_docx.json()["text"]

        uploaded_xlsx = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={
                "file": (
                    "sheet.xlsx",
                    _minimal_xlsx_bytes("Cell A", "Cell B"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert uploaded_xlsx.status_code == 200, uploaded_xlsx.text
        preview_xlsx = client.get(f"/api/v1/attachments/{uploaded_xlsx.json()['id']}/preview", headers=headers)
        assert preview_xlsx.status_code == 200, preview_xlsx.text
        assert "Cell A" in preview_xlsx.json()["text"]

        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": uploaded_docx.json()["id"], "processing": "extract_text"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is True


def test_pdf_upload_exposes_basic_text_preview_and_can_preflight():
    with TestClient(app) as client:
        headers = _auth(client, "pdf")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("notes.pdf", _minimal_pdf_bytes("Hello PDF"), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["metadata"]["category"] == "pdf"

        preview = client.get(f"/api/v1/attachments/{uploaded.json()['id']}/preview", headers=headers)
        assert preview.status_code == 200, preview.text
        assert "Hello PDF" in preview.json()["text"]
        derivative = next(item for item in preview.json()["derivatives"] if item["kind"] == "text_preview")
        assert derivative["processor_version"] == "builtin-pdf-basic-v1"
        assert derivative["metadata"]["ocr_required"] is False

        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": uploaded.json()["id"], "processing": "extract_text"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is True


def test_pdf_page_selection_validates_detected_page_range():
    with TestClient(app) as client:
        headers = _auth(client, "pdf-pages")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("pages.pdf", _minimal_pdf_bytes("First page", "Second page"), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]
        preview = client.get(f"/api/v1/attachments/{attachment_id}/preview", headers=headers)
        assert preview.status_code == 200, preview.text
        assert "[Page 1]" in preview.json()["text"]
        assert "[Page 2]" in preview.json()["text"]
        derivative = next(item for item in preview.json()["derivatives"] if item["kind"] == "text_preview")
        assert derivative["metadata"]["pages_detected"] == 2

        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text", "selection": {"kind": "pages", "pages": [2]}}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is True
        assert preflight.json()["inputs"][0]["selection"] == {"kind": "pages", "pages": [2]}

        out_of_range = {
            **payload,
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text", "selection": {"kind": "pages", "pages": [3]}}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        blocked = client.post("/api/v1/chat/preflight", headers=headers, json=out_of_range)
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["ok"] is False
        assert blocked.json()["blockers"][0]["code"] == "SELECTION_OUT_OF_RANGE"


def test_pdf_without_extractable_text_requires_ocr_before_preflight():
    with TestClient(app) as client:
        headers = _auth(client, "pdf-scan")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("scan.pdf", _minimal_pdf_bytes(), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment_id = uploaded.json()["id"]
        preview = client.get(f"/api/v1/attachments/{attachment_id}/preview", headers=headers)
        assert preview.status_code == 200, preview.text
        derivative = next(item for item in preview.json()["derivatives"] if item["kind"] == "text_preview")
        assert derivative["state"] == "FAILED"
        assert derivative["metadata"]["ocr_required"] is True

        payload = {
            "message": {"parts": [{"type": "file", "attachment_id": attachment_id, "processing": "extract_text"}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is False
        assert preflight.json()["blockers"][0]["code"] == "PROCESSOR_UNAVAILABLE"


def test_agent_mode_preflight_is_disabled_until_sandbox_execution_exists():
    with TestClient(app) as client:
        headers = _auth(client, "agent-mode")
        payload = {
            "schema_version": 1,
            "target": {"kind": "legacy", "model": "mock"},
            "mode": "agent",
            "message": {"parts": [{"type": "text", "text": "inspect"}]},
            "requested_outputs": [{"type": "text"}],
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }

        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)

    assert preflight.status_code == 503, preflight.text
    assert preflight.json()["detail"]["code"] == "SANDBOX_UNAVAILABLE"


def test_video_upload_exposes_metadata_and_video_part_is_blocked(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is not installed")
    mp4_path = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:d=0.2:r=1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(mp4_path),
        ],
        check=True,
        timeout=20,
    )
    with TestClient(app) as client:
        headers = _auth(client, "video")
        uploaded = client.post(
            "/api/v1/attachments",
            headers=headers,
            files={"file": ("clip.mp4", mp4_path.read_bytes(), "video/mp4")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["metadata"]["category"] == "video"
        attachment_id = uploaded.json()["id"]
        preview = client.get(f"/api/v1/attachments/{attachment_id}/preview", headers=headers)
        assert preview.status_code == 200, preview.text
        derivative = next(item for item in preview.json()["derivatives"] if item["kind"] == "video_metadata")
        assert derivative["state"] == "SUCCEEDED"
        assert derivative["metadata"]["width"] == 16
        assert derivative["metadata"]["height"] == 16
        frame = next(item for item in preview.json()["derivatives"] if item["kind"] == "video_frame")
        assert frame["state"] == "SUCCEEDED"
        assert frame["processor_version"] == "ffmpeg-frame-v1"
        assert frame["metadata"]["time_ms"] == 0
        frame_content = client.get(
            f"/api/v1/attachments/{attachment_id}/derivatives/{frame['id']}/content",
            headers=headers,
        )
        assert frame_content.status_code == 200, frame_content.text
        assert frame_content.content.startswith(b"\xff\xd8\xff")

        payload = {
            "message": {"parts": [{"type": "video", "attachment_id": attachment_id, "processing": "frames_asr", "selection": {"kind": "time", "start_ms": 0, "end_ms": 100}}]},
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        }
        preflight = client.post("/api/v1/chat/preflight", headers=headers, json=payload)
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["ok"] is False
        assert preflight.json()["inputs"][0]["type"] == "video"
        assert preflight.json()["blockers"][0]["code"] == "PROCESSOR_UNAVAILABLE"


def _tiny_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(8000)
        audio.writeframes(b"\x80" * 800)
    return buffer.getvalue()


def _minimal_docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs
    )
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>
""".encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _minimal_xlsx_bytes(*values: str) -> bytes:
    shared_items = "".join(f"<si><t>{value}</t></si>" for value in values)
    cells = "".join(f"<c r=\"A{index + 1}\" t=\"s\"><v>{index}</v></c>" for index, _value in enumerate(values))
    shared = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared_items}</sst>
""".encode("utf-8")
    sheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">{cells}</row></sheetData></worksheet>
""".encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def _minimal_pdf_bytes(*pages: str) -> bytes:
    page_texts = list(pages)
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(page_texts) or 1))
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {len(page_texts) or 1} >> endobj".encode("ascii"),
    ]
    if not page_texts:
        objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> >> endobj")
        objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj")
    else:
        for index, text in enumerate(page_texts):
            page_obj = 3 + index * 2
            contents_obj = page_obj + 1
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
            objects.extend(
                [
                    f"{page_obj} 0 obj << /Type /Page /Parent 2 0 R /Resources << /Font << /F1 99 0 R >> >> /Contents {contents_obj} 0 R >> endobj".encode("ascii"),
                    b"%d 0 obj << /Length " % contents_obj + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream\nendobj",
                ]
            )
        objects.append(b"99 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj")
    return b"\n".join([b"%PDF-1.4", *objects, b"%%EOF"])
