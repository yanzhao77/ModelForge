"""Startup and runtime recovery (V1.9).

Every subsystem already settles its own orphans (downloads → PAUSED, training →
error, agent runs → PROCESS_RESTARTED). This service is the single entry point
that runs them in a defined order and returns a report, plus the two pieces that
were missing:

* **Model registry sweep** — scan the configured model root, register new
  artifacts, mark records whose file disappeared as ``invalid``;
* **Workflow run sweep** — a workflow run only lives inside the process, so a
  non-terminal row after a restart can never finish.

It is intentionally idempotent: running it twice in a row must report zero
changes the second time.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from core.database import SessionLocal
from models.records import PlatformPackage, WorkflowRun


class RecoveryService:
    def __init__(self, db=None):
        self._db = db

    def startup_recovery(self) -> dict:
        """Run every recovery step once and return a machine-readable report."""
        report: dict = {
            "started_at": datetime.datetime.utcnow().isoformat() + "Z",
            "steps": {},
            "ok": True,
        }
        for name, runner in (
            ("models", self._recover_models),
            ("downloads", self._recover_downloads),
            ("training", self._recover_training),
            ("agent_runs", self._recover_agent_runs),
            ("workflow_runs", self._recover_workflow_runs),
            ("api_invocations", self._recover_api_invocations),
            ("runtime", self._recover_runtime),
        ):
            try:
                report["steps"][name] = runner()
            except Exception as exc:  # a failing step must not block startup
                report["ok"] = False
                report["steps"][name] = {"error": type(exc).__name__}
        report["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        from core.cache import invalidate_all

        report["cache_entries_invalidated"] = invalidate_all()
        return report

    # -- steps --------------------------------------------------------------

    def _recover_models(self) -> dict:
        from core.config import settings
        from services.model_registry import ModelRegistry

        with SessionLocal() as session:
            registry = ModelRegistry(session)
            records = registry.list_models()
            invalidated = 0
            for record in records:
                registry.refresh(record, commit=False)
                if record.status == "invalid":
                    invalidated += 1
            backfilled = registry.backfill_capabilities()
            session.commit()
        # Discovery stays a *user* action (`POST /models/scan`): the model root is
        # shared, so registering everything globally at startup would expose one
        # account's files to every other account. Recovery only validates what is
        # already registered and reports how many artifacts are on disk.
        discoverable = 0
        root = Path(settings.model_path)
        if root.is_dir():
            try:
                discoverable = sum(
                    1
                    for entry in root.iterdir()
                    if entry.is_file() and entry.suffix.lower() in {".gguf", ".bin", ".safetensors", ".pt", ".pth"}
                )
            except OSError:
                discoverable = 0
        return {
            "model_root": str(settings.model_path),
            "discoverable_files": discoverable,
            "discovered": 0,
            "discovery": "user-triggered (POST /api/v1/models/scan)",
            "records": len(records),
            "invalid_records": invalidated,
            "capabilities_backfilled": backfilled,
        }

    def _recover_downloads(self) -> dict:
        from services.downloader import get_downloader

        return {"settled": get_downloader().reconcile_orphaned_tasks()}

    def _recover_training(self) -> dict:
        from services.training import get_training_service

        return {"interrupted": get_training_service().reconcile_orphaned_tasks()}

    def _recover_agent_runs(self) -> dict:
        from services.agent_runtime_service import get_agent_runtime

        runtime = get_agent_runtime()
        if runtime is None:
            return {"skipped": "AGENT_RUNTIME_UNAVAILABLE"}
        return {"settled": runtime.reconcile_orphaned_runs()}

    def _recover_workflow_runs(self) -> dict:
        """A workflow run's executor only exists in memory."""
        with SessionLocal() as session:
            rows = (
                session.query(WorkflowRun)
                .filter(WorkflowRun.status.in_(("PENDING", "RUNNING", "WAITING_HUMAN")))
                .all()
            )
            for row in rows:
                row.status = "FAILED"
                row.error = "PROCESS_RESTARTED: workflow run interrupted by a service restart"
                row.finished_at = datetime.datetime.utcnow()
            session.commit()
        return {"settled": len(rows)}

    def _recover_api_invocations(self) -> dict:
        from services.api_platform import reconcile_orphaned_invocations

        with SessionLocal() as session:
            return {"settled": reconcile_orphaned_invocations(session)}

    def _recover_runtime(self) -> dict:
        """Clear in-memory runtime state and report what was loaded before."""
        from services.model_runtime_manager import get_model_runtime_manager

        manager = get_model_runtime_manager()
        instances = manager.instances_payload()
        for instance in list(manager.list_loaded()):
            try:
                manager.resources.release(instance.model_id)
            except Exception:
                continue
        return {
            "previous_instances": len(instances),
            "stale_claims_released": len(instances),
            "max_instances": manager.max_instances,
        }

    # -- diagnostics --------------------------------------------------------

    def hardening_report(self) -> dict:
        """Point-in-time hardening view for the desktop/ops page."""
        from core.cache import cache_snapshot
        from services.migration_preflight import migration_preflight
        from services.model_runtime_manager import get_model_runtime_manager

        manager = get_model_runtime_manager()
        with SessionLocal() as session:
            stalled_workflows = (
                session.query(WorkflowRun)
                .filter(WorkflowRun.status.in_(("PENDING", "RUNNING")))
                .count()
            )
            packages = session.query(PlatformPackage).count()
            try:
                preflight = migration_preflight()
            except Exception as exc:
                preflight = {"ok": False, "error": type(exc).__name__}
        return {
            "cache": cache_snapshot(),
            "runtime": {
                "instances": manager.instances_payload(),
                "queue": manager.queue_snapshot(),
                "max_instances": manager.max_instances,
                "recent_events": manager.recent_events(limit=10),
            },
            "stalled_workflow_runs": stalled_workflows,
            "packages": packages,
            "migration_preflight": preflight,
            "schema_version": 5,
        }


recovery_service = RecoveryService()


def get_recovery_service() -> RecoveryService:
    return recovery_service


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = ["RecoveryService", "get_recovery_service", "recovery_service"]
