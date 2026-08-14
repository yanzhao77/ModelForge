# ModelForge 3.0 技术开发实施规范

> **文档类型：技术开发实施规范 / Coding Agent 执行规范**
>
> **目标：** 在 ModelForge 2.1 的现有代码基础上，演进为一个 Local-first、可持久化、可观测、可扩展、支持 Tool/MCP/多模型/多 Agent 的 AI Agent Runtime Platform。
>
> **重要：**
>
> 本文不是概念设计文档。
>
> 本文是给 Codex / Claude Code / Coding Agent 使用的**工程实施规范**。
>
> Coding Agent 必须：
>
> 1. 先阅读现有代码；
> 2. 不得假设文档描述一定正确；
> 3. 以当前 `master` 实际代码为准；
> 4. 保留 ModelForge 2.1 已有功能；
> 5. 采用增量重构；
> 6. 每完成一个阶段必须运行测试；
> 7. 不允许为了实现新架构而破坏已有 API；
> 8. 不允许一次性大规模重写整个项目；
> 9. 每个阶段完成后都必须保证项目可启动、测试可运行；
> 10. 如果发现本文与实际代码冲突，以代码为准，并记录冲突。

---

# 1. 项目定位

## 1.1 当前 ModelForge

当前 ModelForge 2.1 已经具备：

* FastAPI Backend
* PySide6 Thin Client
* Model Registry 基础能力
* Ollama Runtime
* Transformers Runtime
* GGUF Runtime
* OpenAI Compatible API
* Chat
* Session
* Memory
* Knowledge / RAG
* Dataset
* Fine-tuning
* LangGraph Agent
* Tool Calling
* SSE Streaming
* Plugin 基础设施
* System Monitoring
* JWT Authentication
* SQLite / SQLAlchemy
* 152 Tests
* 58 API Routes

当前 `TECHNICAL_REPORT.md` 是 ModelForge 2.1 的现状基线。

不要重复实现上述功能。

---

# 2. ModelForge 3.0 的核心目标

ModelForge 3.0 不再定位为：

> Local AI Model Manager

而定位为：

> **Local-first AI Agent Runtime Platform**

即：

```text
                    ModelForge
                        │
              ┌─────────┴─────────┐
              │   Control Plane   │
              └─────────┬─────────┘
                        │
       ┌────────────────┼────────────────┐
       │                │                │
 Model Registry    Agent Registry    Tool Registry
       │                │                │
       └────────────────┼────────────────┘
                        │
                 Agent Runtime
                        │
          ┌─────────────┼─────────────┐
          │             │             │
       Context       Memory         Policy
          │             │             │
          └─────────────┼─────────────┘
                        │
                  Execution Engine
                        │
             ┌──────────┼──────────┐
             │          │          │
            LLM        Tools       RAG
             │          │          │
             └──────────┼──────────┘
                        │
                    Event Bus
                        │
          ┌─────────────┼─────────────┐
          │             │             │
         SSE          Audit         Metrics
```

核心原则：

> **Agent 是定义，Run 是执行，Session 是上下文，Event 是事实，Tool 是能力，Model 是推理资源。**

---

# 3. 核心概念模型

ModelForge 3.0 必须明确区分以下对象。

## 3.1 Agent

Agent 是一个可持久化的 AI 工作实体。

```text
Agent
├── id
├── name
├── description
├── model_ref
├── system_prompt
├── tools
├── memory_config
├── knowledge_config
├── policy
├── runtime_config
├── status
├── created_at
└── updated_at
```

Agent 不负责保存运行过程。

---

# 4. Agent Run

Agent Run 是 3.0 最核心的新对象。

每次 Agent 执行任务，都创建一个 Run。

```text
Agent
   │
   ├── Run #001
   ├── Run #002
   └── Run #003
```

Run 必须持久化。

建议字段：

```text
agent_runs
├── id
├── agent_id
├── user_id
├── session_id
├── status
├── input
├── output
├── model_id
├── started_at
├── finished_at
├── error
├── token_usage
├── tool_call_count
├── iteration_count
├── metadata
└── created_at
```

状态：

```text
PENDING
RUNNING
WAITING_TOOL
WAITING_HUMAN
COMPLETED
FAILED
CANCELLED
TIMEOUT
```

禁止把 Run 状态只保存在 Python 内存中。

---

# 5. Agent Session

Session 和 Run 必须分离。

```text
Session
   │
   ├── Run 1
   ├── Run 2
   ├── Run 3
   └── Run 4
```

Session 保存长期对话上下文。

Run 表示一次具体执行。

---

# 6. Event System

ModelForge 3.0 必须引入统一 Agent Event。

所有 Agent 执行过程都必须产生事件。

事件模型：

```text
AgentEvent
├── id
├── run_id
├── session_id
├── event_type
├── sequence
├── timestamp
├── payload
├── metadata
└── correlation_id
```

至少支持：

```text
run.created
run.started
run.completed
run.failed
run.cancelled

model.request.started
model.request.completed
model.request.failed

agent.message
agent.response

tool.call.started
tool.call.completed
tool.call.failed

memory.read
memory.write

knowledge.search.started
knowledge.search.completed

human.approval.required
human.approval.granted
human.approval.denied

runtime.error
runtime.warning
```

要求：

* 每个 Run 都有独立事件流；
* Event 必须具有 sequence；
* sequence 在同一个 Run 内严格递增；
* Event 必须可以持久化；
* Event 可以通过 SSE 实时订阅；
* Event 可以用于 Debug；
* Event 可以用于 Audit；
* Event 可以用于未来的分布式 Runtime。

---

# 7. Event Bus

新增：

```text
backend/app/runtime/events/
```

建议：

```text
events/
├── __init__.py
├── types.py
├── event.py
├── bus.py
├── publisher.py
└── subscribers.py
```

第一阶段不要引入 Kafka、Redis 等重量组件。

默认实现：

```text
In-process EventBus
+
Database Event Store
+
SSE Subscriber
```

未来可以替换成：

```text
Redis
NATS
Kafka
RabbitMQ
```

但上层 API 不应该依赖具体消息中间件。

---

# 8. Tool Registry

当前 `AGENT_TOOLS` 直接通过 Python Dict 管理工具。

3.0 必须升级为 Tool Registry。

目标：

```text
Tool Registry
│
├── Builtin Tools
├── Plugin Tools
├── MCP Tools
└── Remote Tools
```

Tool 定义：

```text
Tool
├── id
├── name
├── description
├── version
├── input_schema
├── output_schema
├── permissions
├── timeout
├── retry_policy
├── executor
├── source
└── metadata
```

---

# 9. Tool 标准接口

定义统一 Tool Protocol。

建议：

```python
class Tool:
    name: str
    description: str

    def schema(self) -> dict:
        ...

    async def execute(
        self,
        arguments: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        ...
```

ToolResult：

```python
class ToolResult:
    success: bool
    output: Any
    error: str | None
    metadata: dict
```

ToolExecutionContext：

```text
ToolExecutionContext
├── user_id
├── agent_id
├── run_id
├── session_id
├── permissions
├── timeout
├── cancellation_token
└── metadata
```

---

# 10. Tool 权限

所有危险 Tool 必须具备权限定义。

例如：

```text
filesystem.read
filesystem.write
shell.execute
python.execute
network.request
git.write
docker.execute
```

权限级别：

```text
READ
WRITE
EXECUTE
NETWORK
SYSTEM
ADMIN
```

Agent 不允许因为 system prompt 要求就自动获得权限。

权限来自 Runtime Policy。

---

# 11. Tool Timeout

所有 Tool 必须支持 timeout。

默认：

```text
Tool timeout = 60 seconds
```

不同工具可以覆盖。

例如：

```text
filesystem.read = 10s
web.search = 30s
shell.execute = 60s
training = 3600s
```

禁止 Tool 无限阻塞 Agent Run。

---

# 12. Tool Retry

Tool 必须支持：

```text
retry_count
retry_delay
retryable_errors
```

默认：

```text
retry_count = 0
```

只有明确允许重试的 Tool 才可以自动 retry。

---

# 13. Model Registry 3.0

当前模型管理能力继续保留。

但是模型必须统一抽象。

定义：

```text
ModelRef
├── provider
├── model_id
├── endpoint
├── local
├── capabilities
├── context_window
├── max_output_tokens
├── streaming
├── tool_calling
├── vision
├── reasoning
└── metadata
```

Capabilities：

```text
CHAT
STREAM
TOOL_CALLING
VISION
EMBEDDING
REASONING
JSON_MODE
```

---

# 14. Model Provider

统一 Provider 接口：

```python
class ModelProvider:

    async def chat(...):
        ...

    async def stream(...):
        ...

    async def count_tokens(...):
        ...

    def capabilities(...):
        ...
```

支持：

```text
Ollama
OpenAI Compatible
Transformers
GGUF
Custom Provider
```

以后可以自然增加：

```text
Anthropic
Gemini
DeepSeek
Qwen
ModelScope
```

禁止业务层直接依赖具体 Provider。

---

# 15. Context Engine

3.0 增加：

```text
backend/app/runtime/context/
```

负责构造最终 LLM Context。

输入：

```text
User Input
+
System Prompt
+
Session History
+
Memory
+
Knowledge
+
Tool Results
+
Agent State
```

输出：

```text
Context
```

---

# 16. Context Pipeline

标准流程：

```text
User Input
    ↓
System Prompt
    ↓
Session History
    ↓
Memory Retrieval
    ↓
Knowledge Retrieval
    ↓
Tool State
    ↓
Context Budget
    ↓
Final Prompt
```

Context Engine 必须能够：

* 计算上下文长度；
* 删除低优先级历史；
* 保留 System Prompt；
* 保留最近消息；
* 保留关键 Memory；
* 保留 Tool Result；
* 支持未来 Context Compression。

---

# 17. Memory System

现有 Memory 功能必须保留。

3.0 将 Memory 统一抽象为：

```text
Memory
├── Conversation Memory
├── User Memory
├── Agent Memory
├── Semantic Memory
└── Working Memory
```

Memory 必须与 Session 分离。

---

# 18. Knowledge System

Knowledge / RAG 继续保留。

但 Knowledge 不能直接和 Agent Runtime 耦合。

定义：

```text
KnowledgeService
    ↓
Retriever
    ↓
Context Engine
```

Agent 只需要声明：

```text
knowledge_sources
```

而不是直接操作 RAG 内部实现。

---

# 19. Agent Runtime

新增：

```text
backend/app/runtime/
```

建议目录：

```text
runtime/
├── __init__.py
├── runtime.py
├── execution.py
├── state.py
├── context/
├── events/
├── tools/
├── models/
├── memory/
├── policy/
├── scheduler/
└── errors.py
```

---

# 20. Execution Engine

Execution Engine 负责：

```text
Create Run
    ↓
Load Agent
    ↓
Load Model
    ↓
Build Context
    ↓
Invoke LLM
    ↓
Tool Call?
   ├── No → Finish
   └── Yes
        ↓
      Execute Tool
        ↓
      Emit Event
        ↓
      Update State
        ↓
      Build Context
        ↓
      Invoke LLM
        ↓
       ...
```

---

# 21. LangGraph 的定位

当前 LangGraph 可以继续使用。

但是：

> LangGraph 是 Execution Engine 的实现细节，不是整个 ModelForge Runtime。

禁止让：

```text
API
 ↓
LangGraph
```

成为系统架构。

正确结构：

```text
API
 ↓
Agent Runtime
 ↓
Execution Engine
 ↓
LangGraph Adapter
 ↓
LLM / Tools
```

未来如果需要，可以替换：

```text
LangGraph
   ↓
Custom Graph Engine
```

而不影响 API。

---

# 22. Agent State

Agent State 必须独立。

建议：

```text
AgentState
├── run_id
├── messages
├── context
├── tool_calls
├── variables
├── metadata
├── iteration
└── status
```

State 不应该直接依赖 SQLAlchemy Model。

---

# 23. Agent Loop 限制

必须增加：

```text
max_iterations
max_tool_calls
max_tokens
timeout
```

默认：

```text
max_iterations = 20
max_tool_calls = 50
timeout = 10 minutes
```

防止 Agent 无限循环。

---

# 24. Cancellation

Agent Run 必须支持取消。

API：

```http
POST /api/v1/agent/runs/{run_id}/cancel
```

取消必须：

1. 修改 Run 状态；
2. 通知 Execution Engine；
3. 终止当前 Tool；
4. 停止后续 LLM 调用；
5. 写入 `run.cancelled` Event。

---

# 25. Agent Run API

新增 API：

```text
POST   /api/v1/agent/runs
GET    /api/v1/agent/runs
GET    /api/v1/agent/runs/{id}
POST   /api/v1/agent/runs/{id}/cancel
GET    /api/v1/agent/runs/{id}/events
GET    /api/v1/agent/runs/{id}/stream
```

创建：

```json
{
  "agent_id": "xxx",
  "session_id": "xxx",
  "input": "分析当前项目",
  "metadata": {}
}
```

返回：

```json
{
  "run_id": "xxx",
  "status": "PENDING"
}
```

---

# 26. SSE Run Stream

新增：

```text
GET /agent/runs/{id}/stream
```

输出：

```text
event: run.started

event: agent.message

event: tool.call.started

event: tool.call.completed

event: agent.message

event: run.completed
```

客户端可以实现实时 Agent Timeline。

---

# 27. Agent Trace

每个 Run 必须可以看到：

```text
Run
 │
 ├── LLM Call
 │
 ├── Tool Call
 │
 ├── LLM Call
 │
 ├── Tool Call
 │
 └── Final Response
```

Trace 必须支持：

* duration
* input
* output
* model
* tokens
* tool name
* error

---

# 28. Database 设计

在现有 11 张表基础上增量增加。

至少增加：

```text
agent_runs
agent_events
tools
```

如果当前 Agent 表已经存在，则扩展。

建议：

```text
agents
agent_runs
agent_events
tools
```

所有业务数据必须支持：

```text
user_id
```

需要用户隔离的对象必须进行 ownership check。

---

# 29. 数据库索引

至少增加：

```text
agent_runs.agent_id
agent_runs.user_id
agent_runs.session_id
agent_runs.status
agent_runs.created_at

agent_events.run_id
agent_events.sequence
agent_events.created_at
```

联合索引：

```text
(run_id, sequence)
(user_id, created_at)
```

---

# 30. Event 持久化

Event 不允许只存在内存。

最低要求：

```text
Run
 ↓
Event
 ↓
Database
 ↓
SSE
```

而不是：

```text
Run
 ↓
SSE
```

因为客户端断线后必须能够恢复。

---

# 31. SSE Resume

未来客户端重新连接时，可以使用：

```text
Last-Event-ID
```

或者：

```text
?after_sequence=123
```

恢复事件。

第一阶段可以实现：

```text
after_sequence
```

---

# 32. Human Gate

ModelForge 3.0 必须为 Human-in-the-loop 留接口。

状态：

```text
WAITING_HUMAN
```

Event：

```text
human.approval.required
```

API：

```text
POST /api/v1/agent/runs/{id}/approve
POST /api/v1/agent/runs/{id}/reject
```

第一阶段只实现基础机制。

不要做复杂 UI。

---

# 33. Policy Engine

新增：

```text
runtime/policy/
```

Policy 控制：

```text
allowed_models
allowed_tools
max_iterations
max_tool_calls
network_access
filesystem_access
shell_access
human_approval_required
```

例如：

```json
{
  "allowed_tools": [
    "filesystem.read",
    "knowledge.search"
  ],
  "network_access": false,
  "shell_access": false,
  "max_iterations": 10
}
```

---

# 34. 安全原则

禁止 Agent 默认拥有：

```text
shell
filesystem write
network
docker
git push
```

危险能力必须显式授权。

---

# 35. Sandbox

第一阶段不要直接实现复杂 Docker Sandbox。

但必须设计：

```text
ToolExecutor
```

接口。

以后可以：

```text
LocalExecutor
DockerExecutor
RemoteExecutor
```

所以 Tool 不允许直接：

```python
subprocess.run(...)
```

而应该：

```text
Tool
 ↓
Executor
 ↓
Sandbox
```

---

# 36. MCP

3.0 必须预留 MCP。

增加：

```text
MCP Server Registry
```

概念：

```text
MCP Server
├── name
├── endpoint
├── transport
├── auth
├── tools
└── status
```

MCP Tool 最终进入：

```text
Tool Registry
```

Agent 不应该区分：

```text
Builtin Tool
MCP Tool
Plugin Tool
```

统一：

```text
Tool
```

---

# 37. Plugin System

当前 Plugin SPI 保留。

3.0 Plugin 可以注册：

```text
ModelProvider
Tool
MemoryProvider
KnowledgeProvider
Runtime
MCP Server
EventSubscriber
```

---

# 38. Scheduler

增加基础 Scheduler 接口：

```text
Scheduler
├── schedule_once
├── schedule_interval
└── cancel
```

未来支持：

```text
cron
```

但第一阶段不需要复杂分布式调度。

---

# 39. Agent 定时任务

未来 Agent 可以：

```text
每天 09:00
    ↓
创建 Agent Run
    ↓
执行任务
    ↓
产生 Event
    ↓
输出结果
```

这为未来 Autonomous Agent 打基础。

---

# 40. Multi-Agent

3.0 第一阶段不要实现复杂 Multi-Agent。

只需要让一个 Agent 能够通过 Tool 调用另一个 Agent：

```text
Agent A
  ↓
delegate_agent
  ↓
Agent B
  ↓
Agent Run
  ↓
Result
```

未来再扩展：

```text
Sequential
Parallel
Supervisor
Hierarchical
Debate
Swarm
```

---

# 41. Agent Delegation

预留 Tool：

```text
agent.delegate
```

参数：

```json
{
  "agent_id": "xxx",
  "task": "分析代码质量"
}
```

返回：

```json
{
  "run_id": "xxx",
  "status": "PENDING"
}
```

第一阶段允许同步等待。

后续支持异步。

---

# 42. OpenAI Compatible API

现有：

```text
/v1/chat/completions
/v1/models
```

必须保持兼容。

3.0 可以增加：

```text
/v1/agents
/v1/agents/{id}/runs
```

但不要破坏已有 OpenAI API。

---# 43. API Versioning

保持：

```text
/api/v1
```

Agent Runtime 新 API 统一放：

```text
/api/v1/agent/*
```

不要创建：

```text
/api/runtime/*
```

和：

```text
/api/agent/*
```

两套重复 API。

---

# 44. Service Layer

禁止 API Route 直接操作 Runtime 内部。

正确：

```text
API
 ↓
AgentService
 ↓
AgentRuntime
 ↓
ExecutionEngine
```

而不是：

```text
API
 ↓
LangGraph
```

---

# 45. Repository Layer

如果当前代码中 SQLAlchemy 查询散落在 Service 中，应逐步抽象：

```text
repositories/
├── agent_repository.py
├── run_repository.py
├── event_repository.py
└── tool_repository.py
```

但不要一次性重构所有旧代码。

只针对 3.0 新功能使用 Repository。

---

# 46. DTO / Schema

增加：

```text
backend/app/schemas/
```

至少：

```text
agent.py
run.py
event.py
tool.py
model.py
```

API 禁止直接暴露 SQLAlchemy ORM Object。

---

# 47. Error Model

统一错误结构：

```json
{
  "error": {
    "code": "AGENT_RUN_TIMEOUT",
    "message": "Agent run timed out",
    "details": {}
  }
}
```

至少定义：

```text
AGENT_NOT_FOUND
RUN_NOT_FOUND
RUN_CANCELLED
RUN_TIMEOUT
TOOL_NOT_FOUND
TOOL_DENIED
TOOL_TIMEOUT
MODEL_NOT_FOUND
MODEL_UNAVAILABLE
CONTEXT_TOO_LARGE
POLICY_DENIED
HUMAN_APPROVAL_REQUIRED
RUNTIME_ERROR
```

---

# 48. Observability

3.0 至少实现：

```text
structured logs
run_id
agent_id
session_id
user_id
tool_name
model_name
duration
```

所有 Agent Runtime 日志必须包含：

```text
run_id
```

这样才能完整追踪一次 Agent 执行。

---

# 49. Metrics

第一阶段至少统计：

```text
agent_runs_total
agent_runs_success
agent_runs_failed
agent_run_duration
tool_calls_total
tool_call_duration
llm_calls_total
llm_tokens_total
```

暂时不强制 Prometheus。

内部 Metrics API 即可。

---

# 50. Client 改造

PySide6 客户端必须保持瘦客户端。

不要把 Runtime 逻辑放到 Client。

增加：

```text
AgentPage
AgentRunPage
RunTimeline
ToolCallCard
EventStream
```

推荐 UI：

```text
Agent
 ├── Chat
 ├── Runs
 ├── Tools
 └── Settings
```

Run 页面：

```text
Run #123
────────────────────────

09:21:01  Run Started

09:21:02  LLM
          Thinking...

09:21:04  Tool
          filesystem.read

09:21:04  Tool Result
          25 files

09:21:06  LLM
          ...

09:21:10  Completed
```

---

# 51. 不允许在客户端显示“伪 Thinking”

如果模型没有返回 reasoning：

不要伪造：

```text
Thinking...
```

只能显示：

```text
Generating...
```

Tool Call 必须显示真实 Event。

---

# 52. 测试要求

每新增一个 Runtime 功能，必须增加测试。

最低：

```text
Unit Test
Integration Test
API Test
Failure Test
```

---

# 53. Agent Runtime 测试

至少：

```text
test_create_run
test_run_success
test_run_failure
test_run_cancel
test_run_timeout
test_tool_call
test_tool_denied
test_tool_timeout
test_max_iterations
test_max_tool_calls
test_event_sequence
test_event_persistence
test_sse_stream
test_sse_resume
```

---

# 54. Agent Loop Mock

测试不能依赖真实 LLM。

必须使用：

```text
MockLLM
FakeTool
```

例如：

```text
MockLLM
 ↓
tool_call
 ↓
FakeTool
 ↓
tool_result
 ↓
MockLLM
 ↓
final
```

---

# 55. E2E 测试

至少实现一个完整流程：

```text
Create Agent
    ↓
Create Run
    ↓
LLM requests Tool
    ↓
Tool executes
    ↓
Event stored
    ↓
LLM final response
    ↓
Run COMPLETED
```

---

# 56. 回归要求

ModelForge 2.1 原有：

```text
152 tests
```

必须全部保持通过。

3.0 开发过程中：

```text
旧测试 + 新测试
```

必须全部通过。

不得通过修改测试来“解决”功能回归。

---

# 57. 性能要求

单个 Agent Run：

```text
Runtime overhead < 100ms
```

不包含 LLM 推理时间。

Event 持久化：

```text
不能阻塞 LLM 主执行路径
```

允许采用：

```text
async queue
```

进行异步写入。

---

# 58. 并发

第一阶段：

```text
单进程
asyncio
```

支持：

```text
multiple concurrent runs
```

禁止：

```python
global current_run
```

这样的全局状态。

---

# 59. Cancellation Token

Execution Context 必须包含：

```text
CancellationToken
```

Tool 和 LLM Provider 都应该能够检查。

---

# 60. Resource Limits

Run 必须限制：

```text
max_iterations
max_tool_calls
timeout
max_context_tokens
max_output_tokens
```

以后可以增加：

```text
max_cost
max_network_requests
max_file_operations
```

---

# 61. 配置

新增：

```yaml
runtime:
  max_iterations: 20
  max_tool_calls: 50
  timeout_seconds: 600
  event_persistence: true
  event_retention_days: 30
```

Tool：

```yaml
tools:
  default_timeout_seconds: 60
```

Policy：

```yaml
policy:
  default_network_access: false
  default_shell_access: false
```

---

# 62. Backward Compatibility

必须保证：

```text
ModelForge 2.1 Chat
ModelForge 2.1 Session
ModelForge 2.1 Memory
ModelForge 2.1 Knowledge
ModelForge 2.1 Training
ModelForge 2.1 Model
ModelForge 2.1 OpenAI API
```

全部继续工作。

---

# 63. Migration Strategy

禁止：

```text
一次性重写
```

必须：

```text
Phase 1
基础 Runtime

Phase 2
Run

Phase 3
Event

Phase 4
Tool Registry

Phase 5
Context

Phase 6
Policy

Phase 7
MCP

Phase 8
Client

Phase 9
Scheduler

Phase 10
Multi-Agent
```

---

# 64. Phase 1 —— Runtime Foundation

目标：

```text
backend/app/runtime/
```

建立：

```text
Runtime
ExecutionContext
AgentState
RuntimeError
```

完成：

* Runtime 生命周期；
* Cancellation；
* Timeout；
* Execution Context。

不要修改旧 Chat。

验收：

```text
pytest
```

全部通过。

---

# 65. Phase 2 —— Agent Run

实现：

```text
agent_runs
```

API：

```text
POST /agent/runs
GET /agent/runs
GET /agent/runs/{id}
POST /agent/runs/{id}/cancel
```

实现：

```text
PENDING
RUNNING
COMPLETED
FAILED
CANCELLED
TIMEOUT
```

验收：

* Run 可以创建；
* Run 可以执行；
* Run 可以查询；
* Run 可以取消；
* 状态持久化。

---

# 66. Phase 3 —— Event System

实现：

```text
AgentEvent
EventBus
EventStore
```

所有 Run 状态变化产生 Event。

验收：

```text
run.started
run.completed
run.failed
run.cancelled
```

可以持久化。

---

# 67. Phase 4 —— Tool Registry

将：

```text
AGENT_TOOLS
```

逐步迁移为：

```text
ToolRegistry
```

原有工具必须继续工作。

禁止一次性删除 `AGENT_TOOLS`。

采用：

```text
Legacy Adapter
```

过渡。

---

# 68. Phase 5 —— Context Engine

将：

```text
history
memory
knowledge
tool results
```

统一进入：

```text
ContextBuilder
```

Chat 旧逻辑可以继续使用。

Agent Runtime 优先使用新 Context Engine。

---

# 69. Phase 6 —— Policy

增加：

```text
PolicyEngine
```

首先支持：

```text
allowed_tools
network_access
shell_access
filesystem_access
max_iterations
```

Tool 执行前检查 Policy。

---

# 70. Phase 7 —— MCP

实现：

```text
MCPRegistry
MCPClient
MCPToolAdapter
```

MCP Tool 自动注册到 Tool Registry。

---

# 71. Phase 8 —— Client

增加：

```text
AgentPage
RunPage
Timeline
ToolCall
```

实现：

```text
Run Stream
```

---

# 72. Phase 9 —— Scheduler

支持：

```text
schedule_once
schedule_interval
```

Scheduler 创建：

```text
AgentRun
```

Scheduler 不直接执行 Agent。

---

# 73. Phase 10 —— Multi-Agent

只实现：

```text
agent.delegate
```

基础能力。

不要立即实现复杂 Workflow。

---

# 74. 未来架构

最终目标：

```text
                       ModelForge
                            │
                   ┌────────┴────────┐
                   │   Control Plane │
                   └────────┬────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
      Models              Agents              Tools
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                     Agent Runtime
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
    Context               Memory              Policy
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                      Execution Engine
                            │
              ┌─────────────┼─────────────┐
              │             │             │
             LLM           Tools          RAG
              │             │             │
              └─────────────┼─────────────┘
                            │
                         Events
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
       SSE                 Audit             Metrics
```

---

# 75. 与 Hermes 的关系

ModelForge 不负责成为最高层 Orchestrator。

未来建议：

```text
Hermes
   │
   │ Agent Protocol / API
   ▼
ModelForge
   │
   ├── Model Runtime
   ├── Agent Runtime
   ├── Tool Runtime
   ├── Memory
   ├── RAG
   └── Execution
```

因此：

> Hermes 是 Commander / Orchestrator。

> ModelForge 是 Runtime / Execution Platform。

ModelForge 不应该把 Hermes 的职责写进核心 Runtime。

---

# 76. 与 Proteus 的关系

未来：

```text
Proteus
   │
   │ Software Factory Workflow
   ▼
Hermes
   │
   │ Agent Tasks
   ▼
ModelForge
   │
   │ Agent Runs
   ▼
Models / Tools / Sandbox
```

因此 ModelForge 是底层执行基础设施。

---

# 77. 与 DeepSeek Harness 的关系

DeepSeek Harness 等项目可以作为 Agent Harness / Capability Layer 的参考。

ModelForge 不需要复制 Harness。

ModelForge 应负责：

```text
Runtime
State
Run
Tool
Model
Memory
Event
Policy
```

Harness 可以作为：

```text
Agent Definition / Execution Strategy
```

接入。

---

# 78. 代码组织原则

禁止：

```text
god class
```

禁止：

```text
AgentEngine
```

承担：

* Database
* Model Provider
* Tool Registry
* Memory
* SSE
* API
* Policy

全部职责。

拆分：

```text
AgentService
AgentRuntime
ExecutionEngine
ContextEngine
ToolRegistry
ModelRegistry
EventBus
PolicyEngine
```

---

# 79. 依赖原则

核心 Runtime 不允许直接依赖：

```text
PySide6
FastAPI
SQLAlchemy
```

Runtime 应尽量保持框架无关。

推荐：

```text
API
 ↓
Service
 ↓
Runtime
 ↓
Ports / Interfaces
 ↓
Adapters
```

---

# 80. Adapter 原则

例如：

```text
ModelProvider
    ↓
OllamaAdapter
OpenAIAdapter
TransformersAdapter
GGUFAdapter
```

Tool：

```text
Tool
    ↓
BuiltinToolAdapter
MCPToolAdapter
PluginToolAdapter
```

Storage：

```text
Repository
    ↓
SQLAlchemyRepository
```

---

# 81. Logging

禁止：

```python
print()
```

Runtime 使用统一 logger。

所有 Run 日志必须包含：

```text
run_id
agent_id
session_id
```

---

# 82. Documentation

完成代码后同步更新：

```text
docs/TECHNICAL_REPORT.md
docs/AGENT_RUNTIME.md
docs/API_REFERENCE.md
docs/DEVELOPMENT_PLAN.md
```

其中：

```text
TECHNICAL_REPORT.md
```

描述真实当前状态。

```text
AGENT_RUNTIME.md
```

描述 Runtime 架构。

```text
API_REFERENCE.md
```

描述 API。

```text
DEVELOPMENT_PLAN.md
```

描述未来路线。

禁止文档描述不存在的功能。

---

# 83. Definition of Done

一个 Phase 只有满足以下条件才算完成：

```text
[ ] 代码实现
[ ] Unit Test
[ ] Integration Test
[ ] API Test
[ ] Error Handling
[ ] Logging
[ ] Documentation
[ ] Backward Compatibility
[ ] pytest 全部通过
```

---

# 84. Codex 执行规则

Codex 开始工作后：

## Step 1

扫描：

```text
backend/app
client/pyside6
tests
docs
requirements*.txt
config.yaml
```

## Step 2

读取：

```text
docs/TECHNICAL_REPORT.md
```

## Step 3

分析当前实际代码。

## Step 4

生成：

```text
ModelForge 3.0 Implementation Plan
```

不要直接修改代码。

## Step 5

将计划拆成 Phase。

## Step 6

一次只实施一个 Phase。

## Step 7

每个 Phase：

```text
修改
↓
测试
↓
修复
↓
测试
↓
更新文档
```

## Step 8

不要一次性修改 50+ 文件。

---

# 85. Codex 特别禁止事项

禁止：

```text
大规模重写
删除已有测试
删除旧 API
删除现有功能
修改数据库后不做迁移
修改 API 后不做测试
为了通过测试修改测试预期
引入重量级中间件而没有必要
```

---

# 86. 最终验收标准

最终 ModelForge 3.0 必须能够完成：

```text
Create Agent
      ↓
Select Model
      ↓
Select Tools
      ↓
Configure Policy
      ↓
Create Session
      ↓
Create Run
      ↓
Context Build
      ↓
LLM
      ↓
Tool Call
      ↓
Tool Execution
      ↓
Event
      ↓
Context Update
      ↓
LLM
      ↓
Final Response
      ↓
Run Completed
```

并且整个过程：

```text
可持久化
可取消
可恢复
可追踪
可审计
可测试
可扩展
```

---

# 87. 最终目标

ModelForge 3.0 最终不是：

> 一个更漂亮的本地 AI 聊天软件。

也不是：

> 一个更强的模型下载器。

而是：

> **一个 Local-first AI Agent Runtime Platform。**

其核心能力应该浓缩成：

```text
Model
Agent
Run
Session
Tool
Context
Memory
Knowledge
Policy
Event
Runtime
```

其中最重要的关系：

```text
Agent = What an agent is

Run = What an agent is doing

Session = What an agent remembers in a conversation

Tool = What an agent can do

Model = How an agent thinks

Context = What an agent currently knows

Memory = What an agent remembers

Knowledge = What an agent can retrieve

Policy = What an agent is allowed to do

Event = What an agent has done

Runtime = Where everything executes
```

这套模型必须成为 ModelForge 3.0 的核心设计原则。

**不要继续单纯堆功能。**

从 ModelForge 2.1 到 3.0，最重要的工作是：

> **把已有的 Model、Chat、Memory、RAG、Tool、LangGraph、Training 能力，从“功能集合”重构为一个真正可运行的 Agent Runtime。**