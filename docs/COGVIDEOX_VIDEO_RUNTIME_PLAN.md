# CogVideoX-2B Local Video Runtime Development Plan

**Document status:** Implementation-ready ExecPlan; plan only.

**Repository baseline:** `755edcd944c7e5904892cf8dc606e549ccd35257` (`master`).

**Research date:** 2026-09-11.

**Scope invariant:** This plan does not authorize model downloads, dependency installation, database migration, inference, application-code changes, release operations, or external publication. Implementation begins only after this plan is accepted.

## Evidence Labels

Every material conclusion uses one of these labels:

- **CONFIRMED:** Directly established from the baseline repository or an authoritative upstream source.
- **INFERRED:** Recommended from confirmed facts, but not yet implemented or validated in ModelForge.
- **UNKNOWN:** Available evidence is insufficient for a reliable conclusion.
- **NEEDS BENCHMARK:** Must be measured on the target Mac mini M4 24GB under the frozen benchmark procedure in section 24.

## 1. Purpose

Define an executable development plan for adding a first-class, local text-to-video capability to ModelForge, initially using `zai-org/CogVideoX-2b` through PyTorch, Diffusers, and Apple Metal Performance Shaders (MPS).

The target product is not a standalone demo. It is a managed ModelForge capability with model inventory, readiness, runtime lifecycle, persistent jobs, authenticated LAN API access, desktop controls, task visibility, cancellation, recovery, output retention, tests, packaging, and benchmark evidence.

## 2. Current ModelForge Architecture

**CONFIRMED:** The baseline has these major layers:

| Layer | Current responsibility | Relevant locations |
|---|---|---|
| FastAPI application | Lifespan, middleware, exception mapping, router composition | `backend/app/main.py` |
| Control-plane API | Models, providers, runtime, tasks, chat, agents, plugins, training | `backend/app/api/` |
| OpenAI-compatible API | `/v1/chat/completions`, `/v1/models` | `backend/app/api/openai_api.py` |
| Chat inference runtimes | Ollama, local Transformers/GGUF, remote OpenAI-compatible | `backend/app/services/runtime.py`, `runtime_registry.py`, `ollama_runtime.py`, `services/runtimes/` |
| Agent Runtime | Runs, tools, events, cancellation, scheduling, policies, plugins | `backend/app/runtime/` |
| Model management | Inventory, scan/install/download/delete, provider readiness | `backend/app/api/models.py`, `backend/app/services/model_manager.py`, `downloader.py`, `model_readiness_service.py` |
| Task infrastructure | Persistent tasks, transitions, events, outbox, SSE, retry monitor | `backend/app/api/tasks.py`, `backend/app/services/task_service.py`, `task_execution.py`, `task_realtime.py` |
| Persistence | SQLAlchemy records; SQLite bootstrap/ledger and PostgreSQL Alembic | `backend/app/models/records.py`, `backend/app/core/database.py`, `backend/alembic/` |
| Desktop client | PySide6 pages, API client, readiness store, task stream and task center | `client/pyside6/` |

**CONFIRMED:** `main.py` initializes the database, task outbox publisher, retry monitor, chat runtime, legacy agent engine, plugin manager, and Agent Runtime. Heavy model imports are currently deferred by runtime implementations.

**CONFIRMED:** Repository-level `AGENTS.md`, `AGENTS.override.md`, `PLANS.md`, `GOALS.md`, and `PROMPTS.md` are absent at the baseline. Existing plans under `docs/` were reviewed and this document does not replace their control-plane, readiness, release, or observability decisions.

## 3. Current Runtime Architecture

There are two systems named “runtime,” and they must not be conflated.

### 3.1 Chat model runtime

**CONFIRMED:** `services.runtime.RuntimeEngine` requires:

```python
async def load(model_name: str, **kwargs) -> dict
async def chat(model_name: str, messages: list, **kwargs) -> dict
async def stop(model_name: str) -> dict
```

**CONFIRMED:** `RuntimeRegistry` lazily creates `OllamaRuntime`, `LocalRuntime`, or `OpenAIRuntime`. The registry defaults to Ollama, has a small instance cache, and its convenience methods delegate without a capability parameter. `LocalRuntime` covers both local Transformers and GGUF paths.

**INFERRED:** Adding `CogVideoXRuntime` as another `RuntimeEngine` subclass would force a video generator to expose a meaningless `chat()` method and would preserve a registry that cannot safely route by media capability. The existing interface should remain compatible for chat while a capability-oriented layer is introduced beside it.

### 3.2 Agent Runtime

**CONFIRMED:** `backend/app/runtime/` owns Agent Run execution, tool dispatch, context, memory, policy, cancellation, event publication, metrics, schedules, MCP adapters, and composable plugins. Its model-provider port is chat-oriented.

**INFERRED:** A video generation job is not an Agent Run. It may later be callable by an Agent tool, but its lifecycle and persistent domain state must exist independently.

### 3.3 Target runtime boundary

Introduce a capability registry without breaking the chat contract:

```text
ModelCapabilityRegistry
  chat
    existing RuntimeRegistry adapter
  video_generation
    CogVideoXRuntime
```

The implementation may later retire or generalize `RuntimeRegistry`, but Phase 1 must use adapters and explicit capability lookup rather than a flag day rewrite.

## 4. Current OpenAI-compatible API

**CONFIRMED:** `backend/app/api/openai_api.py` implements authenticated `/v1/chat/completions` and `/v1/models`. It applies request validation, rate limiting, model selection, streaming/non-streaming chat behavior, and OpenAI-style error envelopes. `main.py` maps `/v1/*` Pydantic validation failures to the same envelope and supplies correlation headers.

**CONFIRMED:** The current `/v1/models` result is not a complete capability-aware projection of the managed model inventory; the implementation includes a hard-coded compatibility model entry.

**CONFIRMED:** `/v1/*` currently depends on Bearer authentication. Project API keys exist in the `/api/v2` commercial surface, but they are not automatically accepted by `/v1/*`.

**CONFIRMED:** CORS origins are explicit. Native Flutter clients do not require browser CORS, while Flutter Web does.

**CONFIRMED:** OpenAI documentation available on 2026-09-11 marks the Videos API as deprecated and states that the Sora API will shut down on 2026-09-24. Therefore `/v1/videos` is not treated as a durable external standard.

**Decision:** ModelForge will implement a documented **OpenAI-style compatibility subset**, freeze its own contract version, and record deviations. It will reuse existing `/v1` authentication, error, correlation, and rate-governance utilities rather than create a separate security stack.

## 5. Problem Statement

ModelForge has no media-generation runtime contract, capability-aware model registry, persistent video job, isolated MPS worker, authenticated artifact endpoint, or video desktop workflow. Directly running Diffusers inside a FastAPI handler would block workers, make cancellation unreliable, couple HTTP lifetime to inference, and leave restart recovery undefined.

The implementation must also avoid these category errors:

- Treating CUDA VRAM reports as Apple unified-memory evidence.
- Treating a downloaded checkpoint as a ready runtime.
- Treating `CANCEL_REQUESTED` as proof that inference stopped.
- Treating an Agent Run or generic TaskRecord as the complete video domain model.
- Treating arbitrary `seconds` and `fps` as parameters CogVideoX accepts without frame mapping.
- Treating an absolute output path as an API-safe artifact reference.

## 6. Goals

1. Add a capability-oriented video runtime contract without regressing existing chat runtimes.
2. Support managed local installation and readiness for `zai-org/CogVideoX-2b`.
3. Execute generation outside the FastAPI event loop with MPS exclusivity and bounded concurrency.
4. Persist video-domain state, progress, errors, request identity, runtime metadata, and output metadata.
5. Reuse TaskRecord/Event/Outbox/SSE for task-center projection and realtime updates.
6. Provide authenticated local and LAN-accessible `/v1/videos` endpoints.
7. Add a minimal PySide6 model/runtime workflow and video generation page.
8. Keep ordinary CI independent of model downloads, MPS, and 24GB hardware.
9. Produce reproducible M4 24GB benchmark evidence before declaring support.
10. Preserve an extension path for additional video models without implementing them in v1.

## 7. Non-Goals

- Image-to-video, video-to-video, editing, remixing, upscaling, interpolation, audio, or lip sync.
- CogVideoX-5B, Wan, LTX-Video, or cloud video providers in the first release.
- Multi-GPU, distributed inference, cloud queues, billing, tenancy quotas, or public Internet hosting.
- Arbitrary resolution, frame count, duration, scheduler, or precision passthrough.
- Automatic model download or environment modification without explicit user confirmation.
- Replacing the existing chat RuntimeEngine or Agent Runtime in one migration.
- Guaranteeing M4 24GB support before Phase 0 evidence passes.
- Byte-range streaming optimization in the first slice unless the desktop/Flutter validation shows it is required.

## 8. Requirements

### 8.1 Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | List video-capable models and readiness through model APIs without loading the model. |
| FR-2 | Explicitly install/download CogVideoX assets and optional runtime dependencies with progress and cancellation. |
| FR-3 | Submit a text-to-video request and return a persistent job immediately. |
| FR-4 | Queue jobs with default global video concurrency `1`. |
| FR-5 | Query status after process restart. |
| FR-6 | Cancel queued jobs immediately and running jobs cooperatively, then forcibly after a bounded grace period. |
| FR-7 | Retrieve completed MP4 content only through an authorized endpoint. |
| FR-8 | Display projected progress in the existing task center and the video page. |
| FR-9 | Start/stop/unload the video runtime without affecting chat runtimes. |
| FR-10 | Reject unsupported combinations before queue admission. |

### 8.2 Non-functional requirements

- No synchronous Diffusers execution on the ASGI event loop.
- No model weights, prompts, absolute paths, tokens, or raw upstream exceptions in logs or public errors.
- Atomic output publication: temporary file first, validate, then rename and mark complete.
- Idempotent submission per authenticated principal and `Idempotency-Key`.
- Database state and output retention remain understandable after crash/restart.
- Optional video dependencies do not burden base, GUI-only, or non-video installations.
- All always-on tests use fakes or small fixtures and perform no model download.

## 9. CogVideoX-2B Technical Research

### 9.1 Confirmed upstream facts

**CONFIRMED:** The official model ID is `zai-org/CogVideoX-2b`. Diffusers exposes `CogVideoXPipeline`. The published pipeline configuration includes a tokenizer, T5 text encoder, CogVideoX transformer, 3D VAE, and scheduler.

**CONFIRMED:** Official examples use half precision, model CPU offload in CUDA-oriented examples, VAE slicing, VAE tiling, and `export_to_video`. A commonly documented workload is 49 frames at 8 FPS and 720x480 with around 50 inference steps. Those values are a supported example, not a universal performance promise.

**CONFIRMED:** Diffusers pipelines support step-end callbacks. A runtime can use the callback boundary to update progress and inspect a cancellation token. Whether every CogVideoX/PyTorch execution segment responds promptly still requires measurement.

### 9.2 Parameter policy

The API must expose a small validated profile, then map it to runtime-native parameters:

| Public input | v1 policy |
|---|---|
| `model` | Only registered, ready video-generation model IDs. |
| `prompt` | Required, bounded UTF-8 text; never logged verbatim. |
| `seconds` | Compatibility input mapped to an approved frame profile; not passed directly. |
| `fps` | Approved output encoding rate; combined with frames to define displayed duration. |
| `size` | Initially one validated model profile, expected `720x480`; orientation variants require spike evidence. |
| `num_inference_steps` | Bounded server policy with a conservative default; administrators may narrow it. |
| `guidance_scale` | Omit from public v1 unless Phase 0 proves a stable supported range. |
| `seed` | Optional signed 64-bit-compatible integer, persisted for reproducibility. |

**INFERRED:** Use explicit generation profiles such as `cogvideox2b-t2v-49f-720x480` rather than promising arbitrary duration. Response metadata should return the resolved `frames`, `fps`, `size`, `steps`, and seed.

### 9.3 Size and memory interpretation

**CONFIRMED:** “2B” describes parameter scale, not total runtime memory. Weight files, text encoder, VAE, transformer, scheduler state, latent tensors, decoded frames, Python/PyTorch overhead, Metal allocations, and export buffers contribute separately.

**UNKNOWN:** The exact disk footprint depends on the pinned repository revision, selected file format, cache layout, and whether duplicate snapshots exist.

**NEEDS BENCHMARK:** Peak unified memory for the frozen M4 workload. Do not substitute a CUDA VRAM number.

## 10. Apple Silicon / MPS Analysis

### 10.1 What is known

**CONFIRMED:** PyTorch exposes the `mps` device on supported Apple Silicon/macOS systems. `torch.backends.mps.is_available()` and `is_built()` distinguish build and host availability.

**CONFIRMED:** `PYTORCH_ENABLE_MPS_FALLBACK=1` allows unsupported MPS operations to fall back to CPU. It is an opt-in compatibility mechanism, not proof of complete support or good performance.

**CONFIRMED:** Diffusers' Apple Silicon guidance recommends memory-conscious attention slicing for some pipelines and warns that MPS behavior differs by PyTorch/macOS version. Public CogVideoX issue reports include severe MPS allocation failures on high-memory Apple Silicon, so “large unified memory” alone is not sufficient evidence.

### 10.2 Decisions for the spike

- Default candidate precision: FP16, because it matches official examples and reduces storage/activation pressure. This remains **NEEDS BENCHMARK** for correctness and stability on M4.
- BF16: **UNKNOWN** for the selected M4/PyTorch/Diffusers matrix; test only if the pipeline declares support and FP16 fails.
- FP32: diagnostic fallback only; likely impractical for the target memory envelope and **NEEDS BENCHMARK** if attempted.
- VAE slicing and tiling: enable in the first candidate profile, then benchmark separately to establish whether either can be relaxed.
- CPU offload: do not assume CUDA-oriented offload utilities improve MPS. Test support, allocation behavior, and wall time. If unsupported or harmful, omit it from MPS production configuration.
- MPS fallback: expose as a runtime configuration/readiness fact, default off during compatibility diagnosis, then test on with fallback telemetry. Never mutate the process environment after torch import.

### 10.3 Phase 0 support gate

The target is declared `SUPPORTED_EXPERIMENTAL` only if the frozen environment can:

1. Load from a local snapshot without network access.
2. Generate a structurally valid, non-black, non-NaN 49-frame output at the approved profile.
3. Repeat generation in the same worker without unbounded memory growth.
4. Cancel at a measured callback boundary and terminate forcibly within the configured timeout.
5. Report peak process RSS and best-available MPS allocation metrics.

Otherwise readiness must be `UNAVAILABLE` with a stable reason, and implementation may continue with mock/runtime foundations without claiming usable M4 support.

## 11. Proposed Architecture

```text
Flutter / PySide6 / API client
            |
            v
       /v1/videos
            |
     VideoGenerationService
      |        |         |
      |        |         +--> artifact authorization / retention
      |        +------------> VideoJobRepository
      +---------------------> VideoQueueCoordinator
                                  |
                          isolated worker process
                                  |
                      VideoGenerationRuntime protocol
                                  |
                          CogVideoXRuntime
                                  |
                     Diffusers + PyTorch MPS

VideoJob --projection--> TaskRecord / TaskEvent / TaskOutbox --SSE--> TaskStore
```

### Ownership rules

- `VideoJob` is the video lifecycle source of truth.
- `TaskRecord` is the cross-product task-center projection, not a second writable lifecycle authority.
- `VideoQueueCoordinator` owns admission order and the single active worker lease.
- Worker process owns loaded pipeline state and active inference.
- Runtime adapter owns framework calls, parameter mapping, progress callbacks, and media export.
- API service owns authentication scope, idempotency, schema validation, and response mapping.
- Artifact service owns paths, authorization, validation, retention, and deletion.

## 12. Runtime Design

### 12.1 New protocol

Planned file: `backend/app/services/video_runtime.py`.

```python
class VideoGenerationRuntime(Protocol):
    runtime_name: str

    async def probe(self, model: VideoModelSpec) -> VideoRuntimeProbe: ...
    async def load(self, model: VideoModelSpec) -> RuntimeLoadResult: ...
    async def generate(
        self,
        request: ResolvedVideoGenerationRequest,
        *,
        progress: ProgressCallback,
        cancellation: CancellationToken,
        output_path: Path,
    ) -> VideoGenerationResult: ...
    async def unload(self, model_id: str) -> RuntimeStopResult: ...
    async def shutdown(self) -> None: ...
```

The API shapes above are design targets; exact dataclass placement is finalized in Phase 1.

### 12.2 Capability registration

Planned file: `backend/app/services/model_capability_registry.py`.

- Register providers by stable capability and runtime name.
- Resolve `(capability, model.runtime_name)` explicitly.
- Lazy-import optional Diffusers/PyTorch integration.
- Reject duplicate registrations and unknown capability/runtime pairs.
- Report runtime metadata without importing or loading weights.
- Adapt existing `RuntimeRegistry` under capability `chat` without changing chat callers in Phase 1.

### 12.3 Isolation and lifecycle

**Decision:** Run CogVideoX in a dedicated child process managed by a backend coordinator, not in a thread and not directly in Uvicorn.

Reasons:

- PyTorch/Metal allocation cleanup is more reliable at process exit.
- Forced cancellation has a bounded mechanism.
- A worker crash does not crash the API process.
- Optional heavy imports stay outside ordinary API startup.
- One active process naturally enforces the initial MPS concurrency limit.

Use a structured local IPC protocol with versioned messages: `READY`, `LOAD`, `GENERATE`, `PROGRESS`, `RESULT`, `ERROR`, `CANCEL`, `UNLOAD`, `SHUTDOWN`, and `HEARTBEAT`. Do not parse worker stdout as the protocol; stdout/stderr are diagnostic streams with redaction.

## 13. Video Job Design

### 13.1 A/B/C comparison

| Option | Advantages | Problems | Decision |
|---|---|---|---|
| A. Existing task only | Maximum UI/SSE reuse; fewer tables | Generic payload cannot safely express request/output/runtime recovery invariants; lifecycle can be mutated by unrelated task code | Reject |
| B. Standalone VideoJob | Clear domain ownership | Duplicates event, SSE, task center, cancellation visibility, retry plumbing | Reject |
| C. VideoJob plus task projection | Domain truth plus infrastructure reuse | Requires transactional projection rules and reconciliation | **Recommend** |

### 13.2 State machine

Persistent states:

```text
QUEUED -> RUNNING -> COMPLETED
   |         |  \-> FAILED
   |         |  \-> CANCEL_REQUESTED -> CANCELLED
   |         \----> INTERRUPTED
   \--------------> CANCELLED

INTERRUPTED -> QUEUED       only after explicit recovery policy approves
INTERRUPTED -> FAILED       when recovery is unsafe or retry budget is exhausted
```

`PAUSED` is excluded from v1 because CogVideoX generation cannot be reliably serialized and resumed mid-denoising. `RECOVERING` is represented as an event/recovery attempt, not a durable user-facing state, unless implementation evidence shows the transition needs a separately queryable state.

### 13.3 Progress

- Persist coarse progress only: accepted, model loading, inference step N/total, VAE decode, encoding, publishing.
- Throttle database/outbox progress updates by time and percentage to avoid one write per diffusion step.
- Allow high-frequency progress over process-local IPC but persist at most the configured rate.
- Never estimate remaining seconds until benchmark-derived behavior is stable; show phase and percentage.

### 13.4 Restart recovery

On startup, reconcile non-terminal jobs before accepting new work:

- `QUEUED`: retain queue order and re-enqueue.
- `RUNNING` or `CANCEL_REQUESTED` with no live matching worker lease: mark `INTERRUPTED`.
- Valid completed artifact with uncommitted final state: reconcile only through an explicit checksum/container validation path.
- Partial temporary output: quarantine/delete according to retention policy; never expose it as content.
- Automatic retry: disabled by default for interrupted generation because cost and determinism are material. User may resubmit with the same resolved parameters and seed.

## 14. API Design

### 14.1 Contract scope

ModelForge contract identifier: `modelforge.video.v1`. It is OpenAI-style, not a claim of full OpenAI compatibility.

### 14.2 Submit

`POST /v1/videos`

Headers:

- `Authorization: Bearer ...` in the first vertical slice.
- `Idempotency-Key: ...` required for LAN/mobile clients and strongly recommended for all clients.
- Project API key support is a separate acceptance item in Phase 4, implemented by reusing the established `/api/v2` principal/authentication machinery rather than inventing another key table.

Request:

```json
{
  "model": "cogvideox-2b",
  "prompt": "A futuristic submarine cruising through the deep ocean",
  "seconds": 6,
  "fps": 8,
  "size": "720x480",
  "num_inference_steps": 30,
  "seed": 12345
}
```

Accepted response (`202`):

```json
{
  "id": "video_01...",
  "object": "video",
  "created_at": 1789056000,
  "status": "queued",
  "model": "cogvideox-2b",
  "progress": 0,
  "resolved": {
    "frames": 49,
    "fps": 8,
    "size": "720x480",
    "num_inference_steps": 30,
    "seed": 12345
  },
  "error": null
}
```

The response must not return the prompt by default. A user-scoped detail endpoint may return a redacted prompt summary only if product requirements later justify it.

### 14.3 Query

`GET /v1/videos/{video_id}` returns `queued`, `processing`, `completed`, `failed`, or `cancelled`. Internal `CANCEL_REQUESTED` and `INTERRUPTED` map to stable public states plus `status_detail.code` so clients can distinguish “cancelling” or “interrupted” without expanding the top-level compatibility enum.

### 14.4 Content

`GET /v1/videos/{video_id}/content`

- Requires the same principal scope as job access.
- Returns `404` for unknown or unauthorized IDs to avoid existence disclosure.
- Returns `409 VIDEO_NOT_COMPLETE` before completion.
- Uses `FileResponse` or equivalent streaming response from a server-resolved path.
- Sets `Content-Type: video/mp4`, a safe filename, `Content-Length`, `ETag`, and `Cache-Control: private`.
- Never accepts a path parameter and never redirects to a local filesystem URL.
- Byte ranges are evaluated in Phase 4; support them if Flutter/desktop playback requires seeking.

### 14.5 Cancellation

Add `POST /v1/videos/{video_id}/cancel`. It is clearer for LAN clients than exposing the internal Task ID. Internally it calls the same cancellation service used by `/api/v1/tasks/{task_id}/cancel` and is idempotent.

### 14.6 Model listing

Extend `/v1/models` so each managed model can declare non-breaking ModelForge metadata:

```json
{
  "id": "cogvideox-2b",
  "object": "model",
  "owned_by": "local",
  "capabilities": ["video_generation"],
  "readiness": "ready"
}
```

If strict clients reject extensions, expose extensions under a single `modelforge` object and keep standard fields unchanged.

### 14.7 Error map

All `/v1` errors retain `{error: {message, type, code, param}, correlation_id}`. Planned codes include:

`VIDEO_MODEL_NOT_FOUND`, `VIDEO_MODEL_NOT_READY`, `VIDEO_PROFILE_UNSUPPORTED`, `VIDEO_QUEUE_FULL`, `VIDEO_RUNTIME_UNAVAILABLE`, `VIDEO_JOB_NOT_FOUND`, `VIDEO_NOT_COMPLETE`, `VIDEO_CANCEL_CONFLICT`, `VIDEO_GENERATION_FAILED`, `VIDEO_ARTIFACT_MISSING`, and `IDEMPOTENCY_CONFLICT`.

## 15. Model Management

### 15.1 Model metadata

Extend managed model records or add a normalized capability table so a model can declare:

- stable public model ID and upstream repository/revision;
- capabilities (`chat`, `video_generation`, future `image_generation`);
- runtime name and model family;
- local snapshot root and manifest/checksum metadata;
- precision/profile policy;
- install state and runtime readiness state;
- platform constraints and last probe summary.

Do not overload `provider` or model filename to infer capability.

### 15.2 Installation workflow

```text
User clicks Install
  -> terms/disk/network confirmation
  -> create installation task
  -> download pinned snapshot to staging
  -> verify expected files/checksums/size policy
  -> atomic publish into managed model store
  -> dependency and MPS probe
  -> readiness update
```

**CONFIRMED:** The existing downloader persists records but its in-process asynchronous execution does not automatically resume after restart. Video installation must either harden that executor or add a resumable downloader worker before it claims restart recovery.

### 15.3 Delete versus uninstall

- **Remove record:** remove only an inventory reference when assets are externally managed.
- **Uninstall managed assets:** delete ModelForge-owned snapshot/cache after confirmation and after proving no active/queued job references it.
- **Unload runtime:** release worker/model memory without deleting files.

The existing model delete behavior does not remove model files, so UI/API wording must not imply otherwise.

## 16. Model Readiness

### 16.1 Two-level readiness

The current aggregate `READY/DEGRADED/SETUP_REQUIRED` snapshot remains useful for “can the user do anything?” but is insufficient for video installation and runtime probes.

Add resource-level states:

```text
NOT_INSTALLED
DOWNLOADING
INSTALLING
PROBING
READY
UNAVAILABLE
ERROR
```

Keep separate facts:

- `install_state`
- `runtime_state` (`STOPPED`, `STARTING`, `READY`, `BUSY`, `STOPPING`, `ERROR`)
- `capability_readiness`
- `platform_probe`
- `last_error_code`

### 16.2 Readiness checks

`READY` requires all of:

1. Complete pinned local snapshot and manifest.
2. Importable pinned optional dependencies.
3. Supported Python/PyTorch/Diffusers/macOS matrix.
4. `mps` built and available for the MPS profile.
5. Sufficient configured free disk threshold.
6. Runtime probe succeeds without loading full weights unless the probe explicitly requests a load test.

Readiness reads must not trigger downloads, network calls, full model loads, or inference.

## 17. PySide6 UI Design

### 17.1 Model page

Extend the existing model page and readiness store instead of creating a parallel manager. A CogVideoX row/detail view shows:

- `Video generation` capability;
- upstream model and pinned revision;
- disk/install state;
- runtime backend `MPS` and probe result;
- `Install`, `Cancel install`, `Start`, `Stop`, `Uninstall`, and `Open model folder` actions as state permits;
- clear `Experimental on Apple Silicon` labeling until the support gate passes.

Actions that download, delete, or start resource-intensive work require explicit confirmation. UI network and task polling continue through existing async API worker patterns, never the GUI thread.

### 17.2 Video generation page

Add a work-focused page with:

- prompt editor;
- ready video model selector;
- duration/profile and FPS controls restricted to supported values;
- bounded inference steps and optional seed;
- Generate and Cancel commands;
- current phase/progress and correlation ID on failure;
- completed video preview using the safest supported Qt multimedia path;
- Save As and Open Folder actions against authorized downloaded/local artifacts.

The first version has no prompt gallery, timeline editor, batch generation, advanced scheduler tuning, or nested card layout.

### 17.3 Task center

Reuse `TaskStore`, task SSE, and task center. Video projection rows show job phase, model, progress, created time, and cancellation state. Prompt text and absolute output paths are excluded.

## 18. Plugin Architecture Decision

### 18.1 Alternatives

| Form | Maintainability | Install/dependency isolation | Future models | Decision |
|---|---|---|---|---|
| Built-in chat RuntimeEngine | Low; wrong `chat()` contract | Poor | Locks media into chat registry | Reject |
| Current Agent/Tool plugin | Agent discovery works, but media lifecycle does not fit | Plugin process isolation is not established for heavy ML stacks | Useful only as a later caller | Reject for v1 |
| Built-in video runtime adapter | Clear ownership and integrated UX | Optional dependency group plus worker isolation | Capability contract permits more adapters | **Use for v1** |
| Video runtime plus future provider plugin SPI | Best long-term extension | Requires a real runtime-provider packaging/lifecycle contract | Strong | Design extension point, do not implement full SPI in v1 |

### 18.2 Decision

CogVideoX-2B is a first-party, built-in `VideoGenerationRuntime` adapter loaded only when selected. Heavy libraries live in an optional video dependency group and inference runs in a child process. Agent integration, if later added, is a thin tool that submits a normal VideoJob; it does not own inference.

Before third-party Wan/LTX adapters are supported, define a separate runtime-provider SPI covering capabilities, dependency/environment declaration, process boundary, model schema, readiness probes, job parameter schema, and artifact contract. The legacy `RuntimePlugin` skeleton and current composable Agent plugins are not sufficient evidence for that SPI.

## 19. Persistence / Database Changes

### 19.1 `video_jobs`

Planned columns:

| Column | Purpose |
|---|---|
| `id` | Internal primary key |
| `public_id` | Unique opaque `video_...` identifier |
| `user_id` / principal fields | Ownership and authorization scope |
| `task_id` | Unique projection link to TaskRecord |
| `model_id`, `runtime_name`, `profile_id` | Resolved execution target |
| `status`, `status_detail_code`, `progress`, `phase` | Lifecycle |
| `prompt_ciphertext` or protected prompt reference | Optional recovery/audit storage; plaintext is not logged |
| `request_json`, `resolved_request_json` | Versioned, validated non-secret execution parameters |
| `idempotency_key_hash`, `request_hash` | Safe deduplication/conflict detection |
| `seed`, `frames`, `fps`, `width`, `height`, `steps` | Reproducibility/query fields |
| `worker_id`, `lease_expires_at`, `attempt` | Recovery and ownership |
| `output_relpath`, `output_sha256`, `output_bytes`, `media_duration_ms` | Artifact metadata; relative path only |
| `error_code`, `error_summary`, `correlation_id` | Stable diagnostics without raw exception leakage |
| timestamps | queued/started/completed/cancelled/updated |

Use a unique constraint over principal scope plus `idempotency_key_hash`. Store request hashes to detect reuse with a different body.

### 19.2 Additional persistence

- Model capability/install/probe columns or new normalized tables, selected in Phase 1 after migration compatibility review.
- Optional `video_artifacts` table only if multiple outputs/thumbnails are required; keep v1 one-output design in `video_jobs` otherwise.
- Runtime leases may be a table or fields on jobs; prefer the smallest design that supports single-worker recovery.

### 19.3 Migration paths

**CONFIRMED:** Both paths must be updated:

1. SQLite initialization and append-only migration ledger used by local desktop deployments.
2. PostgreSQL Alembic revisions under `backend/alembic/versions/`.

Migration tests must open a representative previous SQLite database and upgrade without deleting model, task, provider, or credential records.

## 20. Error Handling

- Convert known validation/runtime/worker/artifact failures to stable internal enums.
- Public messages are concise, localizable, and omit prompts, paths, stack traces, environment values, and dependency internals.
- Preserve correlation ID across API request, VideoJob, TaskRecord, IPC messages, worker logs, and artifact publication.
- Worker error payload contains a stable code, safe summary, retryability, failed phase, and internal diagnostic reference.
- Capture raw stack traces only in protected backend diagnostics with existing redaction policy.
- Map MPS OOM/resource exhaustion distinctly from unsupported operator, missing dependency, corrupt model, encode failure, and worker crash.
- A generation failure never returns a partial media file.

## 21. Cancellation / Recovery

### 21.1 Cancellation protocol

1. API transaction changes `VideoJob` and projected TaskRecord to `CANCEL_REQUESTED` and emits outbox event.
2. Coordinator signals the worker cancellation token.
3. Diffusers step callback checks the token and aborts through a controlled runtime exception/result.
4. Worker deletes/quarantines temporary output, unloads transient tensors, and responds `CANCELLED`.
5. Coordinator confirms both VideoJob and TaskRecord as `CANCELLED` transactionally.
6. If the worker does not acknowledge within the configured grace period, terminate it, mark the job `CANCELLED` with `forced=true`, and create a fresh worker before subsequent jobs.

Cancellation latency is **NEEDS BENCHMARK**. The UI must say “Cancelling” until executor confirmation.

### 21.2 Recovery safeguards

- Worker heartbeat and lease must use monotonic process time for liveness and database UTC timestamps for persistence.
- Never let two coordinators claim the same job; use a database-supported compare-and-set/lease transaction.
- SQLite desktop mode has one coordinator by configuration. PostgreSQL mode still enforces the lease for future multi-process deployment.
- Output publication is idempotent and uses a job-specific staging directory.
- Cleanup runs as a bounded task with dry-run/report support before deletion.

## 22. Security

### 22.1 Authentication and authorization

- Reuse current Bearer identity for the first `/v1/videos` implementation.
- Add project API key authentication only by adapting the established `/api/v2` principal and scope checks.
- Define video scopes such as `videos:create`, `videos:read`, and `videos:cancel`; default user JWT permissions map internally.
- Job status/content/cancel use owner or authorized project scope and return non-enumerating `404` on denial.

### 22.2 LAN posture

- Binding beyond localhost is an explicit setting with a warning, never an automatic discovery behavior.
- Require authentication on all video routes, including content.
- Document firewall/TLS expectations. Plain HTTP may be acceptable only on a user-trusted LAN in the initial local-server profile; public exposure is out of scope.
- Rate-limit submission, status polling, content downloads, and cancellation separately.
- Bound queue depth and per-principal outstanding jobs to prevent memory/disk exhaustion.

### 22.3 Input, files, and supply chain

- Bound prompt length and JSON sizes before persistence.
- Server generates all directories and filenames; reject traversal and symlink escapes using resolved-path containment checks.
- Pin model repository revision and optional dependency versions; record licenses and provenance.
- Use safe tensor formats where supported and avoid executing repository code (`trust_remote_code=False`) unless a reviewed, pinned exception is approved.
- Validate output container before publishing and serve with safe headers.
- Prompts are sensitive user content. Define retention and deletion explicitly; no telemetry or logs contain prompt text.

## 23. Testing Strategy

### 23.1 Always-on unit tests

- Request schema, profile mapping, frame/duration resolution, seed handling.
- VideoJob transition matrix, illegal transitions, cancellation idempotency.
- Capability/runtime selection and unknown runtime rejection.
- Model install/readiness truth table and no-side-effect readiness reads.
- Error mapping and redaction.
- Artifact path containment, ownership, retention, and missing-file behavior.
- Idempotency replay and body-conflict behavior.
- Queue ordering, single concurrency, leases, restart reconciliation.

### 23.2 API tests

- Authenticated and unauthenticated `POST /v1/videos`.
- Validation errors use the existing OpenAI envelope.
- Submit returns `202`; idempotent replay returns the same job.
- Status mapping for every internal state.
- Content before completion, successful MP4, unauthorized/unknown ID, missing artifact.
- Cancellation for queued, running, completed, failed, and repeated requests.
- `/v1/models` preserves compatibility and advertises capability/readiness.
- Bearer and, when implemented, project-key scope isolation.

### 23.3 Runtime tests

- `FakeVideoRuntime` is deterministic, fast, cancellable, and can inject phase-specific failures.
- Worker IPC contract tests run a fake worker subprocess.
- Real CogVideoX smoke tests are opt-in, require a pre-provisioned pinned local snapshot, and never download implicitly.
- Golden validation checks MP4 parseability, dimensions, frame count, finite pixels, and non-uniform frames; it does not assert subjective visual quality.

### 23.4 Desktop tests

- Domain/API mapping without Qt.
- Offscreen PySide6 state rendering and action enablement.
- Task SSE projection, reconnect, stale update rejection, and cancellation confirmation.
- Generate flow with fake runtime, preview failure recovery, Save As, and Open Folder.
- English, Simplified Chinese, and Japanese localization for new visible strings.

## 24. Benchmark Strategy

### 24.1 Frozen benchmark manifest

Record:

- Mac model, chip, core counts, 24GB unified memory, macOS version, power mode, free disk.
- Python, PyTorch, torchvision if present, Diffusers, Transformers, Accelerate, safetensors, imageio/ffmpeg versions.
- Model repository ID and exact commit revision.
- Environment variables including MPS fallback and watermark limits.
- Runtime profile: FP16, frames, FPS, resolution, steps, scheduler, guidance if used, seed.
- Exact prompt and prompt hash in the benchmark artifact only.
- VAE slicing/tiling and offload configuration.

### 24.2 Required workload

At minimum:

1. Cold worker startup and model load.
2. First generation: fixed prompt, 49 frames, 8 FPS, 720x480, fixed seed, and the approved initial step count.
3. Second same-process generation with identical settings.
4. Cancellation at approximately 25% inference progress.
5. Three sequential generations to detect retained allocation growth.

Test 30 and 50 steps only if both fit the support gate; do not multiply the matrix before basic viability is established.

### 24.3 Metrics

- Worker startup and model load time.
- Time to first progress, denoising time, VAE decode time, encode time, total time.
- Peak process RSS and best-available current/peak MPS allocated and driver memory.
- CPU utilization, GPU/MPS utilization where reliable tooling exists, thermal state, and swap activity.
- Output bytes, duration, dimensions, frames, effective FPS, and checksum.
- Cancellation acknowledgement and process termination latency.
- Memory before/after unload and between repeated jobs.

All numeric performance and memory expectations remain **NEEDS BENCHMARK** until this manifest is published.

## 25. CI / Cross-platform Strategy

| Environment | Always run | Conditional | Expected runtime status |
|---|---|---|---|
| Linux CI | Schemas, state machines, API with fake runtime, IPC fake worker, migrations, artifact security | Optional CPU import smoke with no weights | CogVideoX MPS unavailable with stable reason |
| Windows CI | Same platform-neutral tests; path/security tests | Optional fake worker process smoke | MPS unavailable with stable reason |
| Intel Mac | Platform-neutral tests and probe mapping | No real MPS inference | Unsupported hardware reason |
| Apple Silicon CI | Platform-neutral plus MPS probe tests | Small non-model MPS tensor smoke | Hardware available, model support not implied |
| Dedicated Mac mini M4 24GB | Full opt-in pinned real-runtime smoke and benchmark | Scheduled/manual, serialized | Evidence source for support gate |

Rules:

- Ordinary CI must not download CogVideoX weights.
- Real runtime jobs use explicit markers and fail closed when the snapshot/revision is absent.
- Cache keys include model revision and dependency lock hash; model caches are not uploaded to public artifacts.
- Mock tests remain authoritative for API behavior; hardware tests cover compatibility/performance only.
- Package/import tests verify base ModelForge starts when video extras are absent.

## 26. Development Phases

### Phase 0 - Decision Freeze and MPS Feasibility Spike

**Goal:** Freeze contracts and determine whether M4 24GB can support the initial profile without making unsupported claims.

**Prerequisites:** Accepted plan; dedicated Mac mini M4 24GB; approved disk/network budget; separately approved dependency/model installation.

**Files:** `docs/` spike protocol/evidence; isolated experimental scripts under a new explicitly non-production benchmark area; no production route changes.

**Modules:** PyTorch MPS probe, Diffusers CogVideoX load/generate/export, metrics collector.

**New interfaces:** Draft `VideoModelSpec`, resolved profile, runtime probe/result, cancellation callback semantics.

**Data structures:** Benchmark manifest/result JSON schemas; compatibility matrix.

**Implementation steps:** Pin versions/revision; verify offline reload; test FP16 baseline; measure slicing/tiling; test fallback off/on; test offload only if supported; run repeat/cancel workloads; inspect generated media; record all failures.

**Tests:** Manifest schema; metrics parser; output structural checks; manual visual smoke.

**Acceptance:** Support classification and exact known-good or known-failing matrix are documented; no invented timing/memory number; architecture contracts are frozen.

**Risks:** MPS OOM, unsupported ops, black/NaN frames, excessive runtime, unstable cleanup.

**Rollback:** Remove experimental environment and local snapshot; retain evidence; proceed with mock-only foundation or stop product implementation if viability is unacceptable.

### Phase 1 - Video Runtime Foundation

**Goal:** Add capability-oriented runtime contracts and fake implementation without changing chat behavior.

**Prerequisites:** Phase 0 contract decisions; code-change approval.

**Files:** New `backend/app/services/video_runtime.py`, `model_capability_registry.py`, domain schema module; focused tests; minimal `main.py` lifecycle wiring only when required.

**Modules:** Capability registry, runtime protocol, model/profile resolver, fake runtime.

**New interfaces:** `VideoGenerationRuntime`, `VideoRuntimeProbe`, `ResolvedVideoGenerationRequest`, capability lookup.

**Data structures:** Typed runtime/model/profile/progress/result/error records.

**Implementation steps:** Define immutable schemas; adapt chat registry under `chat`; add explicit video registration; lazy imports; lifecycle shutdown; fake runtime; stable errors.

**Tests:** Registry collisions, capability selection, absent optional dependencies, fake progress/cancel/failure, unchanged chat tests.

**Acceptance:** Base app imports and starts without video extras; chat suite passes unchanged; fake video runtime is usable by services.

**Risks:** Circular imports and premature generalization.

**Rollback:** Remove capability adapter and new modules; existing RuntimeRegistry remains untouched.

### Phase 2 - CogVideoX MPS Runtime and Worker

**Goal:** Implement the pinned first-party adapter and isolated worker using Phase 0's supported configuration.

**Prerequisites:** Phase 0 viability gate passed or explicitly accepted as experimental; Phase 1 contracts stable.

**Files:** New `backend/app/services/runtimes/cogvideox_runtime.py`, video worker/IPC modules, optional dependency definition, worker tests, packaging hooks.

**Modules:** Worker supervisor, IPC, CogVideoX pipeline adapter, MP4 exporter, resource metrics.

**New interfaces:** Versioned worker commands/events and runtime lifecycle methods.

**Data structures:** Worker config, command envelope, progress event, safe error, artifact result.

**Implementation steps:** Add optional extras; lazy import; spawn-safe entrypoint; local-only snapshot loading; precision/device policy; callback cancellation; staging export; heartbeat; graceful and forced shutdown.

**Tests:** Fake subprocess IPC always-on; dependency-absent probe; opt-in real M4 load/generate/cancel; worker crash recovery.

**Acceptance:** API process stays responsive during fake and real jobs; one worker owns MPS; valid MP4 produced on approved hardware; forced cancellation recreates worker.

**Risks:** Spawn behavior, Metal cleanup, offload incompatibility, exporter dependency differences.

**Rollback:** Disable CogVideoX registration/feature flag and uninstall video extras; keep generic runtime foundation.

### Phase 3 - VideoJob, Queue, Persistence, and Task Projection

**Goal:** Establish persistent domain truth, serialized execution, task-center projection, and restart reconciliation.

**Prerequisites:** Phase 1; Phase 2 fake worker contract; migration design review.

**Files:** `backend/app/models/records.py`, new video job repository/service/coordinator modules, `backend/app/services/task_service.py` integration, SQLite migration ledger, new Alembic revision, tests.

**Modules:** VideoJob repository, queue coordinator, lease/reconciler, task projection, artifact manager.

**New interfaces:** Submit/claim/transition/cancel/reconcile/cleanup service methods.

**Data structures:** `video_jobs`, optional model capability/probe records, transactional event payloads.

**Implementation steps:** Add migrations; implement transition guards; transactional task projection/outbox; concurrency one; leases; throttled progress; atomic artifacts; startup reconciliation; retention cleanup.

**Tests:** Both migration paths, state matrix, queue order, duplicate claims, crash/interruption, projection consistency, cleanup/path security.

**Acceptance:** Restart preserves queued jobs and marks orphaned running jobs interrupted; TaskStore receives correct events; no partial artifact is exposed.

**Risks:** Split-brain state between VideoJob and TaskRecord; SQLite locking; excessive progress writes.

**Rollback:** Stop coordinator, reverse code usage, retain additive tables for forensic safety; do not destructively downgrade user databases.

### Phase 4 - OpenAI-style Video API

**Goal:** Expose secure submit/status/content/cancel endpoints and capability-aware model listing.

**Prerequisites:** Phase 3 services; stable schemas/errors; auth design decision for project keys.

**Files:** New `backend/app/api/videos.py`, `backend/app/main.py`, `backend/app/api/openai_api.py` or shared OpenAI utilities, security/rate-limit modules as needed, API tests, API docs.

**Modules:** Request/response schemas, principal adapter, idempotency, error mapping, content response.

**New interfaces:** `POST /v1/videos`, `GET /v1/videos/{id}`, `GET /v1/videos/{id}/content`, `POST /v1/videos/{id}/cancel`; `/v1/models` extensions.

**Data structures:** Public request/job/error schemas and idempotency records/hash fields.

**Implementation steps:** Route wiring; validation/profile resolution; auth/scope reuse; rate limits; idempotent transaction; non-enumerating reads; secure content; cancellation; compatibility documentation.

**Tests:** Full matrix in section 23.2, polling concurrency, LAN client contract fixture, range requests if adopted.

**Acceptance:** Fake runtime end-to-end works over HTTP; retries do not duplicate work; unauthorized artifacts are inaccessible; OpenAI envelope remains consistent.

**Risks:** Ambiguous deprecated upstream semantics, polling load, API-key scope regressions.

**Rollback:** Unregister videos router and capability extensions behind a feature flag; preserve jobs/artifacts for controlled export/deletion.

### Phase 5 - Model Management and Readiness

**Goal:** Make installation, probing, lifecycle, and removal manageable without shell commands.

**Prerequisites:** Phase 2 probe; Phase 3 persistence; license/storage policy.

**Files:** `backend/app/api/models.py`, runtime API, `model_manager.py`, `downloader.py`, `model_readiness_service.py`, records/migrations, client API mappings, tests.

**Modules:** Video model catalog, install task, manifest validation, readiness probe, runtime start/stop, uninstall guard.

**New interfaces:** Model catalog/install/probe/start/stop/uninstall operations, extending existing routes where semantics fit.

**Data structures:** Capability metadata, install/runtime/readiness states, probe summary, pinned revision/manifest.

**Implementation steps:** Register catalog entry; resumable staging download; explicit confirmation; validate/publish; readiness aggregation; runtime lifecycle; delete/uninstall distinction; active-job guards.

**Tests:** State truth table, interrupted download, corrupt snapshot, missing extras, unsupported platform, MPS unavailable, active-job uninstall rejection.

**Acceptance:** A user can install and reach a truthful readiness state through ModelForge; readiness reads have no side effects; uninstall semantics are explicit.

**Risks:** Disk duplication, Hugging Face cache semantics, installer restart behavior, license presentation.

**Rollback:** Disable catalog entry and installs; retain already downloaded managed files until user-confirmed cleanup.

### Phase 6 - PySide6 Video UX

**Goal:** Add minimal model controls, generation workflow, preview, and task visibility.

**Prerequisites:** Phases 4-5 APIs; selected Qt media playback strategy; localization keys.

**Files:** `client/pyside6/api_client/client.py`, `pages/models_page.py`, `pages/runtime_page.py`, new video page/components, navigation/main window, readiness/task stores, localization resources, GUI tests.

**Modules:** Video form/view model, job polling/SSE binding, preview/download, model/runtime actions.

**New interfaces:** Client methods for video and model lifecycle endpoints; Qt signals for job changes.

**Data structures:** Client video job/profile/readiness models.

**Implementation steps:** Add navigation; build bounded form; use readiness store; submit and bind projection; cancellation state; preview; save/open; model controls; localization/accessibility.

**Tests:** Domain mapping, offscreen states, signal ordering, stale response handling, locale switching, fake end-to-end UI smoke.

**Acceptance:** User completes install/readiness/generate/cancel/view flow without terminal commands; GUI remains responsive; controls reflect authoritative state.

**Risks:** Qt codec availability, large local download UX, duplicate SSE/poll updates.

**Rollback:** Hide video navigation and controls behind feature flag; backend remains usable.

### Phase 7 - Validation, Benchmark, and CI Gates

**Goal:** Turn implementation evidence into release gates across platforms.

**Prerequisites:** Phases 2-6; dedicated hardware runner; frozen benchmark manifest.

**Files:** Test markers/config, CI workflows, benchmark harness/results schema, validation evidence document.

**Modules:** Cross-platform fake suite, MPS integration suite, benchmark collector, artifact verifier.

**New interfaces:** CLI/test entrypoints for opt-in offline real-model validation.

**Data structures:** Benchmark and release-evidence manifests.

**Implementation steps:** Partition tests; enforce no-download CI; add platform probes; run M4 matrix; record metrics; repeat/cancel/leak checks; publish internal evidence; set thresholds from evidence.

**Tests:** Entire section 23 plus benchmark harness self-tests.

**Acceptance:** Required CI is green on Linux/Windows/macOS; M4 evidence passes the declared support gate or release is explicitly marked unavailable/experimental.

**Risks:** Flaky hardware runner, thermal variance, hidden model cache network access.

**Rollback:** Remove real-model job from required CI while retaining scheduled evidence; do not weaken fake/API gates.

### Phase 8 - Documentation, Packaging, and Release Readiness

**Goal:** Deliver reproducible installation, operation, LAN integration, troubleshooting, and rollback documentation.

**Prerequisites:** All prior accepted phases and evidence; release-governance review.

**Files:** `requirements-ai.txt` or a dedicated video extra/lock, API/reference/server docs, model license/provenance, troubleshooting, release manifests and changelog.

**Modules:** Packaging metadata, optional dependency installer, diagnostics/export redaction.

**New interfaces:** Supported installation command/UI flow and documented API contract.

**Data structures:** Compatibility table, provenance manifest, retention/config reference.

**Implementation steps:** Pin extras; verify clean install/base install; document LAN/auth/CORS; document storage/cleanup; add API examples; record upstream deprecation difference; complete release checklist.

**Tests:** Clean-room package install, base-without-video startup, offline model startup, docs examples against fake server, security scan/license inventory.

**Acceptance:** Another developer can install and validate from docs; users can operate through UI/API; release status matches benchmark evidence.

**Risks:** Wheel availability by Python/macOS version, bundle size, stale compatibility claims.

**Rollback:** Ship without video extras/feature flag; remove catalog advertisement while preserving existing user data and documented cleanup path.

## 27. Acceptance Criteria

Release acceptance requires all of the following:

1. Existing chat, Agent Runtime, model, task, and desktop tests remain passing.
2. Base installation starts without video dependencies or weights.
3. CogVideoX is represented as `video_generation`, not a chat model.
4. VideoJob is persistent and projects consistently into Task/Event/Outbox.
5. Only one local MPS generation runs at a time by default.
6. FastAPI remains responsive while generation executes.
7. Submit/status/content/cancel endpoints pass authentication, authorization, idempotency, error, and rate-limit tests.
8. Output is atomically published, structurally validated, and never exposed by absolute path.
9. Queued restart and orphaned-running reconciliation pass.
10. Cooperative and forced cancellation paths pass with measured latency.
11. Model installation/readiness/start/stop/uninstall are available without shell commands and have truthful states.
12. PySide6 remains responsive and supports the minimal end-to-end workflow.
13. Ordinary CI performs no model download and passes on non-MPS environments.
14. M4 24GB support language exactly matches Phase 0/7 evidence.
15. Documentation records dependency/model revisions, security posture, retention, known limitations, and OpenAI compatibility differences.

## 28. Risks

| Risk | Status | Mitigation |
|---|---|---|
| CogVideoX-2B cannot complete the target workload on M4 24GB | UNKNOWN | Phase 0 stop/go spike; do not expose READY or claim support before evidence |
| MPS allocator failure despite available unified memory | CONFIRMED upstream risk | Process isolation, conservative profile, slicing/tiling tests, measured repeat runs |
| Unsupported MPS operations or CPU fallback causes extreme latency | UNKNOWN | Fallback off/on comparison and operator diagnostics |
| FP16 produces NaN/black/corrupt output | UNKNOWN | Structural/pixel checks and repeatability tests; evaluate approved fallback only |
| Cancellation callback is too coarse | NEEDS BENCHMARK | Grace timeout plus worker termination and recreation |
| API and worker state diverge after crash | INFERRED risk | VideoJob authority, leases, transactional task projection, startup reconciliation |
| Partial or unauthorized artifacts leak | INFERRED risk | Staging paths, atomic rename, ownership checks, non-enumerating errors |
| Downloads cannot resume after restart | CONFIRMED current limitation | Harden downloader before claiming resumability |
| Optional dependencies break base packaging | INFERRED risk | Isolated extras, lazy import, base-start CI |
| Deprecated OpenAI API semantics create false compatibility expectations | CONFIRMED | ModelForge contract version and explicit deviation documentation |
| Prompt or paths leak through events/logs | INFERRED risk | Existing redaction policy, typed safe errors/events, negative leakage tests |
| SQLite write contention from progress events | INFERRED risk | Throttling, coarse persistence, outbox batching |

## 29. Open Questions

These questions must be resolved at the named phase, not guessed during implementation:

1. **NEEDS BENCHMARK / Phase 0:** Can M4 24GB reliably generate the approved 49-frame profile?
2. **NEEDS BENCHMARK / Phase 0:** What are cold load, first inference, warm inference, decode, export, and cancellation times?
3. **NEEDS BENCHMARK / Phase 0:** What is peak unified memory and does swap occur?
4. **UNKNOWN / Phase 0:** Which operators, if any, require CPU fallback for the pinned matrix?
5. **NEEDS BENCHMARK / Phase 0:** Are VAE slicing and tiling both necessary, and what is their cost?
6. **UNKNOWN / Phase 0:** Does any supported CPU-offload strategy improve MPS viability or only increase transfers/time?
7. **UNKNOWN / Phase 1:** Should model capabilities be normalized in a new table or added as versioned JSON/columns to `ModelRecord`? Decide after query/migration review.
8. **UNKNOWN / Phase 3:** Is one output per job sufficient, or is a separate artifact table required for thumbnails/alternate encodes?
9. **UNKNOWN / Phase 4:** Does the target Flutter player require byte-range support for acceptable seeking?
10. **UNKNOWN / Phase 4:** Which existing project-key principal/scopes can be reused unchanged for `/v1/videos`?
11. **UNKNOWN / Phase 5:** Should managed snapshots reuse the Hugging Face shared cache or use a ModelForge-owned immutable store with deduplication links?
12. **UNKNOWN / Phase 6:** Which Qt multimedia backend/codecs are guaranteed in each packaged desktop target?
13. **UNKNOWN / Product:** Prompt retention duration and whether users may opt out of prompt persistence entirely.
14. **UNKNOWN / Product:** Default completed-artifact retention and per-user disk quota.

## 30. Rollback Strategy

Rollback is capability-based and additive:

1. Keep video routes, catalog entries, and UI navigation behind one server-advertised feature flag.
2. Stop queue admission before stopping workers.
3. Let the active job finish or cancel it explicitly; never abandon a worker silently.
4. Disable CogVideoX registration while preserving generic runtime and job code if only the adapter is faulty.
5. Preserve additive database tables/columns during application rollback; old binaries ignore them. Do not perform destructive down migrations on user installations.
6. Preserve completed artifacts and job metadata until the user or retention policy deletes them.
7. Provide an explicit cleanup command/UI that reports affected snapshots, jobs, and artifacts before deletion.
8. Base ModelForge, chat runtimes, Agent Runtime, and task center must remain operable with video disabled or extras absent.

## 31. Future Extensions

The v1 contracts should permit, but must not pre-implement:

- CogVideoX-5B and additional text-to-video profiles.
- CogVideoX image-to-video with a new capability/input schema rather than optional untyped fields.
- Wan and LTX-Video adapters through a reviewed runtime-provider SPI.
- CUDA and CPU runtimes selected by explicit platform profiles.
- Remote video providers behind the same VideoGenerationService with provider-specific adapters.
- Agent tools that submit/read VideoJobs without owning execution.
- Webhook/event callbacks for trusted LAN automation.
- Multiple artifacts, thumbnails, alternate encodes, and range-optimized media serving.
- Priority/fair queues and configurable device pools after single-device correctness is proven.

The extension rule is: new model families implement the generic capability/job/artifact contracts and define their own validated profiles. They do not add model-specific fields to the common API without versioning.

## External References

Authoritative sources reviewed on 2026-09-11:

1. CogVideoX-2B model card: https://huggingface.co/zai-org/CogVideoX-2b
2. CogVideoX-2B repository files: https://huggingface.co/zai-org/CogVideoX-2b/tree/main
3. Diffusers CogVideoX API: https://huggingface.co/docs/diffusers/api/pipelines/cogvideox
4. Diffusers pipeline callbacks: https://huggingface.co/docs/diffusers/using-diffusers/callback
5. Diffusers MPS optimization guidance: https://huggingface.co/docs/diffusers/optimization/mps
6. PyTorch MPS notes: https://docs.pytorch.org/docs/stable/notes/mps.html
7. PyTorch MPS environment variables: https://docs.pytorch.org/docs/stable/mps_environment_variables.html
8. Official CogVideo repository: https://github.com/zai-org/CogVideo
9. Official Diffusers repository: https://github.com/huggingface/diffusers
10. Public Diffusers CogVideoX MPS allocation report: https://github.com/huggingface/diffusers/issues/11393
11. ComfyUI repository, reviewed only for queue/history/output operational patterns: https://github.com/comfyanonymous/ComfyUI
12. OpenAI Videos API reference and deprecation notice: https://platform.openai.com/docs/api-reference/videos
13. OpenAI developer API reference for video resources: https://developers.openai.com/api/reference/resources/videos

Third-party implementations are references only. No external project code is assumed portable or licensed for direct copying into ModelForge; production implementation must follow this repository's authentication, persistence, task, security, and packaging boundaries.
