# V1.1 → V2.0 现状审计（先读后改）

> 依据 `docs/plan/MODELFORGE_V1.1_TO_V2.0_COMPLETE_PLAN.md` 第二十六节
> "先读后改、优先复用已有 Service、不删除现有功能"，在动手前先确认每个版本的
> 已有能力与缺口。本文件随各版本开发逐步更新。

## 总体判断

仓库里已经存在大量 V1.1/V1.4/V1.6/V1.8 的底座（Agent Runtime、Tool/Policy、
Memory、Knowledge、Task Center、Plugin、Audit、Encrypted Provider Keys）。
因此本次路线不是"从零实现"，而是**按路线图补齐缺口、统一入口、补齐验收项**。

## V1.1 Agent Runtime

| 路线图要求 | 现状 | 本次处理 |
|---|---|---|
| AgentDefinition | `runtime.types.AgentConfig` + `agents` 表（无 `model_id`） | 增加 `model_id` 字段与迁移 |
| AgentRun / AgentMessage / ToolCall / ToolResult | `RunRecord`、`AgentEventRecord`、`runtime.models.base.ToolCall/ModelResult`、`ToolResult` | 复用；补 Trace 组装 |
| Agent 不直接实例化 Runtime | `agent_runtime_service` 默认走 Ollama/远程 provider | 新增 `RuntimeBackedProvider`，local `model_id` 走 ModelRuntimeManager |
| Tool System（5 个工具 + 权限 + schema） | `ToolRegistry` + 5 个内置工具（filesystem.read/code.search/shell.execute/web.search/knowledge.search） | 复用；补权限词汇别名 |
| Permission 分级 | `PermissionLevel`（READ/FILESYSTEM_READ/WRITE/EXECUTE/NETWORK/SYSTEM/ADMIN） | 增加 READ_ONLY/FILESYSTEM_WRITE/PROCESS_EXECUTE/DANGEROUS 映射 |
| Trace | 事件已持久化，无 trace 端点 | 新增 `AgentTrace` + `GET /agents/runs/{id}/trace` |
| REST `/api/v1/agents*` | 现有 `/agent/create`、`/agent/list`、`/agent/{name}/chat`、`/agent/runs` | 新增 `/api/v1/agents` 规范入口（不改旧路由） |
| Agent UI | `pages/agent_page.py`、`agent_workbench_page.py`、`run_timeline.py` | 在 Agent 页接入 Trace |

## V1.2 Multi-Runtime

| 要求 | 现状 | 本次处理 |
|---|---|---|
| `RuntimeAdapter` 抽象 | `RuntimeEngine`（load/chat/stop），无 status/capabilities | 新增 `RuntimeAdapter` 协议 + 4 个适配器 |
| llama.cpp / Transformers / Remote | `LocalRuntime`（两者合一）、`OpenAIRuntime`、`OllamaRuntime` | 拆分为 llama-cpp / transformers / remote_openai / ollama 适配器 |
| Runtime Resolver | 无 | 新增 `RuntimeResolver`（supported/preferred） |
| ModelRecord 增加 supported_runtimes/preferred_runtime | 无 | 增加列 + 迁移 + 推导 |
| Remote 模型进入 Registry | 远程 provider 独立存在（加密存储） | Registry 暴露 remote 条目（`source=remote`） |
| Runtime Health | 无 | `GET /api/v1/runtimes`、`/{id}/health` |

## V1.3 Multi-Model & Resource Manager

| 要求 | 现状 | 本次处理 |
|---|---|---|
| 多 Runtime Instance | V1.0 为单实例 | 改为多实例 + 上限 + 兼容 `get_current()` |
| Resource Manager（RAM/VRAM/CPU/Disk） | 无 | 新增 `ResourceManager`（psutil 可选，降级采样） |
| LRU（不卸载 busy 实例） | 无 | 资源不足时按 last_used 驱逐空闲实例 |
| Load Queue + Priority | 无 | 新增等待队列 + HIGH/NORMAL/LOW |
| 内存泄漏测试 | 无 | 新增循环 load/unload 用例 |

## V1.4 Knowledge / RAG

| 要求 | 现状 | 本次处理 |
|---|---|---|
| KnowledgeBase / Document / Chunk / Retrieval | `KnowledgeDocument`、`KnowledgeChunk`、`KnowledgeCollection` | 复用 + 新增集合 CRUD 与检索模式 |
| PDF/TXT/MD/DOCX/CSV/代码 | PDF/MD/TXT/代码 | 补 DOCX/CSV 文本抽取 |
| Embedding 模型进 Registry | 无 | 增加 `EMBEDDING` 能力推导与 embedding runtime |
| 检索 semantic/keyword/hybrid/rerank | semantic（TF-IDF 词袋） | 增加 keyword/hybrid/rerank |
| Agent RAG | `knowledge_config.collection_ids` + `KBKnowledgeProvider` | 复用并补 API |
| 索引进度 | 无 | 接入统一任务中心 |

## V1.5 Workflow

整体缺失。新增 Workflow/Node/Edge/Run/Event、执行引擎
（sequential/parallel/condition/loop/retry/timeout/approval）、
多 Agent 编排、API 与桌面页面。

## V1.6 Developer Platform

| 要求 | 现状 | 本次处理 |
|---|---|---|
| OpenAI 兼容扩展（embeddings/agents/knowledge/workflows） | 仅 /v1/models、/v1/chat/completions | 新增 `/v1/embeddings`、`/v1/agents/*`、`/v1/knowledge/*`、`/v1/workflows/*` |
| Python SDK | 无 | 新增 `sdk/python/modelforge` |
| Plugin System + Permission | `runtime/plugins/*`、`services/plugin_manager.py`、`api/plugin.py` | 补权限展示与示例插件 |
| Developer Docs / Examples | `PLUGIN_ARCHITECTURE.md` | 新增开发者文档与示例 |

## V1.7 Package / Marketplace Foundation

整体缺失。新增 package manifest、export/import、version、dependency、
license metadata，覆盖 model/agent/tool/workflow 四类包。

## V1.8 Observability / Evaluation / Security

| 要求 | 现状 | 本次处理 |
|---|---|---|
| Trace（Trace/Span/Event） | Agent 事件流 | 新增统一 Trace API（Agent/Workflow/Tool/RAG/Model） |
| Metrics（TTFT/tokens/sec/资源） | `runtime/metrics.py`、`model_metrics.py` | 补 TTFT/tokens-per-second 与资源指标 |
| Evaluation | 无 | 新增 EvaluationDataset/Run/Result + A/B 对比 |
| Secret Manager | 加密存储（Fernet + 本机密钥文件） | 新增 keychain 优先的实现与文档 |
| Tool Sandbox / Audit | 策略引擎 + `services/audit_log.py` | 补沙箱约束与安全审计文档 |

## V1.9 Production Hardening

| 要求 | 现状 | 本次处理 |
|---|---|---|
| Training Recovery | `reconcile_orphaned_tasks` | 复用 |
| Runtime Recovery | 部分（加载失败清理） | 新增崩溃检测/资源与租约释放/可重载 |
| Startup Recovery | 下载/训练/项目调用结算 | 扩展为统一启动恢复（扫描模型、校验文件、清理陈旧运行时） |
| Performance Benchmark | 无 | 新增 `scripts/benchmark_platform.py` |
| Cache（含失效策略） | 部分（searcher cache、kb vocab） | 新增统一 TTL 缓存用于元数据/检索/嵌入 |
| Migration/Upgrade | `migration_preflight` | 扩展为升级检查清单 |

## V2.0 Platform

| 要求 | 现状 | 本次处理 |
|---|---|---|
| Dashboard | 无独立 dashboard API | 新增 `GET /api/v1/dashboard` + 桌面首页数据 |
| Unified Task Center | `task_service` + `TaskRecord` | 扩展任务类型（embedding/index/workflow） |
| Unified Events | Agent/Task 事件 | 新增统一事件查询 |
| ID 规范 / 权限目录 | 部分 | 文档化 + 校验用例 |
| E2E（Model/Agent/RAG/Training/Workflow/External API） | 部分 | 新增平台 E2E 用例 |

## 跨版本原则落地

1. Model Registry 仍是唯一模型事实来源（V1.2 把远程模型也纳入其中）；
2. Runtime Manager 是唯一执行入口（Agent 通过 `RuntimeBackedProvider` 间接调用）；
3. Agent 只持有 `model_id`，不接触模型路径；
4. UI 只调用 API，不直接操作 Runtime；
5. Tool 必须经过 PolicyEngine + ToolExecutor（复用现有实现）。

---

## 实施结果（V1.1 → V2.0 全部完成）

| 版本 | 交付 | 主要文件 | 用例 |
|---|---|---|---|
| V1.1 Agent Runtime | AgentDefinition `model_id`、RuntimeBackedProvider、Trace、`/api/v1/agents` | `services/agent_model_provider.py`、`agent_trace.py`、`agent_service.py`、`agent_run_service.py`、`api/agents.py`、`tools/base.py` | `tests/test_agent_definition_api.py` |
| V1.2 Multi-Runtime | 适配器目录、Resolver、注册表 runtime 列、`/api/v1/runtimes` | `services/runtimes/adapters.py`、`runtime_resolver.py`、`api/runtimes.py` | `tests/test_multi_runtime.py` |
| V1.3 Multi-Model | 多实例、LRU、队列、优先级、资源管理 | `services/resource_manager.py`、`model_runtime_manager.py`、`api/runtime.py` | `tests/test_multi_model_runtime.py` |
| V1.4 Knowledge/RAG | DOCX/CSV、四种检索模式、知识库 CRUD、Embedding Provider、索引进度 | `services/knowledge_service.py`、`embedding_service.py`、`knowledge_base.py`、`api/knowledge.py` | `tests/test_knowledge_rag_v14.py` |
| V1.5 Workflow | 引擎 + 数据模型 + API + 桌面页 | `services/workflow_engine.py`、`workflow_service.py`、`workflow_trace.py`、`api/workflows.py`、`pages/workflow_page.py` | `tests/test_workflow_engine.py`、`test_workflow_api.py` |
| V1.6 Developer Platform | OpenAI 扩展端点、Python SDK、示例、权限目录 | `api/developer_api.py`、`sdk/python/`、`examples/` | `tests/test_developer_platform.py` |
| V1.7 Packages | 四类包导入/导出、版本、依赖、许可证 | `services/package_service.py`、`api/packages.py` | `tests/test_packages_v17.py` |
| V1.8 Observability | Trace 索引、Metrics、Evaluation、SecretStore | `services/observability_service.py`、`evaluation_service.py`、`core/secret_store.py`、`api/observability.py` | `tests/test_observability_v18.py` |
| V1.9 Hardening | 统一恢复、TTL 缓存、基准脚本 | `services/recovery_service.py`、`core/cache.py`、`scripts/benchmark_platform.py` | `tests/test_hardening_v19.py` |
| V2.0 Platform | Dashboard、统一事件、总览页、E2E | `api/dashboard.py`、`pages/dashboard_page.py` | `tests/test_platform_e2e.py` |

版本号：本仓库交付 `V1.1 → V2.0` 的实现，迁移链回到
`0001 → 0005`（Alembic）与 `schema_migrations 0001 → 0005`（SQLite）。
