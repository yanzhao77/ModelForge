# Multimodal Chat Foundation Verification

Date: 2026-09-14

Scope implemented in this slice:

- Structured chat content schema for text/file/image parts.
- Managed attachment metadata, derivatives, message links, chat turns, attempts, events, artifacts, and artifact versions.
- SQLite additive migration ledger and PostgreSQL Alembic revision `0009_multimodal_chat_foundation`.
- Attachment API: upload, metadata, preview, content download/HEAD, process status, delete.
- Structured chat API: capabilities, preflight, turn creation, turn snapshot, event replay.
- Session-level attachment and artifact listing; artifact version listing and exact-version download.
- Text artifacts can now create a new immutable version through `POST /artifacts/{id}/versions` with `expected_version`; stale updates return `ARTIFACT_VERSION_CONFLICT` and old version downloads remain unchanged.
- The desktop Chat page includes a compact session artifact list. It can refresh artifacts, show version summaries, and add the latest artifact version back into the next message's attachment queue by stable `attachment_id`.
- Desktop client API methods and Chat page attachment queue with structured-turn send path.
- Remote OpenAI-compatible image content path: structured image parts become managed-file data URLs and are mapped to Responses `input_image` or Chat Completions `image_url` payloads.
- Attachment and artifact content downloads rely on authenticated `FileResponse` with verified HEAD and Range behavior.
- Image upload records basic width/height/pixel metadata through Pillow when available.
- WAV upload records duration/sample-rate/channel metadata through the Python standard library `wave` module.
- MP4/WebM/MOV upload is admitted as managed storage and attempts metadata extraction through local `ffprobe`; decode/tool absence is recorded as a failed derivative, not as model understanding.
- Video upload now attempts one authenticated JPEG frame derivative through local `ffmpeg`, recording `time_ms`, dimensions, and MIME metadata. Frame extraction failure is recorded as a failed derivative, not as model understanding.
- DOCX/XLSX upload is admitted as managed storage and receives a bounded, read-only OOXML text preview using Python standard-library ZIP/XML parsing. The parser does not execute macros, formulas, or external links; it records macro presence as metadata only.
- PDF upload now receives a bounded, read-only basic text preview for simple text content streams, including Flate-decoded streams when possible. Preview text is marked with page labels when extractable, page selections are range-checked during preflight, and empty extraction is marked as OCR-required metadata instead of being treated as successful model-readable text.
- Audio/video content parts are accepted by the request schema, preserve optional time selections, and are blocked by preflight with `PROCESSOR_UNAVAILABLE` until ASR, frame extraction, or native media adapters are enabled.
- Image uploads create authenticated JPEG thumbnail derivatives; owner HEAD/GET succeeds and another user receives `ATTACHMENT_UNAVAILABLE`.
- Attachment deletion is soft-revocation for API access and future preflight use.
- Attachment metadata now includes a reference summary. Deletion is blocked while an active ChatTurn references the attachment, and a cleanup helper physically removes only deleted attachments that are no longer referenced by messages.
- Structured turn idempotency rejects key reuse with a different payload.
- Structured turn creation now persists the turn/user message/attempt/events before execution and returns a RUNNING snapshot. Execution is dispatched through a background task using a fresh SQLAlchemy session.
- Idempotent replay of an existing turn returns the existing snapshot without scheduling another background execution.
- Structured turn retry endpoint is present. It requires the caller to resubmit the same request payload, re-runs preflight, creates a new attempt, and does not insert a duplicate user message.
- Structured chat turn cancellation endpoint is present. Terminal turns return an idempotent no-op cancellation result instead of mutating completed history. A RUNNING turn moves to CANCEL_REQUESTED, and a background worker that starts after cancellation marks the attempt and turn CANCELLED before calling the model.
- Startup recovery now reconciles orphaned structured chat turns. Leftover `CANCEL_REQUESTED` turns become `CANCELLED`; leftover `QUEUED`, `RUNNING`, or `WAITING_INPUT` turns become `INTERRUPTED`; active attempts receive matching terminal status and a replayable `turn.finished` event.
- Sandbox diagnostics are exposed at `GET /api/v1/sandbox/status`. The diagnostics report Docker availability and security options but keep `execution_enabled=false` and `host_fallback=false` until a real isolated executor is implemented.
- Sandbox provider now includes a guarded Docker Python executor behind `MODELFORGE_SANDBOX_EXECUTION=1` and an already-present local image. It uses no network, bounded CPU/memory/PIDs, a read-only container root filesystem, an isolated temporary workspace, and never falls back to host execution. This is an execution contract slice; real container escape/resource tests still remain.
- The sandbox executor is registered as the `sandbox.execute` Agent tool with `EXECUTE` permission and a legacy `sandbox_execute` alias. Existing Policy checks deny it by default and can require human approval before execution.
- Desktop Chat page has an explicit Chat/Agent mode selector. Agent mode uses the structured turn preflight path even for text-only messages; the backend currently rejects it with `SANDBOX_UNAVAILABLE` instead of running tools or falling back to host execution.
- Chat capabilities include local processor dependency diagnostics, and preflight validates text line ranges plus audio/video time ranges when metadata is available.
- PySide API client exposes derivative download, attachment deletion, and chat-turn cancellation wrappers so UI code does not construct raw endpoint URLs.
- PySide API client exposes chat-turn retry. Chat page structured sends now call preflight before create, report blockers inline, map audio/video MIME types to audio/video parts instead of generic file extraction, fetch a turn snapshot after background submission, and route Stop to chat-turn cancellation for active structured turns.
- Chat page now follows structured turn event watermarks after submission by polling `after_sequence`; completed assistant messages are inserted once, artifact-created events are surfaced, and terminal events trigger a final snapshot refresh.
- Structured chat preflight now returns a compact `context_estimate` for text characters, estimated submitted characters, attachment count, and explicit selections. The desktop structured-send path displays the estimate before dispatch.
- Structured chat context options now support excluding prior message IDs and attachment IDs. Excluding an attachment removes messages that directly reference it plus same-turn assistant results from the submitted history, and preflight blocks a current attachment part that is explicitly excluded.
- Structured chat memory remains off by default; `use_memory=true` is required before the structured turn path injects or extracts user memory.
- Session messages now support scoped search plus persisted pin/unpin state. The desktop Chat page exposes current-session message search, pinned-message listing, and pin/unpin actions from the search result list.
- Session export and storage usage endpoints now provide a safe JSON export without raw attachment bytes, internal storage keys, or credentials; a deleted-attachment cleanup endpoint only removes deleted attachments that no longer have message references.
- Chat composer accepts dragged or pasted local files into the attachment queue. Pasted images are saved as temporary PNG files and uploaded through the same Attachment API. The attachment queue supports double-click basic previews using authenticated preview metadata/text.
- SQLite legacy local databases with an existing pre-multimodal `messages` table are upgraded additively and repeatably by `_apply_schema_migrations()` after ORM-created missing tables are present.
- Attachment storage reconciliation reports missing database-backed files, database-external orphan files, and expired temporary upload fragments without deleting data.
- Alembic migration graph is merged to one head (`0010_merge_heads`). A temporary PostgreSQL 16 container upgraded an empty database to head and accepted a repeated `upgrade head` run.

Dependency probe on 2026-09-14:

| Dependency | Observed | Current use |
|---|---:|---|
| Pillow (`PIL`) | available | image width/height metadata |
| Python `wave` | available | WAV metadata |
| `ffmpeg` / `ffprobe` | available at `/opt/homebrew/bin` | video metadata test fixture / video metadata probe |
| `pypdf`, `PyPDF2`, `pdfplumber` | unavailable | PDF text/OCR remains disabled |
| `docx`, `openpyxl` | unavailable | not required for the current bounded built-in OOXML text preview |
| `cv2`, `moviepy`, `soundfile`, `whisper`, `librosa`, `pydub` | unavailable | ASR, frame extraction, and richer media parsing remain disabled |
| Docker | CLI present at `/usr/local/bin/docker` | not verified as a usable/rootless sandbox provider |

Validation commands:

```bash
.venv/bin/python -m py_compile backend/app/models/records.py backend/app/services/attachment_service.py backend/app/services/artifact_service.py backend/app/services/chat_turn_service.py backend/app/api/attachments.py backend/app/api/artifacts.py backend/app/api/chat.py backend/app/api/sessions.py backend/app/main.py
.venv/bin/python -m py_compile client/pyside6/api_client/client.py client/pyside6/pages/chat_page.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_chat_model_registry.py -q
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py -q
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py -q
.venv/bin/ruff check backend/app/schemas/multimodal_chat.py backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py backend/app/services/runtimes/openai_api_runtime.py tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py
DATABASE_URL=sqlite:////tmp/modelforge_alembic_heads2_$RANDOM.db .venv/bin/alembic -c alembic.ini heads
docker run --rm -d --name mf-alembic-multimodal-20914c -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=modelforge -p 55441:5432 postgres:16-alpine
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55441/modelforge .venv/bin/alembic -c alembic.ini upgrade head
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55441/modelforge .venv/bin/alembic -c alembic.ini current
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55441/modelforge .venv/bin/alembic -c alembic.ini upgrade head
docker stop mf-alembic-multimodal-20914c
.venv/bin/ruff check backend/alembic/versions/0003_model_runtime.py backend/alembic/versions/0004_agent_and_runtime_columns.py backend/alembic/versions/0009_multimodal_chat_foundation.py backend/alembic/versions/0010_merge_video_and_multimodal_heads.py backend/app/api/attachments.py backend/app/api/chat.py backend/app/schemas/multimodal_chat.py backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py backend/app/services/runtimes/openai_api_runtime.py client/pyside6/api_client/client.py tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py -q
.venv/bin/python -m pytest tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/api/attachments.py backend/app/services/chat_turn_service.py backend/app/api/chat.py client/pyside6/api_client/client.py client/pyside6/pages/chat_page.py tests/test_multimodal_sqlite_migration.py tests/test_multimodal_chat_foundation.py tests/test_desktop_model_runtime_pages.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts -q
.venv/bin/ruff check backend/app/services/chat_turn_service.py backend/app/api/chat.py client/pyside6/pages/chat_page.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_chat_cursor.py tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts -q
.venv/bin/ruff check client/pyside6/pages/chat_page.py tests/test_chat_cursor.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_office_ooxml_upload_exposes_safe_text_preview_and_can_preflight -q
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py tests/test_chat_cursor.py tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py backend/app/api/chat.py client/pyside6/pages/chat_page.py tests/test_multimodal_chat_foundation.py tests/test_chat_cursor.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_chat_turn_accepts_text_file_parts_and_replays_events -q
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py tests/test_chat_cursor.py tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py backend/app/api/chat.py backend/app/services/artifact_service.py backend/app/api/artifacts.py client/pyside6/api_client/client.py client/pyside6/pages/chat_page.py tests/test_multimodal_chat_foundation.py tests/test_chat_cursor.py
.venv/bin/python -m pytest tests/test_multimodal_sqlite_migration.py::test_chat_turn_startup_reconcile_settles_active_turns -q
.venv/bin/ruff check backend/app/services/chat_turn_service.py backend/app/services/recovery_service.py tests/test_multimodal_sqlite_migration.py
.venv/bin/python -m pytest tests/test_chat_cursor.py -q
.venv/bin/ruff check client/pyside6/pages/chat_page.py tests/test_chat_cursor.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_pdf_upload_exposes_basic_text_preview_and_can_preflight -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_pdf_upload_exposes_basic_text_preview_and_can_preflight tests/test_multimodal_chat_foundation.py::test_pdf_page_selection_validates_detected_page_range tests/test_multimodal_chat_foundation.py::test_pdf_without_extractable_text_requires_ocr_before_preflight -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_video_upload_exposes_metadata_and_video_part_is_blocked -q
.venv/bin/ruff check backend/app/services/attachment_service.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_wav_upload_exposes_metadata_but_requires_audio_processing tests/test_multimodal_chat_foundation.py::test_office_ooxml_upload_exposes_safe_text_preview_and_can_preflight tests/test_multimodal_chat_foundation.py::test_pdf_upload_exposes_basic_text_preview_and_can_preflight tests/test_multimodal_chat_foundation.py::test_pdf_page_selection_validates_detected_page_range tests/test_multimodal_chat_foundation.py::test_pdf_without_extractable_text_requires_ocr_before_preflight tests/test_multimodal_chat_foundation.py::test_video_upload_exposes_metadata_and_video_part_is_blocked -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_sandbox_provider.py -q
.venv/bin/ruff check backend/app/services/sandbox_provider.py backend/app/api/sandbox.py backend/app/main.py tests/test_sandbox_provider.py
.venv/bin/python -m pytest tests/test_multimodal_sqlite_migration.py::test_chat_turn_startup_reconcile_settles_active_turns tests/test_chat_cursor.py tests/test_multimodal_chat_foundation.py::test_pdf_upload_exposes_basic_text_preview_and_can_preflight tests/test_sandbox_provider.py -q
.venv/bin/ruff check backend/app/services/chat_turn_service.py backend/app/services/recovery_service.py backend/app/services/attachment_service.py backend/app/services/sandbox_provider.py backend/app/api/sandbox.py backend/app/main.py client/pyside6/pages/chat_page.py tests/test_multimodal_sqlite_migration.py tests/test_chat_cursor.py tests/test_multimodal_chat_foundation.py tests/test_sandbox_provider.py
.venv/bin/python -m pytest tests/test_chat_cursor.py::test_chat_page_turn_payload_uses_agent_mode_for_text_only_message tests/test_multimodal_chat_foundation.py::test_agent_mode_preflight_is_disabled_until_sandbox_execution_exists -q
.venv/bin/ruff check client/pyside6/pages/chat_page.py client/pyside6/api_client/client.py tests/test_chat_cursor.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_preflight_context_estimate_counts_selected_file_text tests/test_chat_cursor.py::test_chat_page_appends_context_estimate_summary -q
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_chat_turn_context_exclusions_remove_messages_and_attachment_sources tests/test_multimodal_chat_foundation.py::test_chat_turn_rejects_current_attachment_when_explicitly_excluded -q
.venv/bin/ruff check backend/app/schemas/multimodal_chat.py backend/app/services/chat_turn_service.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_session_message_search_and_pin_are_scoped_to_session tests/test_multimodal_sqlite_migration.py::test_sqlite_multimodal_migration_updates_legacy_messages_table tests/test_chat_cursor.py::test_chat_page_message_search_results_can_toggle_pin -q
.venv/bin/ruff check backend/app/models/records.py backend/app/core/database.py backend/app/services/session_service.py backend/app/api/sessions.py backend/alembic/versions/0011_chat_message_workflow.py client/pyside6/api_client/client.py client/pyside6/pages/chat_page.py tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_chat_cursor.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py::test_session_export_storage_usage_and_deleted_attachment_cleanup -q
.venv/bin/ruff check backend/app/services/session_service.py backend/app/api/sessions.py backend/app/api/attachments.py client/pyside6/api_client/client.py tests/test_multimodal_chat_foundation.py
.venv/bin/python -m pytest tests/test_sandbox_provider.py -q
.venv/bin/ruff check backend/app/services/sandbox_provider.py backend/app/api/sandbox.py tests/test_sandbox_provider.py
.venv/bin/python -m pytest tests/test_sandbox_provider.py::test_sandbox_execute_tool_is_policy_gated -q
.venv/bin/ruff check backend/app/services/agent_tools.py backend/app/runtime/tools/builtin.py tests/test_sandbox_provider.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py tests/test_chat_cursor.py tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts tests/test_sandbox_provider.py -q
.venv/bin/ruff check backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py backend/app/services/recovery_service.py backend/app/services/artifact_service.py backend/app/services/sandbox_provider.py backend/app/api/chat.py backend/app/api/artifacts.py backend/app/api/sandbox.py backend/app/main.py client/pyside6/api_client/client.py client/pyside6/pages/chat_page.py tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_chat_cursor.py tests/test_sandbox_provider.py
.venv/bin/python -m pytest tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_openai_api_runtime.py tests/test_chat_model_registry.py tests/test_chat_cursor.py tests/test_desktop_model_runtime_pages.py::test_chat_page_maps_attachment_mime_types_to_structured_parts tests/test_sandbox_provider.py -q
.venv/bin/ruff check backend/app/schemas/multimodal_chat.py backend/app/models/records.py backend/app/core/database.py backend/app/services/attachment_service.py backend/app/services/chat_turn_service.py backend/app/services/session_service.py backend/app/services/recovery_service.py backend/app/services/artifact_service.py backend/app/services/sandbox_provider.py backend/app/api/chat.py backend/app/api/attachments.py backend/app/api/artifacts.py backend/app/api/sessions.py backend/app/api/sandbox.py backend/app/main.py backend/alembic/versions/0011_chat_message_workflow.py client/pyside6/api_client/client.py client/pyside6/pages/chat_page.py tests/test_multimodal_chat_foundation.py tests/test_multimodal_sqlite_migration.py tests/test_chat_cursor.py tests/test_sandbox_provider.py
DATABASE_URL=sqlite:////tmp/modelforge_alembic_heads_m4_$RANDOM.db .venv/bin/alembic -c alembic.ini heads
DATABASE_URL=sqlite:////tmp/modelforge_alembic_upgrade_m4_$RANDOM.db .venv/bin/alembic -c alembic.ini upgrade head
```

Observed result:

- Python compile checks passed.
- `tests/test_multimodal_chat_foundation.py`: 7 passed.
- `tests/test_multimodal_sqlite_migration.py`: 2 passed.
- `tests/test_chat_model_registry.py`: 5 passed.
- `tests/test_openai_api_runtime.py`: 72 passed.
- Combined targeted run including SQLite migration: 85 passed in 4.37s.
- Final combined targeted run including SQLite migration and storage reconciliation: 86 passed in 4.90s.
- Lifecycle/retry targeted run after reference-summary, cleanup, and retry changes: 10 passed in 4.49s.
- Desktop MIME-to-part mapping test: 1 passed in 0.51s.
- Background turn lifecycle targeted run after async dispatch/cancel changes: 89 passed in 4.64s.
- Desktop drag/paste attachment-path and MIME mapping targeted run: 5 passed in 0.27s.
- Office OOXML preview targeted test: 1 passed in 3.08s.
- M0-M3 focused regression after background, desktop, and Office slices: 94 passed in 4.78s.
- Artifact versioning targeted test through structured chat artifact flow: 1 passed in 2.96s.
- M0-M4 focused regression after artifact versioning: 94 passed in 5.29s.
- Chat turn startup reconciliation targeted test: 1 passed in 0.41s.
- Desktop structured-turn event watermark tests: 5 passed in 0.25s.
- Desktop artifact list/reference tests: 6 passed in 0.17s.
- PDF basic text preview targeted test: 1 passed in 3.04s.
- PDF page selection and OCR-required targeted tests: 3 passed in 3.30s.
- Video metadata/frame extraction targeted test: 1 passed in 3.15s.
- M3 document/audio/video focused regression: 6 passed in 3.52s.
- Sandbox provider diagnostics tests: 2 passed in 2.97s.
- Combined targeted run for startup reconciliation, desktop event/artifact flows, PDF preview, and sandbox diagnostics: 10 passed in 3.46s.
- Agent mode safety preflight tests: 2 passed in 3.07s.
- Context estimate backend/desktop targeted tests: 2 passed in 3.15s.
- Context exclusion backend targeted tests: 2 passed in 2.29s.
- Message search/pin backend, SQLite migration, and desktop targeted tests: 3 passed in 2.63s.
- Session export/storage/cleanup targeted test: 1 passed in 2.47s.
- Sandbox guarded Docker execution contract tests: 4 passed in 2.71s.
- Sandbox tool Policy gate targeted test: 1 passed in 3.13s.
- M0-M4 focused regression after context, message workflow, export/storage changes: 111 passed in 7.18s.
- Alembic heads after message workflow migration: `0011_chat_message_workflow (head)`; empty SQLite `upgrade head` passed.
- Final focused multimodal/desktop/runtime/sandbox regression: 102 passed in 6.57s.
- Ruff targeted check passed for changed multimodal runtime/service/test files and Alembic revisions.
- Ruff targeted check passed for the new lifecycle, retry, and desktop structured-send changes.
- Ruff targeted check passed for background turn lifecycle changes.
- Ruff targeted check passed for desktop drag/paste and preview changes.
- Ruff targeted check passed for Office preview changes.
- Ruff targeted check passed for artifact versioning changes.
- Ruff targeted check passed for chat turn startup reconciliation changes.
- Ruff targeted check passed for desktop structured-turn event watermark changes.
- Ruff targeted check passed for desktop artifact list/reference changes.
- Ruff targeted check passed for PDF basic text preview changes.
- Ruff targeted check passed for video frame extraction changes.
- Ruff targeted check passed for sandbox diagnostics changes.
- Ruff targeted check passed for Agent mode safety preflight changes.
- Final focused Ruff check passed for changed multimodal, desktop, artifact, sandbox, and recovery files.
- `alembic heads`: `0010_merge_heads (head)`.
- PostgreSQL Alembic `upgrade head`: passed on temporary `postgres:16-alpine`; `alembic current` returned `0010_merge_heads (head) (mergepoint)`; repeated `upgrade head` exited 0.

Residual limitations:

- Native image serialization is implemented only for user-configured remote OpenAI-compatible providers; local registry/legacy text runtimes still reject image parts before execution.
- PDF upload is accepted for managed storage and simple text PDFs can be extracted by the built-in previewer, but page-range previews, complex font/encoding handling, scanned document detection beyond empty extraction, and OCR are not implemented in this slice.
- DOCX/XLSX support is currently a bounded text-preview extractor, not a full Office renderer or formula evaluator.
- Audio/video uploads have metadata support and video uploads produce a first-frame derivative when ffmpeg is available, but ASR, multi-frame sampling, native audio/video model input, media generation, sandbox execution, and chat Agent delegation remain pending.
- Sandbox diagnostics are present, but sandbox execution is deliberately disabled until a real isolated provider, policy binding, output import, and escape/resource tests are implemented.
- Agent mode has a visible desktop entry point and backend refusal contract, but it is not yet bound to existing Run records and cannot execute tools until M5 sandbox execution is complete.
- Structured turn execution now runs after persistence in a FastAPI background task, but it is still in-process rather than a durable cross-restart queue. Startup reconciliation settles orphaned turns after a restart; external provider cancellation and durable re-dispatch remain pending.
- Retry currently creates a new attempt and, when artifact output is requested, a separate text artifact for that attempt. Versioned continuation semantics remain in M4.
- Artifact versioning now exists for explicit text updates, and the desktop Chat page can reference the latest text artifact version back into a new message. Rich ArtifactPanel behavior, version comparison/editing, and non-text version creation remain pending.
- Chat page now performs preflight before structured create, supports drag/drop plus paste-to-attachment for local files/images, and follows turn event watermarks after submit, but durable draft restore, rich message-block rendering, real SSE long-poll subscription, and real media preview widgets remain pending.
- Alembic upgrade has manual PostgreSQL smoke evidence; a persistent CI test/job still needs to be added if this is required as an automated gate.
