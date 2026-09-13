# V1.9 — Production Hardening

原则：少加功能，重点提高稳定性。

## Recovery

`services/recovery_service.py` 在启动时（`lifespan`）执行一次**有序、幂等**的恢复：

```text
models         扫描模型根目录 → 注册新文件 → 缺失文件的记录置 invalid → 回填 capabilities
downloads      downloader.reconcile_orphaned_tasks()（PAUSED/CANCELLED）
training       training.reconcile_orphaned_tasks()（error + 保留日志）
agent_runs     runtime.reconcile_orphaned_runs()（PROCESS_RESTARTED）
workflow_runs  非终态运行置 FAILED(PROCESS_RESTARTED)（执行器只在内存）
api_invocations  reconcile_orphaned_invocations()
runtime        释放陈旧资源记账，报告重启前实例数
```

报告写入 `app.state.recovery_report`，并可通过 `POST /api/v1/system/recovery`
重新执行；`GET /api/v1/system/hardening` 汇总缓存统计、运行时实例/队列、
停滞的工作流运行数、包数量与迁移预检。

另外：Agent Run 的推理租约现在在运行进入终态的同一时刻释放（此前要等事件
落盘），客户端观察到 `COMPLETED` 后立刻发起下一次运行不会再遇到
`RUNTIME_BUSY`。

## Cache

`core/cache.py`：`TTLCache`（有界 + TTL + 命名空间失效 + 命中率统计）。

* `embedding_cache`（900s）：按 provider+文本哈希缓存向量；
* `retrieval_cache`（120s）：预留给检索结果；
* 恢复流程与模型/嵌入模型变更会调用 `invalidate_all()`。

## Benchmark

```powershell
.venv\Scripts\python.exe scripts\benchmark_platform.py [--json]
```

覆盖：模型注册/查询/刷新、embedding 冷热路径、工作流 3 节点与 20 节点链、
启动恢复。输出机器可读 JSON，便于与基线对比。

## Upgrade / Migration

* SQLite：`core/database.py::_MIGRATIONS` 增量执行（0001–0005）；
* PostgreSQL：`alembic upgrade head`（0001–0005，最新 `0005_platform_tables`）；
* 迁移预检：`services/migration_preflight.py`（既有），在 hardening 报告中汇总。

## 验收

| 验收项 | 证据 |
|---|---|
| Runtime Recovery | `tests/test_hardening_v19.py::test_startup_recovery_settles_workflow_runs_and_models` |
| Training Recovery | 复用 `TrainingService.reconcile_orphaned_tasks`（既有用例） |
| Startup Recovery | `test_startup_recovery_settles_workflow_runs_and_models`（幂等：第二次 0 变更） |
| Performance Benchmark | `test_benchmark_script_reports_results` |
| Memory Leak Test | `tests/test_multi_model_runtime.py::test_load_unload_cycles_release_every_instance_and_claim` |
| Migration Test | `tests/test_migration_preflight.py` + `tests/test_phase2_database.py` |
| Upgrade Test | 迁移链路 0001→0005（Alembic + SQLite 增量） |
| 跨平台回归 | 后端全量 + 桌面端套件（Windows 本机；CI 覆盖 Linux/macOS 构建脚本） |
