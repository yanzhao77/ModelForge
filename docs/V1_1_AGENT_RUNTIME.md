# V1.1 — Agent Runtime

目标：`User → Agent → Model Runtime → Tool/Memory/RAG → Final Answer`。
本版本把 V1.0 的模型运行时接到 Agent 上，并补齐 AgentDefinition / Run / Trace
的规范入口。

## 1. 数据模型

| 实体 | 位置 | 说明 |
|---|---|---|
| AgentDefinition | `agents` 表 + `runtime.types.AgentConfig` | 新增 `model_id`（跨模块唯一模型引用）与 `updated_at` |
| AgentRun | `agent_runs` 表 + `runtime.types.RunRecord` | 复用 |
| AgentMessage / ToolCall / ToolResult | `runtime.models.base`、`runtime.tools.base` | 复用 |
| Trace | 由事件流投影（`services/agent_trace.py`） | 新增 |

`model_id` 是权威字段：Agent 不再持有模型路径，`runtime_config.model_target`
同时冗余 `kind=local + model_id` 以便旧客户端读取。

## 2. Agent → Runtime 的唯一路径

```
Agent(model_id)
   ↓  services/agent_model_provider.RuntimeBackedProvider
ModelRuntimeManager.load/chat
   ↓
RuntimeInstance（llama.cpp / Transformers / Remote Adapter）
```

* `agent_runtime_service.routed_provider_factory` 对 `kind=local` 或存在
  `model_id` 的 Agent 返回 `RuntimeBackedProvider`，不再构造 Ollama/本地引擎；
* 远程 Agent 仍走 `OpenAICompatibleProvider`（加密凭据，行为不变）；
* 本地模型没有原生 tool 通道，`services/tool_call_parser.py` 负责
  「JSON 信封」的注入与解析（同时被 Workflow LLM 节点复用）。

## 3. Tool 与权限

5 个内置工具（filesystem.read / code.search / shell.execute / web.search /
knowledge.search）继续由 `ToolRegistry` + `ToolExecutor` + `PolicyEngine` 执行。
本版本补齐路线图权限词汇的映射：

| 路线图名称 | 实际强制级别 |
|---|---|
| READ_ONLY | READ |
| FILESYSTEM_READ | FILESYSTEM_READ |
| FILESYSTEM_WRITE | WRITE |
| PROCESS_EXECUTE | EXECUTE |
| NETWORK | NETWORK |
| DANGEROUS | SYSTEM |

`PermissionLevel.catalog()` / `normalize()` 提供映射，执行路径不变，
高风险操作仍由 `require_approval_for` / `human_approval_required` 触发人工确认。

## 4. Trace

`GET /api/v1/agents/runs/{run_id}/trace` 返回：

```json
{
  "trace_id": "<run_id>",
  "status": "COMPLETED",
  "summary": {"model_calls": 2, "tool_calls": 1, "retrievals": 0, "traced_duration_ms": 123},
  "spans": [
    {"name": "agent.run", "type": "run", "status": "COMPLETED", "duration_ms": 120, "events": [...]},
    {"name": "model.call[1]", "type": "model", "status": "COMPLETED", "events": [...]},
    {"name": "tool.filesystem.read", "type": "tool", "status": "COMPLETED", "attributes": {"output": "..."}}
  ],
  "events": [...]
}
```

事件负载在持久化时已经脱敏（input/output 记为 `[REDACTED]`），所以 Trace
不会把用户内容或工作区绝对路径写回响应；`output`/`error` 只来自 Run 记录本身。

## 5. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/agents` | 列出当前用户的 AgentDefinition |
| POST | `/api/v1/agents` | 创建（`model_id` 或 `model_target` 或旧式 `model`） |
| GET | `/api/v1/agents/{agent_id}` | 详情 |
| PUT | `/api/v1/agents/{agent_id}` | 更新（生成新定义版本） |
| DELETE | `/api/v1/agents/{agent_id}` | 删除 |
| GET | `/api/v1/agents/{agent_id}/versions` | 定义版本历史 |
| POST | `/api/v1/agents/{agent_id}/runs` | 创建 Run（`confirm` 默认 true） |
| GET | `/api/v1/agents/{agent_id}/runs` | 该 Agent 的 Run 列表 |
| GET | `/api/v1/agents/runs/{run_id}` | Run 详情 |
| GET | `/api/v1/agents/runs/{run_id}/trace` | Trace |

既有 `/api/v1/agent/*` 路由保持不变（同一张表、同一个运行时），
不会破坏现有桌面客户端。

## 6. UI

`Agent` 页面新增「查看 Trace」按钮 → `pages/agent_trace_dialog.py`：
展示运行摘要、按时间排序的 span 列表（含耗时与属性）以及最终输出/错误。

## 7. 验收

| 验收项 | 证据 |
|---|---|
| Agent 能调用 V1.0 Runtime | `tests/test_agent_definition_api.py::test_agent_run_produces_a_complete_trace`（Run 通过 RuntimeBackedProvider 完成） |
| Agent 能调用 Tool | 同上：脚本化模型先返回 `filesystem.read` 调用 |
| Tool 有权限 | `policy={"filesystem_access": true}` 才允许；权限映射用例 |
| Agent 能使用 Memory | 复用 `runtime/memory/providers.py`（`memory.read`/`memory.write` 进入 Trace） |
| Trace 完整 | trace 用例断言 model/tool/run span 与原始事件流 |
| Agent UI | 桌面端 Trace 对话框（`AgentTraceDialog`） |
| API 完成 | 上表 10 个端点 |
| E2E | `test_agent_definition_api.py`（7 用例） |
