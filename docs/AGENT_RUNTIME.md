# ModelForge 3.0 Agent Runtime 架构

> 本文描述 `backend/app/runtime/` 的真实实现（与代码核对，spec 82）。
> 设计依据见 [AGENT_RUNTIME_DEVELOPMENT.md](AGENT_RUNTIME_DEVELOPMENT.md)。

---

## 1. 分层与依赖原则

```text
API (FastAPI)
    ↓
Service (services/agent_runtime_service.py, api/agent.py)
    ↓
AgentRuntime (runtime/runtime.py)
    ↓
ExecutionEngine (runtime/execution.py)
    ↓
Ports / Interfaces (runtime/ports.py)
    ↓
Adapters (repositories/, runtime/tools/*, runtime/models/*, runtime/kb_provider.py)
```

核心 `runtime/` 包不依赖 FastAPI / SQLAlchemy / PySide6（spec 79）；
持久化通过 Port（RunStore/EventStore/AgentStore）由 `repositories/` 的 SQLAlchemy 适配器实现。

## 2. 核心对象（spec 3-6）

| 对象 | 定义 | 实现 |
|---|---|---|
| Agent | 可持久化工作实体 | `AgentConfig` + `agents` 表（含 policy/runtime_config/knowledge_config） |
| Run | 一次执行 | `agent_runs` 表 + `RunRecord`（PENDING/RUNNING/WAITING_TOOL/WAITING_HUMAN/COMPLETED/FAILED/CANCELLED/TIMEOUT） |
| Session | 长期上下文 | 2.1 `sessions` 表，经 `SessionHistoryProvider` 注入 Context |
| Event | 执行事实 | `agent_events` 表，sequence 按 run 严格递增 |
| Tool | 能力 | `Tool` 协议 + `tools` 表 + `ToolRegistry` |
| Model | 推理资源 | `ModelProvider` 协议（Ollama/Mock；OpenAI 兼容可加） |
| Policy | 允许做什么 | `PolicyEngine`（默认拒绝网络/shell/写文件系统） |

## 3. 执行引擎（spec 20）

```text
Create Run -> Load Agent -> Build Context -> Invoke LLM
    -> Tool Call? (No -> Finish)
    -> Yes: Policy Check -> (Human Gate?) -> Execute Tool -> Emit Event -> Update State -> loop
```

限制：`max_iterations`(默认20) / `max_tool_calls`(默认50) / `timeout_seconds`(默认600)（spec 23 / 60）。
取消：每个 run 独立的 `CancellationToken`，无全局 current_run（spec 58）。

## 4. 事件系统（spec 6 / 7 / 30 / 31）

- `EventBus`：进程内 pub/sub，per-run 严格 sequence；持久化走异步队列写入 `agent_events`（不阻塞 LLM 路径）。
- `SQLAlchemyEventStore`：`(run_id, sequence)` 联合索引，支持 `after_sequence` 恢复。
- SSE：`GET /api/v1/agent/runs/{id}/stream?after_sequence=N` 先回放已持久化事件再订阅实时，按 sequence 去重。

## 5. Tool Registry（spec 8-12）

`ToolRegistry` 统一管理 builtin / MCP / plugin 工具；legacy 名称（file_read 等）作为别名保留（spec 67）。
`ToolExecutor` 统一执行超时（默认 60s）与重试（默认 0 次）。
危险工具声明权限级别（READ/WRITE/EXECUTE/NETWORK/SYSTEM/ADMIN），策略在执行前检查（spec 69）。

## 6. Context Engine（spec 15 / 16）

`ContextBuilder` 按 spec 16 流水线组装：System Prompt + Session History + Memory 检索 + Knowledge 检索 + Tool 状态 + 预算裁剪。
Memory 经 `DBMemoryProvider` 复用 2.1 memory_store；Knowledge 经 `KBKnowledgeProvider` 复用 RAG；
Agent 只声明 `knowledge_config.sources`，不接触 RAG 内部（spec 18）。

## 7. Human Gate（spec 32）

Policy 命中 `human_approval_required` 或 `require_approval_for` 时：
run 进入 `WAITING_HUMAN`，发 `human.approval.required` 事件；`approve/reject` 端点恢复执行。

## 8. MCP（spec 36 / 70）

`MCPRegistry` + `MCPClient`（JSON-RPC 2.0 over HTTP）+ `MCPToolAdapter`，
MCP 工具自动注册进统一 ToolRegistry，Agent 不区分来源。

## 9. Scheduler（spec 38 / 72）

`Scheduler` 提供 schedule_once / schedule_interval / cancel；触发时创建 AgentRun，不直接执行（spec 72）。

## 10. Multi-Agent（spec 40 / 41 / 73）

`agent.delegate` 工具：通过 runtime 创建嵌套 Run 并同步等待结果；禁止自我委托。

## 11. Observability（spec 48 / 49 / 81）

- 结构化日志：所有 run 日志带 run_id/agent_id/session_id（`runtime/logging.py`）。
- 指标：`GET /api/v1/agent/metrics` 返回 agent_runs_total/success/failed、duration、tool_calls_total、llm_calls_total、llm_tokens_total。
- 统一错误模型：`{"error": {"code", "message", "details"}}`（`runtime/errors.py`，15 个错误码）。

## 12. 目录结构（实测）

```text
backend/app/runtime/
├── runtime.py          # AgentRuntime 门面（Run/Agent/Tool/MCP/Scheduler/审批）
├── execution.py        # ExecutionEngine 主循环
├── errors.py           # 统一错误码
├── cancellation.py     # CancellationToken
├── run_context.py      # RunContext / ToolExecutionContext
├── state.py            # AgentState（框架无关）
├── types.py            # RunStatus / RunRecord / AgentConfig
├── ports.py            # RunStore/EventStore/AgentStore/Memory/Knowledge/History Port
├── metrics.py          # 指标注册表
├── logging.py          # 结构化日志
├── scheduler.py        # 调度器
├── kb_provider.py      # Knowledge/History Provider 适配器
├── events/             # types/bus（+ repositories/event_repository.py 存储适配）
├── tools/              # base/registry/executor/builtin/legacy/delegate
├── models/             # base/mock/ollama（ModelProvider）
├── policy/             # engine.py（Policy/PolicyDecision/PolicyEngine）
├── context/            # builder.py（ContextBuilder）
├── memory/             # providers.py（DBMemoryProvider/ConversationMemory）
└── mcp/                # client/registry/adapter
```