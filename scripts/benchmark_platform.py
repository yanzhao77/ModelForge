#!/usr/bin/env python3
"""Baseline benchmark for the ModelForge platform (V1.9).

Measures the operations that regress most often, without requiring a GPU, a
real model or network access:

* model registry query + metadata refresh;
* embedding batch (hash provider) with cold vs warm cache;
* workflow engine sequential run (echo LLM) and a 20-node chain;
* startup recovery pass.

Usage::

    python scripts/benchmark_platform.py [--json]

The numbers are machine-specific; the point is to detect a *change* between two
runs (keep a copy of the JSON as a baseline).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))


def _prepare_env() -> str:
    tmp = tempfile.mkdtemp(prefix="mf_bench_")
    os.environ.setdefault("DATABASE_PATH", os.path.join(tmp, "bench.db"))
    os.environ.setdefault("MODEL_PATH", os.path.join(tmp, "models"))
    os.environ.setdefault("MODEL_DIR", os.environ["MODEL_PATH"])
    os.environ.setdefault("DATA_DIR", os.path.join(tmp, "data"))
    os.makedirs(os.environ["MODEL_PATH"], exist_ok=True)
    return tmp


def _time(label: str, func) -> dict:
    started = time.perf_counter()
    result = func()
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"name": label, "duration_ms": duration_ms, "result": result}


def _time_async(label: str, coro_factory) -> dict:
    started = time.perf_counter()
    result = asyncio.run(coro_factory())
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"name": label, "duration_ms": duration_ms, "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the raw report as JSON")
    args = parser.parse_args()

    tmp = _prepare_env()
    from core.cache import embedding_cache, invalidate_all
    from core.database import Base, SessionLocal, engine, init_db
    from services.embedding_service import embed_texts
    from services.model_registry import ModelRegistry
    from services.recovery_service import RecoveryService
    from services.workflow_engine import WorkflowEngine, WorkflowExecution

    init_db()
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    report: list[dict] = []

    asset = Path(os.environ["MODEL_PATH"]) / "bench.gguf"
    asset.write_bytes(b"GGUF" + b"0" * 1024)
    registry = ModelRegistry(session)
    report.append(_time("model.register", lambda: {"id": registry.register(name="bench", provider="local", path=str(asset), user_id=1).id}))
    report.append(_time("model.list", lambda: {"count": len(registry.list_models(1))}))
    report.append(_time("model.refresh", lambda: {"status": registry.refresh(registry.list_models(1)[0]).status}))

    texts = [f"benchmark text {index} with some words" for index in range(64)]
    invalidate_all()
    report.append(_time("embedding.cold", lambda: {"dimensions": embed_texts(session, 1, texts)["dimensions"]}))
    report.append(_time("embedding.warm", lambda: {"dimensions": embed_texts(session, 1, texts)["dimensions"]}))
    report.append({"name": "embedding.cache", "duration_ms": 0, "result": embedding_cache.snapshot()})

    definition = {
        "entry": "start",
        "nodes": [
            {"id": "start", "type": "input", "next": "ask"},
            {"id": "ask", "type": "llm", "config": {"prompt": "{{input.q}}"}, "next": "done"},
            {"id": "done", "type": "output", "config": {"value": "{{nodes.ask.output}}"}},
        ],
    }

    async def run_short():
        execution = WorkflowExecution(run_id="bench", definition=definition, input={"q": "hi"}, variables={})
        await WorkflowEngine().execute(execution)
        return {"output": execution.output}

    report.append(_time_async("workflow.sequential", run_short))

    long_definition = {
        "entry": "n0",
        "nodes": [{"id": "n0", "type": "input", "next": "n1"}]
        + [
            {"id": f"n{i}", "type": "llm", "config": {"prompt": "step"}, "next": f"n{i + 1}"}
            for i in range(1, 20)
        ]
        + [{"id": "n20", "type": "output", "config": {"value": "done"}}],
    }

    async def run_long():
        execution = WorkflowExecution(run_id="bench-long", definition=long_definition, input={}, variables={})
        await WorkflowEngine().execute(execution)
        return {"nodes": len(execution.nodes)}

    report.append(_time_async("workflow.20_nodes", run_long))
    report.append(_time("recovery.pass", lambda: _recovery_summary(RecoveryService().startup_recovery())))
    session.close()

    payload = {"environment": {"python": sys.version.split()[0], "platform": sys.platform, "tmp": tmp}, "results": report}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        width = max(len(item["name"]) for item in report)
        print(f"ModelForge platform benchmark (python {sys.version.split()[0]}, {sys.platform})")
        for item in report:
            print(f"  {item['name']:<{width}}  {item['duration_ms']:>9.2f} ms   {json.dumps(item['result'], ensure_ascii=False)[:70]}")
    return 0


def _recovery_summary(report: dict) -> dict:
    steps = report.get("steps") or {}
    return {"ok": report.get("ok"), "steps": {key: value for key, value in steps.items()}}


if __name__ == "__main__":
    raise SystemExit(main())
