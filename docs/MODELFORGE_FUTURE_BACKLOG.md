# ModelForge Future Backlog

> Created from the 2026-09-14 Release Stabilization Audit at revision `733f0d7`.
> This file contains work intentionally excluded from stabilization because it adds capability or performs broad architectural redesign. Confirmed P0/P1/P2 defects remain in `MODELFORGE_STABILIZATION_PLAN.md` and must not be deferred here.

## Backlog Rules

- Do not start these items while any P0 or P1 remains open.
- A backlog item may begin only after the release-freeze conditions are met on an exact candidate SHA.
- Each item requires a separate design review, migration/compatibility plan, and scoped acceptance criteria.
- Stabilization fixes may establish truthful rejection or compatibility boundaries; they must not implement these future capabilities implicitly.

## FB-001 - Implement Additional Agent Team Strategies

- **Problem to solve:** Product/API design names `PARALLEL`, `PIPELINE`, `HIERARCHICAL`, `DELEGATION`, and `CONSENSUS`, but the current implementation only has sequential execution.
- **Why not now:** Implementing orchestration semantics, concurrency, merge rules, cancellation, recovery, and trace contracts is new functionality and would materially increase stabilization risk. The stabilization fix is to expose only truthful supported behavior.
- **When appropriate:** After sequential Team execution, child lifecycle, cancellation, recovery, and PostgreSQL event durability are stable and have production evidence.

## FB-002 - Consolidate Plugin Management Architecture

- **Problem to solve:** Legacy `services/plugin_manager.py` and runtime `runtime/plugins/manager.py` serve different compatibility and lifecycle roles, increasing duplicated policy and state risk.
- **Why not now:** Replacing either path changes startup/API compatibility and plugin lifecycle architecture. Current confirmed lifecycle bugs can be repaired locally without a migration.
- **When appropriate:** After plugin load/mount/unmount regression tests are stable, public compatibility consumers are inventoried, and a deprecation window is approved.

## FB-003 - Consolidate Model Runtime Routing

- **Problem to solve:** `RuntimeRegistry`, `ModelRuntimeManager`, and `RuntimeResolver` divide model selection, engine ownership, and status reporting across overlapping paths.
- **Why not now:** A unified runtime authority changes core model loading and provider contracts. Stabilization should only repair proven state/error defects and add cross-path contract tests.
- **When appropriate:** After local, remote, OpenAI-compatible, Agent, desktop, and recovery behavior is frozen and a compatibility matrix identifies every caller.

## FB-004 - Converge Legacy Chat and Structured Chat Turns

- **Problem to solve:** Legacy chat/stream endpoints and structured `/chat/turns` maintain overlapping execution and persistence semantics.
- **Why not now:** Removing or redirecting a public chat path is an API migration and can regress desktop and SDK clients. No broad chat rewrite is required for the confirmed stabilization defects.
- **When appropriate:** After client usage telemetry or a complete caller inventory exists, structured turns cover all retained behavior, and an explicit version/deprecation policy is approved.

## FB-005 - Decompose the Monolithic ORM Module

- **Problem to solve:** Approximately 80 tables are defined in one high-fan-in module, increasing import, ownership, and migration review cost.
- **Why not now:** File/module decomposition has a large change surface without directly fixing a confirmed release blocker. It could obscure migration fixes and generate unrelated churn.
- **When appropriate:** After migration history and schema parity are stable, with one mechanical domain-by-domain plan that guarantees identical metadata and imports.

## FB-006 - Remove the Model/Embedding Circular Dependency

- **Problem to solve:** Embedding service, model registry/importer, adapter catalog, and embedding runtime form a circular module dependency.
- **Why not now:** No current startup failure is attributed to the cycle, and boundary extraction would be architectural refactoring.
- **When appropriate:** When a concrete ownership boundary is designed and protected by import, provider-selection, and embedding regression tests, preferably before the next model-runtime expansion.

## FB-007 - Design Multi-Instance Durable Execution Ownership

- **Problem to solve:** Scheduler, Workflow, Plugin, and some background execution state is process-local; server multi-instance ownership, lease renewal, and failover are not uniformly defined.
- **Why not now:** Distributed coordination, durable queues, and worker ownership are new runtime architecture, not a minimum fix for current single-process cancellation defects.
- **When appropriate:** After single-process task tracking/cancellation/recovery is correct, deployment requirements explicitly include multiple workers/instances, and a persistence/lease design has been reviewed.

## FB-008 - Establish a Unified Product Version Contract

- **Problem to solve:** Backend compatibility version, platform edition, OpenAPI version, desktop version, and roadmap generation labels are different concepts and are easily confused in documentation and clients.
- **Why not now:** Adding or changing machine-readable version fields is an API/product contract change. Stabilization can document the current meanings without changing responses.
- **When appropriate:** Before the next externally versioned release or SDK contract revision, with backward-compatible fields and a migration guide.
