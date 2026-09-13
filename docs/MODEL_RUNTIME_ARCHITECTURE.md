# ModelForge 统一模型运行时架构（Phase 0 交付物）

> 本文对应 `docs/plan/MODELFORGE_MODEL_RUNTIME_TASK_PLAN.md`（以下简称"任务书"）
> 的 Phase 0。它记录改造前的真实调用链、改造后的目标链路，以及本次落地的
> 模块边界。编写本文时以仓库现有代码为准，不做"推倒重来"式重构。

## 1. 改造前的真实链路

### 1.1 模型生命周期

```
POST /api/v1/models/download      → Downloader 落盘（models/<repo>/…）
                                  ↓（结束）
                             没有注册步骤

POST /api/v1/models/scan          → ModelManager.scan() 写 ModelRecord
POST /api/v1/models/install       → ModelManager.install() 写 ModelRecord
```

问题：

* 下载完成后模型中心看不到该模型，需要用户手动扫描；
* `ModelRecord.status` 只有 `available` 一个语义，文件被删除后仍显示为可用；
* 没有 capabilities 概念：训练页把所有 `ModelRecord` 都当成潜在 Base Model，
  纯 GGUF 推理模型也会出现在训练列表里。

### 1.2 运行时链路

```
Chat UI ──model 名称──▶ POST /api/v1/chat
                          ↓
                     ChatService.run_chat()
                          ↓
                     RuntimeRegistry.get()   # 默认 Ollama
                          ↓
                     OllamaRuntime / LocalRuntime

Runtime UI ──model 名称──▶ POST /api/v1/runtime/start
                          ↓
                     RuntimeRegistry.get().load(model)
```

问题：

* `RuntimeRegistry._create("local")` 构造的是 `LocalRuntime()`（`model_path=None`），
  引擎内部并不知道要加载哪个文件；`model_id` 无法解析到磁盘路径；
* 聊天、RAG、运行时页、OpenAI 兼容 API 各自持有"模型"概念，没有共享实例；
* 没有 load/unload 状态机，也没有"同一时刻只有一个本地模型"的约束。

### 1.3 训练链路

```
Training UI ──base_model 文本──▶ POST /api/v1/train/start
                                    ↓
                              TrainingService.start()
                                    ↓
                              subprocess(training_jobs.py)
                                    ↓（完成）
                   POST /api/v1/train/{id}/register-model
                                    ↓
                              ModelManager.install(format=…)
```

问题：

* Base Model 依赖用户在任意文本输入，无法追溯来源；
* 训练产物注册后没有 capabilities，模型中心无法判断它能不能直接聊天
  （LoRA Adapter 实际上必须搭配 Base Model）。

## 2. 改造后的目标链路

```
                    Model Registry（唯一事实来源）
                     backend/app/services/model_registry.py
                              │
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
   Model Center          Runtime Manager       Training Service
   /api/v1/models        model_runtime_manager /api/v1/train
        │                     │                     │
        │             RuntimeInstance               │
        │             (in-memory, 单实例)            │
        │                     │                     │
        └──────────────┬──────┴──────────┬──────────┘
                       ↓                 ↓
                     Chat            OpenAI API
              /api/v1/chat       /v1/chat/completions
```

关键对象：

| 对象 | 位置 | 职责 |
|---|---|---|
| ModelRecord | `models/records.py` | 磁盘模型资产（持久化）：id/name/capabilities/metadata/status |
| ModelRegistry | `services/model_registry.py` | 查询、能力推导、路径解析、注册、默认模型 |
| ModelResolver | `services/model_resolver.py` | 把 `model_id` / 名称 / 别名解析回 ModelRecord |
| ModelRuntimeManager | `services/model_runtime_manager.py` | 唯一加载入口，持有单个 RuntimeInstance |
| RuntimeInstance | 同上（dataclass） | 已加载实例：instance_id/model_id/runtime/状态/参数 |

## 3. 现有代码审计结论（Phase 0 检查项）

| 现有实现 | 结论 | 本次处理 |
|---|---|---|
| `services/model_manager.py` | 持久化原语（scan/install/remove/info） | **保留**，被 ModelRegistry 复用 |
| `services/runtime_registry.py` | Ollama / 远程 provider 的惰性后端 | **保留**，作为未注册模型（Ollama tag 等）的兼容路径 |
| `services/runtimes/local_runtime.py` | GGUF / Transformers 本地推理 | **增强**：支持 `n_gpu_layers` / `n_threads` 与增量 `stream_chat` |
| `services/model_readiness_service.py` | 用户级可用性快照 | **改造**：按 ready 状态 + 文件存在性判定目标 |
| `services/chat_service.py` | Session/Memory/History/Metrics | **保留**，新增按 `model_id` 走 RuntimeManager 的分支 |
| `services/training.py` | 子进程训练 + 产物注册 | **改造**：支持 `base_model_id`、能力校验、产物 capability |
| `services/downloader.py` | 分片续传下载 | **保留**，完成时调用 Registry 注册 |
| `api/openai_api.py` | /v1/chat/completions | **改造**：先走 ModelResolver → RuntimeManager，未命中回落原有后端 |

明确未删除：ModelManager、TrainingService 的子进程模型、Resource Lease、
Session/Memory/History、Dataset/LoRA 配置、下载续传与完整性校验。

## 4. 本次落地清单

### 新增文件

| 文件 | 作用 |
|---|---|
| `backend/app/services/model_capabilities.py` | 能力与状态词表、格式→能力推导规则 |
| `backend/app/services/model_metadata.py` | GGUF 头部 / HF `config.json` 的轻量元数据读取 |
| `backend/app/services/model_registry.py` | ModelRegistry + 统一查询/注册 |
| `backend/app/services/model_resolver.py` | model_id / 名称 / 别名解析 |
| `backend/app/services/model_runtime_manager.py` | RuntimeInstance + 单实例运行时管理器 |
| `backend/alembic/versions/0003_model_runtime.py` | PostgreSQL 迁移 |

### 修改文件

`models/records.py`（ModelRecord 扩展）、`core/database.py`（SQLite 增量迁移）、
`core/api_contracts.py`（problem 支持 details）、`api/models.py`、`api/runtime.py`、
`api/chat.py`、`api/train.py`、`api/openai_api.py`、`api/tasks.py`、
`services/chat_service.py`、`services/training.py`、`services/downloader.py`、
`services/model_readiness_service.py`、`services/inference_errors.py`、
`services/runtimes/local_runtime.py`，以及桌面端
`api_client/client.py`、`pages/models_page.py`、`pages/chat_page.py`、
`pages/runtime_page.py`、`pages/training_page.py`。

## 5. 数据迁移策略

1. **SQLite**：`core/database.py` 的 `_MIGRATIONS` 追加 `0004_model_registry_capabilities`，
   只对确实缺列的库执行 `ALTER TABLE models ADD COLUMN …`，并创建
   `ix_models_status` / `ix_models_base_model_id` 索引。
2. **PostgreSQL**：`alembic upgrade head` 走 `0003_model_runtime`，用
   `batch_alter_table` 加列，再按 `format` 回填 `capabilities`。
3. **旧数据兼容**：启动后 `ModelRegistry.backfill_capabilities()` 可为
   `capabilities IS NULL` 的旧行补齐；无法判断时统一给 `INFERENCE`，
   绝不猜测 `TRAINING`。

## 6. 第一阶段的明确边界

* 只支持一个活跃本地运行时（单实例），切换模型 = 先卸载再加载；
* 不做 LRU、不做多模型并存、不做显存调度；
* LoRA Adapter 只注册与展示，不实现 Base + Adapter 挂载（因此不声明 `CHAT`）；
* 事件同步第一阶段用轮询（运行时页 1.5s），SSE/WebSocket 留待后续版本。

以上边界与任务书 `#50 不做的事情`、`#65 第一阶段 Runtime 实现选择` 一致。
