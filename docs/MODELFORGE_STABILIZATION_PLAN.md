# ModelForge Release Stabilization Plan

> Audit date: 2026-09-14
> Audited revision: `733f0d7` (`master`, aligned with `origin/master`)
> Scope: repository reconnaissance, test execution, architecture audit, defect classification, root-cause analysis, and release repair planning only.
> Change policy: no product features, no business-code changes, no test weakening, no commits, and no pushes were performed during this audit.

## 1. Executive Decision

**Release health: RED / NO-GO. ModelForge is not ready to resume feature development.**

The automated pytest baseline is broad and currently green, but it is not a sufficient release signal:

- The current checkout produces a Docker image that cannot start as its declared non-root user, and that image contains a local development JWT secret and Python cache files. This is a P0 packaging and security boundary failure.
- The required CI lint gate reports 31 errors, so both the main test job and desktop job fail before their test stages.
- Agent Team execution has two independent P1 correctness failures: duplicate event sequences and false completion of asynchronous child Agent Runs.
- Workflow cancellation is not authoritative and does not propagate to child Agent Runs, allowing cancelled work to complete or continue producing side effects.
- PostgreSQL can upgrade to Alembic head, but historical migration verification is not trustworthy and `alembic check` reports schema/ORM drift.

Current issue count, without double-counting combined root causes:

| Classification | Count |
|---|---:|
| P0 | 1 |
| P1 | 4 |
| P2 | 8 |
| P3 | 7 |
| REGRESSION tags | 6 |
| Confirmed FLAKY tests | 0 |

## 2. Audit Scope and Method

The audit used the current code as the source of truth. README and historical documents were treated only as claims to verify.

Reviewed surfaces:

- Git state and recent history.
- Repository instructions: no `AGENTS.md` or `AGENTS.override.md` exists in the repository.
- FastAPI startup, middleware, routers, API contracts, and OpenAI-compatible endpoints.
- SQLAlchemy models, SQLite additive migrations, PostgreSQL Alembic history, and schema parity.
- Agent Runtime, events, tools, Policy, MCP, Plugin lifecycle, Scheduler, Multi-Agent, and Workflow execution.
- Knowledge/RAG, model registry, provider/runtime selection, chat paths, and background execution.
- PySide6 desktop client, test markers, CI/CD, container build, dependency audit, logging, tracing, metrics, and error handling.

Executed evidence included full pytest runs, coverage, desktop tests, app boot smoke, Python compilation, Ruff, dependency audits, Docker build/start checks, PostgreSQL Alembic upgrade, ORM import, `alembic check`, OpenAPI enumeration, and targeted minimal reproductions for the defects below.

## 3. Current Test Baseline

Environment used for the local baseline:

- macOS host, Python `3.11.15` in `.venv`.
- `pytest 9.1.1`, `ruff 0.16.3`, PySide6 available.
- CI is configured for Python `3.10`; that version difference remains a release validation dimension.
- The shell has no plain `python` executable; repository commands must use `.venv/bin/python` locally or an activated virtual environment.

| Check | Result | Time / Notes |
|---|---|---|
| Full pytest, no coverage | **1354 passed, 3 skipped, 0 failed, 0 errors** | 110.95s pytest / 112.46s wall |
| CI-equivalent pytest + backend coverage | **1354 passed, 3 skipped** | 81.93% coverage; 123.21s pytest / 124.60s wall; 75% gate passes |
| Desktop marker suite | **84 passed, 1273 deselected** | 63% `client/pyside6` coverage; 33.97s |
| App boot | **1 passed** | `tests/test_app_boot.py` |
| Import smoke | PASS | FastAPI metadata version `3.0` |
| Python compile | PASS | `compileall` |
| Whitespace | PASS | `git diff --check` |
| Ruff | **FAIL** | 31 errors: 27 `E702/E731` and 4 `I001` across four files |
| Runtime dependency audit | PASS | 61 dependencies, 0 known vulnerabilities |
| Development dependency audit | PASS | 33 dependencies, 0 known vulnerabilities |
| Docker build | PASS | `modelforge:stabilization-audit` built |
| Docker non-root startup | **FAIL** | `PermissionError` reading `/app/backend/app/runtime/__init__.py`; `/healthz` never becomes available |
| PostgreSQL 16 empty DB -> Alembic head | PASS with caveat | Upgraded to `0011_chat_message_workflow`; 81 physical tables including `alembic_version` |
| PostgreSQL app/ORM import | PASS | ORM metadata declares 80 application tables |
| `alembic check` | **FAIL** | Three unexpected indexes exist in DB but not ORM metadata |
| OpenAPI enumeration | PASS | 285 paths / 343 operations; matches the current README count |

Skipped tests are explicit environment gates, not confirmed flaky failures:

1. External network integration requires `RUN_NETWORK_TESTS=1`.
2. Real CPU model smoke requires `MODELFORGE_CPU_SMOKE_MODEL`.
3. GPU smoke requires an NVIDIA CUDA runner; this host has no CUDA device.

No test was deleted, skipped, marked xfail, or weakened. No confirmed flaky test was observed in this run. The suite reports zero visible warnings, but `pytest.ini` filters one Starlette/httpx deprecation-warning class, so the unfiltered warning count is unknown.

## 4. Current Architecture Map

### 4.1 Size and Coupling

- Backend: 197 Python modules, approximately 39,837 LOC.
- PySide6 desktop: 58 Python modules, approximately 14,144 LOC.
- Tests: 142 Python files, approximately 28,112 LOC.
- ORM: 80 application tables concentrated in `backend/app/models/records.py` (approximately 2,576 lines).
- Static internal dependency scan: 621 edges and one circular strongly connected component:
  `embedding_service -> model_registry -> local_model_importer -> runtimes.adapters -> embedding_runtime -> embedding_service`.
- Highest fan-in modules: `models.records` (75 importing modules), `core.database` (54), `core.api_contracts` (42), and `core.config` (38).

### 4.2 Startup and Process Lifecycle

`backend/app/main.py` owns the FastAPI lifespan. Startup initializes or validates the database, starts task outbox publishing, retry monitoring, the video queue, legacy runtime/agent/knowledge/plugin singletons, the 3.0 Agent Runtime, recovery, and persistent schedules. Shutdown stops the task and video services and awaits Agent Runtime shutdown.

The Agent Runtime tracks Agent Run tasks and cancellation tokens. Workflow and some plugin/event background activity use separate task creation paths and do not share the same ownership/cancellation boundary.

### 4.3 API Surfaces

- `/api/v1`: primary control plane with auth, sessions, chat, models, runtime, agents, teams, workflows, knowledge, plugins, tasks, training, video desktop routes, and related resources.
- `/v1`: OpenAI-compatible inference and video endpoints with their own error envelope and local API-key path.
- `/api/v2`: commercial/project API control plane and invocation surface.
- Current OpenAPI: 285 paths and 343 operations.

The repository retains both legacy and newer contracts in several domains. Compatibility may be intentional, but ownership and lifecycle behavior are not consistently unified.

### 4.4 Data and Migrations

- SQLite is initialized with `Base.metadata.create_all()` followed by an append-only local migration ledger in `core.database`.
- PostgreSQL requires Alembic and fails closed if `alembic_version` is unavailable.
- Alembic has revisions from `0001_server_baseline` through merged head `0011_chat_message_workflow`.
- The baseline revision dynamically reads current `Base.metadata`, so historical revision boundaries are not immutable.
- PostgreSQL head currently differs from ORM metadata by three model indexes.

### 4.5 Agent Runtime, Tools, MCP, and Scheduler

`AgentRuntime` composes run/agent stores, event bus, execution engine, context builder, memory and knowledge providers, Policy, metrics, Tool Registry/Executor, MCP registry, plugin scopes, Scheduler, and DelegateTool. Agent Runs have durable state/lease fields and Runtime-owned task tracking.

MCP tools are adapted into the unified Tool Registry. The in-process Scheduler triggers normal Agent Runs. Scheduler and Agent Runtime have lifecycle snapshots, but server multi-instance authority is not established by the current implementation.

### 4.6 Plugins

Two plugin-manager concepts remain:

- `services/plugin_manager.py`: legacy plugin registration/install API used during application startup.
- `runtime/plugins/manager.py`: runtime-scoped manifest, lifecycle, scope, and tool mounting.

The runtime plugin lifecycle has confirmed load rollback and remount state-machine defects.

### 4.7 Multi-Agent and Workflow

Agent Teams persist teams, members, tasks, messages, events, delegations, and task-center projections. The public contract accepts six strategies, but execution always enters one synchronous sequential implementation that creates asynchronous Agent Runs.

Workflow definitions and runs are persisted. `WorkflowService` spawns background execution; `WorkflowEngine` supports LLM, Agent, Tool, control, and output nodes. Workflow task ownership, cancellation authority, and child Agent Run propagation are incomplete.

### 4.8 Knowledge and Chat

Knowledge uses a process-wide `KnowledgeBase` retrieval engine plus a user-scoped `KnowledgeService` library layer. Upload parsing/embedding is offloaded with `asyncio.to_thread`, but the request SQLAlchemy Session crosses thread boundaries.

Chat has a legacy chat service and a structured chat-turn service. The structured path reuses parts of the legacy execution layer. This is a compatibility bridge, not yet a single state machine.

### 4.9 Model Providers and Runtime Selection

The repository contains a legacy `RuntimeRegistry`, a `ModelRuntimeManager`, and a `RuntimeResolver`/adapter catalog. Local registry-backed Agent execution routes through `ModelRuntimeManager`; legacy chat and some compatibility surfaces can still route through `RuntimeRegistry`. Runtime status persistence is best-effort and silently discards all database errors.

### 4.10 Desktop, CI, and Observability

The PySide6 client is a thin HTTP client with pages for workspace, chat, models, video, data, training, knowledge, agents, workflows, runtime, automation, tasks, control, extensions, settings, and developer API. Desktop tests run offscreen and are separately marked.

CI has test, desktop, Docker build, and PostgreSQL release-candidate jobs. The main and desktop jobs both require Ruff. Backend coverage has a 75% gate; desktop coverage is collected but has no fail-under threshold.

Correlation IDs, operation audits, Agent/Workflow traces, model metrics, runtime lifecycle diagnostics, and structured errors exist, but error policy is inconsistent. Several persistence/event paths catch `Exception` and return without durable diagnostics.

## 5. Defect Queue Summary

| ID | Grade | Tags | Module | Summary |
|---|---|---|---|---|
| MF-STAB-001 | P0 | ENVIRONMENT, SECURITY | Docker/release | Current checkout builds a non-starting image and includes local secret/cache state |
| MF-STAB-002 | P1 | REGRESSION | CI/desktop | Required Ruff gate has 31 errors |
| MF-STAB-003 | P1 | REGRESSION | Agent Team | Event sequence generation violates unique key during `execute=true` |
| MF-STAB-004 | P1 | REGRESSION | Agent Team/Agent Runtime | Asynchronous child Run metadata is treated as a completed result |
| MF-STAB-005 | P1 | REGRESSION | Workflow/Agent Runtime | Cancellation is overwritten and child Agent Runs are orphaned |
| MF-STAB-006 | P2 | REGRESSION | Runtime Plugin | Entry import failure leaves a false loaded/mounted state |
| MF-STAB-007 | P2 |  | Runtime Plugin | Unmounted plugin cannot be mounted again |
| MF-STAB-008 | P2 | REGRESSION | Goals/Approval | Approval can reference a nonexistent Agent |
| MF-STAB-009 | P2 |  | Agent Team API | Six accepted strategies all execute as sequential |
| MF-STAB-010 | P2 |  | Alembic | Baseline migration imports current metadata and invalidates historical testing |
| MF-STAB-011 | P2 |  | ORM/Alembic | PostgreSQL head and ORM metadata disagree on three indexes |
| MF-STAB-012 | P2 |  | Knowledge API | Request SQLAlchemy Session is used across worker threads |
| MF-STAB-013 | P2 |  | Model Runtime | Runtime status persistence silently swallows every DB error |
| MF-STAB-014 | P3 | DOCS | Documentation | Test counts, service counts, versions, and historical/current claims drift |
| MF-STAB-015 | P3 | TEST-INFRA | Pytest | One deprecation-warning category is globally hidden |
| MF-STAB-016 | P3 | ARCH | Plugin/runtime/chat/knowledge | Parallel legacy and current implementations lack an explicit ownership map |
| MF-STAB-017 | P3 | ARCH | Runtime/model services | One circular dependency SCC is present |
| MF-STAB-018 | P3 | TEST-GAP | Integrations | Network, real CPU model, and GPU paths are not in the local baseline |
| MF-STAB-019 | P3 | TEST-GAP | Desktop CI | Desktop coverage is measured at 63% but has no enforced threshold |
| MF-STAB-020 | P3 | ARCH | ORM | Monolithic model module and high fan-in increase migration blast radius |

## 6. Root-Cause Analysis: P0

### MF-STAB-001 - Docker Build Context Is Not Hermetic

- **Trigger:** Build the current checkout with `docker build`, then start the image using the Dockerfile's declared `USER modelforge`.
- **Actual behavior:** Uvicorn fails during import with `PermissionError: [Errno 13] Permission denied: '/app/backend/app/runtime/__init__.py'`; `/healthz` never starts. Image inspection also finds `/app/backend/app/data/.dev_jwt_secret`, 33 `__pycache__` directories, and 578 `.pyc` files.
- **Call chain:** Docker `COPY . .` -> files owned by `root:root` -> `USER modelforge` -> Uvicorn imports `main` -> `api.agent` -> `runtime.errors` -> package import reads `runtime/__init__.py` -> permission failure.
- **Root cause:** 111 local files under audited trees have mode `0600`; Git records normal non-executable file mode and therefore does not surface this in status. Docker preserves the local context modes but changes ownership to root. `.dockerignore` excludes root `data/*` and a top-level cache pattern, but does not prevent the nested ignored development state observed in the image.
- **Impact:** Current release image is unusable. Publishing the image can also disclose a local development signing/JWT secret and non-source cache contents. This is both a startup blocker and a build-boundary security failure.
- **Similar-risk search:** Any ignored nested secret, database, model cache, generated bytecode, or restrictive source mode can enter the image because the build copies the repository wholesale.
- **Regression risk:** A narrow chmod-only change could leave secret leakage; a narrow ignore-only change could leave startup failure. Over-broad chown/chmod can weaken runtime-state permissions.
- **Minimum repair:** Make the image input explicit or comprehensively ignored; normalize read/execute permissions for application source before switching user; keep writable state directories separately owned; fail the build if secret/cache/database artifacts are present; verify startup as UID 10001.
- **Regression tests:** Build from a fixture containing restrictive source modes and ignored nested state; assert non-root import and `/healthz`; inspect the image for `.dev_jwt_secret`, `.env`, DB files, `__pycache__`, and `.pyc`; verify writable paths remain limited to intended runtime directories.
- **Dependencies:** Must be fixed before any release-candidate Docker evidence is accepted.
- **Expected files:** `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, and a narrowly scoped existing/new release verification script if required. No application feature code is needed.

## 7. Root-Cause Analysis: P1

### MF-STAB-002 - Required CI Ruff Gate Fails

- **Trigger:** Run `ruff check backend client tests scripts` or either CI lint step.
- **Actual behavior:** 31 errors: import sorting in `session_sidebar.py`, `icons.py`, `test_chat_leakage.py`, and `test_openai_validation.py`; lambda assignment and multi-statement-line violations in `icons.py`.
- **Call chain:** GitHub Actions `test`/`desktop` job -> Ruff step -> non-zero exit -> pytest/build/release-candidate dependency chain is blocked.
- **Root cause:** Recent desktop and test changes were merged without satisfying the repository's existing Ruff rules.
- **Impact:** The protected release pipeline cannot produce a valid candidate despite the local pytest suite being green.
- **Similar-risk search:** No additional Ruff violations were found outside the four reported files.
- **Regression risk:** Mechanical formatting in icon path-building code can accidentally alter painter behavior if statements are reordered rather than only expanded.
- **Minimum repair:** Apply only Ruff-preserving import ordering and statement/lambda expansion; do not refactor icon behavior.
- **Regression tests:** Re-run Ruff, the full suite, and desktop screenshot/widget tests covering the icon paths.
- **Dependencies:** Can be repaired immediately after MF-STAB-001 containment; required before all later CI evidence.
- **Expected files:** `client/pyside6/theme/icons.py`, `client/pyside6/pages/session_sidebar.py`, `tests/test_chat_leakage.py`, `tests/test_openai_validation.py`.

### MF-STAB-003 - Agent Team Event Sequence Collision

- **Trigger:** Create a team with at least one non-manager member and create a team run with `execute=true`.
- **Actual behavior:** Flush during task-center transition raises `sqlite3.IntegrityError: UNIQUE constraint failed: agent_team_events.run_id, agent_team_events.sequence`; API behavior becomes an unhandled 500.
- **Call chain:** `AgentTeamService.create_run` -> `_event(team.started)` -> `_build_team_tasks` -> `_event(task.created)` -> `_execute_sequential` -> more `_event` calls -> later flush/commit -> unique index rejection.
- **Root cause:** `_event()` calculates `sequence` using a database `count()`. `SessionLocal` has `autoflush=False`, so pending events are invisible to repeated counts and receive the same sequence.
- **Impact:** Normal executable Agent Team runs fail, transaction state becomes invalid, and the team/task audit trail is not durable.
- **Similar-risk search:** Workflow event sequencing also computes a last sequence, but uses a separate session and catches all errors; it needs concurrency coverage under MF-STAB-005 rather than reuse of this exact fix.
- **Regression risk:** Adding a flush alone does not solve concurrent writers. Sequence allocation must remain unique under retries and concurrent event appenders.
- **Minimum repair:** Allocate sequence from a transaction-safe authoritative source, with unique-conflict retry or row-level serialization appropriate to SQLite/PostgreSQL; keep event append and team state transaction boundaries explicit.
- **Regression tests:** Single run with multiple pending events; multiple member tasks; concurrent appenders; rollback/retry; SQLite and PostgreSQL unique-key assertions; API returns a stable error if persistence genuinely fails.
- **Dependencies:** Fix before MF-STAB-004 can be validated through the real team path.
- **Expected files:** `backend/app/services/agent_team_service.py`, relevant model/migration only if a durable counter is proven necessary, `tests/test_agent_teams_v31.py`, PostgreSQL integration tests.

### MF-STAB-004 - Agent Team Reports Pending Child Runs as Completed

- **Trigger:** Execute a team run after bypassing/fixing the event collision.
- **Actual behavior:** Child creation returns `status=PENDING`; the team task, team run, and task-center record are immediately marked completed/succeeded, and stored output is only child Run metadata. Later child failure does not update team state.
- **Call chain:** `AgentTeamService._execute_sequential` -> `AgentRunService.create_run(execute=True)` -> `AgentRuntime.create_run` creates and spawns a background task -> service returns `{run_id, status}` -> team stores payload as output and marks completion.
- **Root cause:** Synchronous team orchestration assumes `execute=True` means execution has completed, but Agent Runtime defines it as asynchronous scheduling.
- **Impact:** False success, incorrect handoff context, lost child output, no failure propagation, misleading audit/task status, and possible user action based on nonexistent results.
- **Similar-risk search:** Delegation and Workflow Agent nodes also create asynchronous runs; Workflow at least polls, while Team does not.
- **Regression risk:** Blocking an HTTP request until arbitrary model completion can cause timeouts. The fix needs a durable asynchronous team state machine or a bounded, explicitly awaited service path, not a busy wait in request scope.
- **Minimum repair:** Keep team run non-terminal while child runs execute; persist child `run_id`; advance only after terminal child state; pass actual child output to the next member; propagate failure/cancellation; make task-center state follow the same authority.
- **Regression tests:** Pending -> running -> completed and pending -> failed child transitions; multi-member output handoff; cancellation; restart/recovery; child completion after request session closes; no false terminal state.
- **Dependencies:** MF-STAB-003 first. Coordinate cancellation semantics with MF-STAB-005.
- **Expected files:** `backend/app/services/agent_team_service.py`, possibly existing task/recovery integration modules, `tests/test_agent_teams_v31.py`, focused runtime integration tests.

### MF-STAB-005 - Workflow Cancellation Is Non-Authoritative and Does Not Cancel Child Runs

- **Trigger:** Cancel a running Workflow while its background task continues, or time out/cancel a Workflow Agent node.
- **Actual behavior:** `cancel_run()` returns `CANCELLED`, but background execution can later persist `COMPLETED` or `FAILED`. Timed-out/cancelled Agent nodes leave child Agent Runs active.
- **Call chain:** `WorkflowService._spawn` creates an untracked asyncio task/thread -> `cancel_run` only writes DB status -> runner continues -> `_persist_state(COMPLETED)` overwrites cancellation. Agent node path: `_node_agent` creates a Run -> polls -> timeout raises without `runtime.cancel_run()`.
- **Root cause:** Workflow execution task handles and cancellation tokens are not owned by the service; terminal writes do not use compare-and-set; cancellation checks occur after event emission and can be converted by generic failure handling; parent-child cancellation propagation is absent.
- **Impact:** Cancelled work may continue model/tool execution, consume leases/resources, create side effects, and end with a status that contradicts the user's cancellation request.
- **Similar-risk search:** Team orchestration has the same parent/child lifecycle class of problem. Plugin and workflow event tasks also need bounded shutdown diagnostics.
- **Regression risk:** Cancelling the asyncio wrapper without cancelling a child Agent Run still leaks work. Making every exception `CANCELLED` can hide genuine failures.
- **Minimum repair:** Track workflow task handles; add a workflow cancellation token; use legal CAS terminal transitions where `CANCELLED` cannot be overwritten; propagate cancellation/timeout to recorded child Agent Runs; preserve distinct cancellation and failure event semantics; recover active runs deterministically after restart.
- **Regression tests:** Cancel during slow node, cancel between nodes, completion/cancel race, Agent node timeout, child cancellation, tool side-effect boundary, thread fallback path, restart recovery, and terminal event/status consistency on SQLite and PostgreSQL.
- **Dependencies:** Establish terminal-state contract before changing Team lifecycle; validate with Agent Runtime cancellation tests.
- **Expected files:** `backend/app/services/workflow_service.py`, `backend/app/services/workflow_engine.py`, existing runtime/run-store cancellation interfaces, recovery service, workflow tests.

## 8. Root-Cause Analysis: P2

### MF-STAB-006 - Plugin Import Failure Leaves False Loaded State

- **Trigger:** Load a valid manifest whose `entry` file/module does not exist or fails during import.
- **Actual behavior:** `load()` raises, but the plugin remains in `_plugins` with `status=loaded`, `mounted=true`, and an existing scope.
- **Call chain:** `PluginManager.load` -> create scope/context -> insert state and emit `plugin.loaded` -> `_import_entry` raises before the setup cleanup `try` block.
- **Root cause:** Registry mutation and success event occur before entry import, while rollback covers setup/get_tools/contribute/extend only.
- **Impact:** Capability discovery and lifecycle APIs report a plugin that never loaded; subsequent load attempts return the stale state.
- **Similar-risk search:** Dependency checks and lifecycle mutations should be reviewed for all partial-failure points.
- **Regression risk:** Moving all work into one rollback block must avoid emitting `loaded` before success and must clean only resources owned by this attempt.
- **Minimum repair:** Make load transactional at the manager level: import/setup/mount first in a provisional scope, publish state and `plugin.loaded` only on success, and always unmount/remove on failure.
- **Regression tests:** Missing file, syntax error, setup error, get_tools error, partial tool registration, retry after failure, and dependency behavior.
- **Dependencies:** Fix before remount semantics in MF-STAB-007 are finalized.
- **Expected files:** `backend/app/runtime/plugins/manager.py`, plugin lifecycle tests.

### MF-STAB-007 - Plugin Unmount Cannot Be Reversed

- **Trigger:** Load a plugin, call unmount, then call mount.
- **Actual behavior:** First mount state is true; unmount succeeds; later mount returns false and no tools are restored.
- **Call chain:** `PluginManager.unmount` -> `PluginScope.unmount` unregisters and clears `_owned_tools` -> manager sets `mounted=false` -> `PluginManager.mount` rejects false state.
- **Root cause:** The lifecycle exposes reversible mount/unmount APIs, but unmount destroys the only tool ownership inventory and mount has no reconstruction path.
- **Impact:** Public lifecycle contract is misleading; recovery requires unload/reload and may lose runtime state.
- **Similar-risk search:** Stop/start currently changes status only and does not define whether tools remain callable.
- **Regression risk:** Retaining live tool objects after unmount can retain resources; re-running setup can duplicate side effects.
- **Minimum repair:** Define one contract: either preserve a declarative tool inventory for remount or reject/remove the mount endpoint until supported. For stabilization, prefer the smallest truthful contract change.
- **Regression tests:** load/mount/unmount/remount, idempotent calls, alias cleanup, duplicate registration, start/stop interaction, unload after unmount.
- **Dependencies:** MF-STAB-006 first.
- **Expected files:** `backend/app/runtime/plugins/manager.py`, `backend/app/runtime/plugins/scope.py`, `backend/app/api/plugin.py` only if the truthful minimal contract requires it, plugin tests.

### MF-STAB-008 - Approval Can Reference a Nonexistent Agent

- **Trigger:** Create an approval with a non-empty `agent_id` that does not exist for the user.
- **Actual behavior:** A `PENDING` approval is persisted successfully.
- **Call chain:** Goals API -> `GoalService.create_approval` -> validates only non-empty ID/risk/optional goal -> inserts `ApprovalRequest`.
- **Root cause:** Unlike goal creation, approval creation does not verify Agent existence/ownership, and `ApprovalRequest.agent_id` has no foreign key.
- **Impact:** Orphaned approvals, misleading human-in-the-loop records, and inconsistent ownership guarantees.
- **Similar-risk search:** All records storing Agent identifiers without FK should be checked for service-level ownership validation.
- **Regression risk:** A direct FK to a name-based/multi-tenant Agent identity may be unsafe without a schema review.
- **Minimum repair:** Reuse the existing user-scoped Agent lookup before insert; do not add a migration unless identity semantics require it.
- **Regression tests:** missing Agent, other user's Agent, valid Agent, deleted Agent behavior, approval linked to a goal with a different Agent.
- **Dependencies:** None; coordinate only if migration identity work is already required by another fix.
- **Expected files:** `backend/app/services/goal_service.py`, goal/approval tests.

### MF-STAB-009 - Agent Team Strategy Contract Is False

- **Trigger:** Create and execute a Team using `PARALLEL`, `PIPELINE`, `HIERARCHICAL`, `DELEGATION`, or `CONSENSUS`.
- **Actual behavior:** Input is accepted and persisted, but all execution calls `_execute_sequential()`.
- **Call chain:** `_strategy` accepts six values -> `create_run(execute=true)` -> unconditional `_execute_sequential`.
- **Root cause:** API/schema capability enumeration was expanded without corresponding dispatch or rejection logic.
- **Impact:** Caller intent is ignored, concurrency/ordering expectations are false, and traces label behavior with a strategy that did not execute.
- **Similar-risk search:** Desktop controls and docs may advertise the same unsupported choices.
- **Regression risk:** Implementing five orchestration modes now would violate stabilization scope and materially increase risk.
- **Minimum repair:** During stabilization, accept only the actually supported strategy or reject unsupported execution with a stable 4xx error. Record real strategy implementations in Future Backlog.
- **Regression tests:** each accepted/rejected strategy, persisted value, execute false behavior, and API error contract.
- **Dependencies:** MF-STAB-004 lifecycle contract should define what `SEQUENTIAL` means before final tests.
- **Expected files:** `backend/app/services/agent_team_service.py`, request/schema or desktop option source if necessary to keep the contract truthful, team tests, documentation after code is stable.

### MF-STAB-010 - Alembic Baseline Is Mutable

- **Trigger:** Upgrade an empty PostgreSQL DB only to `0001_server_baseline` using current source.
- **Actual behavior:** The database already contains tables intended for revisions 0005-0009, including Agent Teams, Goals, Workflows, Attachments, and Chat Turns; 74 tables appear at baseline.
- **Call chain:** Alembic `0001_server_baseline.upgrade` imports `models.records` -> reads current `Base.metadata` -> `create_all` for every table except seven API-platform tables.
- **Root cause:** A historical migration dynamically depends on the present ORM instead of declaring the schema frozen at revision creation.
- **Impact:** Empty-DB upgrade to head can pass even if later migrations are broken, downgrade/history tests are meaningless, and deployed intermediate-version reconstruction is impossible to trust.
- **Similar-risk search:** SQLite uses current `create_all` before its local ledger, so SQLite history tests also need explicit legacy fixtures rather than fresh DB alone.
- **Regression risk:** Rewriting an applied historical revision can invalidate existing deployment checksums/expectations. Repair requires an explicit compatibility policy and evidence against existing databases.
- **Minimum repair:** Freeze baseline behavior without destroying deployed history: document and test the chosen Alembic repair strategy, add immutable schema fixtures/checks, and ensure every later revision proves its own delta. Do not blindly edit applied history without upgrade compatibility evidence.
- **Regression tests:** Upgrade each revision boundary from empty and from representative old snapshots; downgrade only on disposable DB; compare expected tables/columns/indexes per revision; head import and data preservation.
- **Dependencies:** Resolve before accepting MF-STAB-011 or any release migration sign-off.
- **Expected files:** Alembic revisions or a corrective revision, migration verification scripts/tests, deployment documentation. Exact historical file edits require an explicit migration decision review.

### MF-STAB-011 - PostgreSQL Head and ORM Metadata Drift

- **Trigger:** Upgrade PostgreSQL to head and run `alembic check`.
- **Actual behavior:** Alembic proposes removal of `ix_models_base_model_id`, `ix_models_preferred_runtime`, and `ix_models_status` because migrations create them but ORM metadata does not declare them.
- **Call chain:** `0003_model_runtime`/`0004_agent_and_runtime_columns` create indexes -> `ModelRecord` columns omit `index=True`/table indexes -> autogenerate comparison detects extras.
- **Root cause:** Migration and ORM index definitions were maintained independently.
- **Impact:** Schema parity gate fails; future autogenerate revisions can accidentally drop useful indexes; performance assumptions are undocumented.
- **Similar-risk search:** Full metadata-vs-head diff must be checked after migration baseline repair, not only these three indexes.
- **Regression risk:** Removing indexes may regress lookup performance; adding ORM declarations is smaller if indexes remain intentional.
- **Minimum repair:** Declare the intended indexes in ORM metadata or add a corrective migration if they are not intended; make `alembic check` a required gate.
- **Regression tests:** PostgreSQL upgrade head + `alembic check`; index existence and representative query-plan smoke where justified.
- **Dependencies:** MF-STAB-010 migration policy first.
- **Expected files:** `backend/app/models/records.py`, possibly a corrective Alembic revision, migration tests/CI.

### MF-STAB-012 - Knowledge Upload Shares a Session Across Threads

- **Trigger:** Upload a knowledge document; parsing/embedding and projection run through two `asyncio.to_thread` calls using the request-scoped SQLAlchemy Session.
- **Actual behavior:** No deterministic failure was observed in the local liveness test, but the same non-thread-safe Session is used from worker threads and later closed by request scope. Under PostgreSQL/disconnect/concurrency this can produce transaction corruption or driver errors.
- **Call chain:** `knowledge_upload` receives `db` -> `to_thread(kb.upload, db=db)` -> `to_thread(_attach_and_project, db, ...)` -> request dependency closes `db`.
- **Root cause:** Blocking work and DB unit-of-work ownership were moved together to a thread instead of giving each worker a thread-local Session and explicit transaction.
- **Impact:** Environment-dependent ingestion failures, inconsistent document/binding/task state, and difficult-to-reproduce transaction errors.
- **Similar-risk search:** Search all `to_thread`/executor calls for request Sessions and ORM objects crossing thread boundaries.
- **Regression risk:** Splitting sessions can expose an uncommitted dependency between ingestion and projection; transaction boundaries must be explicit.
- **Minimum repair:** Pass scalar identifiers/path into the worker; create/close a fresh Session inside the worker; define ingestion and projection commit/rollback semantics; never share ORM instances across threads.
- **Regression tests:** Concurrent uploads, PostgreSQL upload, injected disconnect/rollback, projection failure after ingestion, request cancellation, and session leak checks.
- **Dependencies:** Migration baseline should be trustworthy before PostgreSQL acceptance, but code repair can be developed independently.
- **Expected files:** `backend/app/api/knowledge.py`, knowledge service/base transaction boundaries as minimally required, concurrency/integration tests.

### MF-STAB-013 - Model Runtime Status Persistence Hides DB Failure

- **Trigger:** Any model load/unload/status transition where `_persist_status` encounters a DB error.
- **Actual behavior:** Every exception is swallowed and no log, metric, or caller-visible diagnostic is emitted; in-memory runtime state can diverge from `models.status`.
- **Call chain:** `ModelRuntimeManager` lifecycle -> `_persist_status` -> `session.get`/commit -> broad `except Exception: return`.
- **Root cause:** “Best effort” persistence has no bounded error taxonomy or observability contract.
- **Impact:** UI/API readiness can report stale state, recovery can make decisions from incorrect persisted status, and operators cannot diagnose the divergence.
- **Similar-risk search:** Workflow `_record_event` and configuration loading also have broad exception suppression; each must be classified by whether failure is allowed and made observable.
- **Regression risk:** Making status persistence fatal after the runtime already loaded/unloaded can create the opposite divergence. The primary operation and compensation policy must be explicit.
- **Minimum repair:** Catch known DB exceptions, rollback, emit structured redacted diagnostics/metric, and return or record a defined “persistence degraded” result without pretending success is fully durable.
- **Regression tests:** commit failure, stale session, missing record, rollback, runtime-operation success with persistence failure, diagnostics emission, and recovery behavior.
- **Dependencies:** None; final acceptance should include observability assertions.
- **Expected files:** `backend/app/services/model_runtime_manager.py`, lifecycle diagnostics/metrics only if using existing facilities, runtime tests.

## 9. P3 Issues, Architecture Risks, and Test Gaps

### MF-STAB-014 - Documentation Drift

README currently claims 866 passed in one location, approximately 1080 tests and four skips in another, and 866 passed/three skips in the branch description. The actual baseline is 1354 passed/three skipped. The services count is still described as 21+, while the current service tree is much larger. Version descriptions mix backend compatibility `2.1`, platform `3.0`, V4.0 planning language, and desktop `0.1.3-beta.1` without a single release-version glossary. Historical documents contain valid old baselines such as 339 tests/14 tables but are not always clearly labeled historical.

Repair only after code gates are stable: update current-state documents, preserve dated historical evidence, and label it as historical rather than rewriting history.

### MF-STAB-015 - Warning Baseline Is Partially Hidden

`pytest.ini` globally ignores the Starlette/httpx deprecation warning class. The current “zero warning” observation therefore means zero visible warnings. Review whether the dependency versions still emit it, remove the filter if obsolete, or track it with an owner and expiry.

### MF-STAB-016 - Parallel Implementations Lack Explicit Ownership

Confirmed parallel paths include legacy and runtime Plugin Managers, `RuntimeRegistry` versus `ModelRuntimeManager`/`RuntimeResolver`, legacy chat versus structured chat turns, and `KnowledgeBase` versus `KnowledgeService`. They are not all bugs, but they increase the chance that fixes apply to one path only. Stabilization requires an ownership/compatibility matrix and tests for each still-public path. Long-term consolidation is deferred to Future Backlog.

### MF-STAB-017 - Circular Dependency in Model/Embedding Services

The static module graph contains one SCC through embedding service, model registry, local importer, runtime adapters, and embedding runtime. No startup failure was observed, but import-order sensitivity and hidden initialization coupling raise regression risk. Do not refactor during the first repair phases unless a concrete fix is blocked by the cycle.

### MF-STAB-018 - Real Integration Coverage Is Environment-Gated

External provider/network, real CPU model, and NVIDIA GPU tests are skipped locally. These are legitimate gates, but a release candidate needs dated evidence from the designated jobs/runners, including failure handling and cancellation, not only import-level mocks.

### MF-STAB-019 - Desktop Coverage Has No Gate

Desktop tests pass at 63% client coverage, but CI only uploads the report. Set a non-decreasing baseline after reviewing meaningful exclusions; do not add a target that encourages low-value line coverage or weaken existing tests.

### MF-STAB-020 - ORM Concentration and High Fan-In

Eighty tables in one model module and broad imports from `models.records`, database, contracts, and config increase migration and import blast radius. This is not a stabilization refactor target. Require migration/schema tests for current fixes; defer domain decomposition to Future Backlog.

## 10. Regression Inventory

The following six issues are tied to previously introduced behavior and are tagged `REGRESSION`:

1. MF-STAB-002: recent desktop/test changes violate existing Ruff gates.
2. MF-STAB-003: Agent Team event sequencing introduced with the team platform work.
3. MF-STAB-004: Agent Team execution treats asynchronous child creation as completion.
4. MF-STAB-005: Workflow cancellation semantics allow later overwrite and orphan child work.
5. MF-STAB-006: runtime plugin import failure falls outside rollback coverage.
6. MF-STAB-008: approval creation omitted the Agent ownership validation already used by goal creation.

No confirmed flaky test was found. Environment-gated skips and the current-checkout Docker permission failure are tracked separately from flakiness.

## 11. Repair Priority and Dependency Order

Do not attempt all fixes in one patch. Use this order:

1. **MF-STAB-001:** seal the Docker build boundary and restore non-root startup; this makes release evidence trustworthy.
2. **MF-STAB-002:** restore Ruff so CI can execute the rest of its required jobs.
3. **MF-STAB-010 then MF-STAB-011:** decide migration compatibility, establish immutable revision checks, and restore ORM/head parity before accepting data-layer changes.
4. **MF-STAB-003:** repair Agent Team event durability first.
5. **MF-STAB-004 and MF-STAB-009:** establish truthful sequential lifecycle and reject unsupported strategies; do not implement new strategies.
6. **MF-STAB-005:** make Workflow cancellation authoritative and propagate it to child Runs.
7. **MF-STAB-006 then MF-STAB-007:** make plugin load atomic, then define truthful mount/unmount behavior.
8. **MF-STAB-008:** enforce approval Agent ownership.
9. **MF-STAB-012:** repair Knowledge Session/thread ownership and validate PostgreSQL concurrency.
10. **MF-STAB-013:** make runtime status persistence failures observable and consistent.
11. Address P3 test/documentation gates only after P0/P1/P2 behavior is stable; do not mix architecture cleanup into bug patches.

## 12. Stabilization Phases and Acceptance Conditions

### Phase S0 - Release Boundary Recovery

Scope: MF-STAB-001 and MF-STAB-002.

Acceptance:

- Ruff passes in both main and desktop scopes.
- A clean and a deliberately restrictive-mode build both start as UID 10001.
- `/healthz` passes from the built image.
- Image inspection contains no local secrets, `.env`, DB files, bytecode caches, test caches, or local artifacts.
- Writable runtime paths remain explicit and limited.

### Phase S1 - Migration Truth

Scope: MF-STAB-010 and MF-STAB-011.

Acceptance:

- An approved compatibility strategy exists for the mutable baseline.
- Revision-boundary tests prove the expected schema delta at each relevant revision.
- Existing representative databases upgrade without data loss.
- Empty PostgreSQL and representative old snapshots upgrade to head.
- `alembic check` reports no operations.
- App import and startup schema verification pass against PostgreSQL head.

### Phase S2 - Agent Team Correctness

Scope: MF-STAB-003, MF-STAB-004, MF-STAB-009.

Acceptance:

- Event sequence uniqueness holds under pending events and concurrent appenders.
- Team state never becomes terminal before every required child Run is terminal.
- Actual child output, failure, and cancellation propagate to team tasks, final result, trace, and task center.
- Only implemented strategies are accepted; unsupported modes fail with a stable contract.
- SQLite and PostgreSQL integration tests pass.

### Phase S3 - Workflow Cancellation and Resource Ownership

Scope: MF-STAB-005.

Acceptance:

- `CANCELLED` cannot be overwritten by a late completion/failure.
- All spawned Workflow tasks are tracked and shut down deterministically.
- Agent child Runs are cancelled on parent cancellation and timeout.
- No inference/tool lease or background task remains after terminal cancellation.
- Restart recovery produces one legal terminal state and consistent trace events.

### Phase S4 - Plugin Lifecycle Integrity

Scope: MF-STAB-006 and MF-STAB-007.

Acceptance:

- Failed load leaves no plugin, scope, tool, alias, or success event behind.
- Retry after failure succeeds when the entry is corrected.
- Mount/unmount contract is truthful, idempotent, and covered through API and manager tests.
- Existing plugin/tool/MCP core tests pass without weakening Policy or confirmation requirements.

### Phase S5 - Data Ownership and Diagnostics

Scope: MF-STAB-008, MF-STAB-012, MF-STAB-013.

Acceptance:

- Orphan/cross-tenant approvals are rejected.
- No request SQLAlchemy Session or ORM object crosses worker-thread boundaries.
- Concurrent PostgreSQL knowledge ingestion has deterministic commit/rollback behavior.
- Runtime status persistence failures are rolled back and visible through existing logs/metrics/diagnostics.

### Phase S6 - Documentation and Final Candidate

Scope: P3 accuracy and final validation only.

Acceptance:

- README current test counts, route counts, versions, directory descriptions, and commands match the candidate.
- Dated historical documents remain intact and are clearly labeled historical where needed.
- Warning policy has an owner and no unexplained global suppression.
- Full backend and desktop tests, lint, compile, dependency audit, Docker, PostgreSQL migrations, OpenAI-compatible API smoke, Agent Runtime, Plugin/Tool/MCP, Workflow, Knowledge, and key regressions pass on the exact candidate SHA.
- External network, real CPU model, and GPU evidence is attached or explicitly blocks the claimed release profile.

## 13. Final Release-Freeze Conditions

Feature development may resume only when all of the following are true on one exact candidate revision:

- P0 = 0 and P1 = 0.
- All retained P2/P3 items have an explicit owner, rationale, and release decision.
- Core startup, desktop startup, and Docker non-root startup pass.
- Full pytest and all required CI jobs pass without deleting, skipping, xfail-marking, or weakening tests.
- Core API and OpenAI-compatible API contract tests pass.
- PostgreSQL migration history, head parity, and representative upgrade fixtures pass.
- Agent Runtime creation/execution/cancellation/recovery and event durability pass.
- Plugin, Tool, MCP, Scheduler, Agent Team, and Workflow core lifecycle tests pass.
- No known severe data consistency, transaction, resource-leak, or startup issue remains.
- Dependency audit has no unaccepted high/critical vulnerability.
- README and release documentation match the measured baseline.
- The release artifact is tied to the tested commit, contains no local secrets/state, and passes artifact-level smoke tests.

**Current result: these conditions are not met. The repository remains in stabilization freeze and is not approved for new feature development.**
