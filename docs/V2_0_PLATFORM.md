# V2.0 — ModelForge Local AI Platform

V2.0 不是"再加几个页面"，而是把 Models / Chat / Agents / Knowledge / Training /
Workflows / Tools / Plugins / Runtime / API / SDK / Evaluation / Trace / Task
统一到同一套底座：

```text
Model Registry（唯一模型事实来源）
        │
Runtime Manager（唯一执行入口：多实例 / 多适配器 / LRU / 队列）
        │
Chat · Agent · Workflow · Training · OpenAI API · Python SDK
        │
Task Center · Trace · Metrics · Evaluation · Packages · Plugins
```

## 平台聚合

| 能力 | 端点 | 说明 |
|---|---|---|
| Dashboard | `GET /api/v1/dashboard` | 系统状态、已加载模型、资源、最近会话/Agent Run/训练、知识库、工作流、错误、任务汇总 |
| Unified Events | `GET /api/v1/events?kind=runtime|agent|workflow|task` | 跨子系统的统一事件流（按时间排序） |
| Unified Task Center | `GET /api/v1/tasks`（既有） | 下载 / 训练 / 知识索引 都投影为任务 |
| Trace | `GET /api/v1/traces`、`/traces/{id}` | Agent 与 Workflow 统一形状 |
| Metrics | `GET /api/v1/metrics/overview`、`/metrics/resources` | 延迟、tokens/sec、资源 |
| Evaluation | `/api/v1/evaluations...` | 数据集、运行、A/B 对比 |

桌面端新增「总览」页（导航第二项）：系统/运行时/资源/任务卡片 + 最近活动与错误。

## 数据模型（V2.0 全景）

```text
models(registry)          runtimes(adapter 目录)   runtime_instances(内存)
agents                    agent_runs               agent_events
workflows                 workflow_runs            workflow_run_events
knowledge_documents       knowledge_chunks         knowledge_collections
datasets                  train_tasks              task_records/events/outbox
platform_packages         evaluation_datasets      evaluation_runs
remote_provider_configs   operation_audits         users/sessions/messages/memories
```

## ID 规范

跨模块关联统一使用 ID，禁止用名称/文件名/路径当业务键：

```text
model_id · runtime_id · instance_id · agent_id · run_id · tool_id
knowledge_id · document_id · workflow_id · task_id · artifact_id
package_id · plugin_id · trace_id · evaluation_id
```

已落实的检查：Agent 只持有 `model_id`；模型 API 返回 `model_id`；训练使用
`base_model_id`；工作流节点引用 `agent_id`/`model_id`/`tool` 名称（工具名来自
ToolRegistry，是受控枚举而非路径）。

## 权限目录

```text
MODEL_READ · MODEL_WRITE · RUNTIME_CONTROL · CHAT · AGENT_RUN · TOOL_EXECUTE
FILE_READ · FILE_WRITE · NETWORK · PROCESS_EXECUTE · TRAINING
KNOWLEDGE_READ · KNOWLEDGE_WRITE · PLUGIN_INSTALL
```

映射到既有强制点：`/api/v1/models*`（MODEL_READ/WRITE）、`/api/v1/runtime*` 与
`/models/{id}/load`（RUNTIME_CONTROL + 推理租约）、`ToolExecutor` + `PolicyEngine`
（TOOL_EXECUTE/NETWORK/PROCESS_EXECUTE/FILE_*）、插件安装需运行时管理员
（PLUGIN_INSTALL）、知识库/评估/包按用户隔离（KNOWLEDGE_*）。

**核心原则**：LLM ≠ 可信代码。所有 Shell / Python / 网络 / 文件写入都必须经过
Permission → Policy → Executor → Audit。

## 测试体系

```text
Unit → Service → API → Runtime → Integration → E2E → Performance → Security
```

| E2E 链路 | 用例 |
|---|---|
| Model：注册 → 加载 → 对话 → 卸载 | `test_platform_e2e.py::test_chain_model_lifecycle` |
| Agent：模型 → Agent → Tool → Memory → Final | `test_chain_agent_tool_memory` |
| RAG：文档 → 索引 → 检索 → 回答 | `test_chain_rag_document_to_answer` |
| Training：Base → Dataset → 训练 → 产物 → 注册 → 加载 → 对话 | `test_chain_training_artifact_back_to_chat` |
| Workflow：输入 → Planner → 并行研究/草稿 → 条件 → 输出 | `test_chain_workflow_and_external_api` |
| External API：/v1/models → /v1/chat/completions → Runtime → Response | 同上 |
| Platform：Dashboard + Unified Events | 同上 |

## V2.0 Definition of Done 对照

| 领域 | 状态 |
|---|---|
| Model（Registry/Lifecycle/Capability/Download/Install/Load/Unload/Multi Model） | ✅ |
| Runtime（Manager/Adapter/llama.cpp/Transformers/Remote/Resource/LRU/Recovery） | ✅（Ollama 适配器随附，MLX/vLLM 为后续） |
| Chat（Local/Remote/Streaming/Session/Memory） | ✅ |
| Agent（Definition/Runtime/Tools/Permission/Memory/RAG/Trace/Evaluation） | ✅（Evaluation 通过 EvaluationService 覆盖 Agent 与 Workflow） |
| Knowledge（Base/Document/Chunk/Embedding/Vector Search/Retrieval/RAG） | ✅（内置向量索引；Qdrant 为后续替换项） |
| Training（Dataset/Base/LoRA/Task/Artifact/Registration/Evaluation/Deployment） | ✅（Deployment = 注册后可 Load/Chat/Agent/API） |
| Workflow（Workflow/Node/Edge/Sequential/Parallel/Condition/Loop/Retry/Approval/Multi-Agent） | ✅（Node Graph Editor 为后续） |
| Developer（REST/OpenAI/SDK/Plugin/Package/Docs） | ✅ |
| Platform（Dashboard/Task Center/Trace/Metrics/Evaluation/Security/Recovery/Migration/Upgrade） | ✅ |

## 后续版本建议

```text
V2.1  Qdrant/向量库后端 + 真实 embedding 模型默认启用
V2.2  Base + LoRA Adapter 运行时挂载
V2.3  llama-server 子进程隔离 + 崩溃自愈
V2.4  Workflow 可视化节点编辑器
V2.5  在线 Package Registry / Marketplace
```
