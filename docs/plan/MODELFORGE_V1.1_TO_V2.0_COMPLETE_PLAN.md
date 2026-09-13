# ModelForge V1.1 → V2.0 完整开发路线图

> 前置条件：ModelForge V1.0 已完成 Model
> Registry、Runtime、Chat、Training 的统一联动。
>
> 总目标：把 ModelForge 从"本地模型管理 + 聊天工具"升级为完整的 Local AI
> Platform。

## 一、版本总览

  ---------------------------------------------------------------------------------------
  版本                    核心目标                主要成果
  ----------------------- ----------------------- ---------------------------------------
  V1.1                    Agent Runtime           Agent、Tool、Memory、Trace

  V1.2                    Multi-Runtime           llama.cpp、Transformers、Remote 等统一
                                                  Runtime Adapter

  V1.3                    Multi-Model             多模型实例、资源管理、LRU、队列

  V1.4                    Knowledge / RAG         文档、Embedding、Qdrant、检索

  V1.5                    Workflow                Workflow、Multi-Agent、并行/条件/循环

  V1.6                    Developer Platform      SDK、API、Plugin

  V1.7                    Package / Marketplace   Model/Agent/Tool/Workflow 包
                          Foundation              

  V1.8                    Observability           Trace、Metrics、Evaluation、安全

  V1.9                    Production              崩溃恢复、性能、升级、跨平台

  V2.0                    Local AI Platform       全部能力统一、稳定发布
  ---------------------------------------------------------------------------------------

最终架构：

``` text
                         ModelForge V2.0
                              │
       ┌──────────────────────┼──────────────────────┐
       ↓                      ↓                      ↓
   Model Platform        Agent Platform        Developer Platform
       │                      │                      │
       ↓                      ↓                      ↓
 Model Registry          Agent Runtime           SDK / API
       │                ┌─────┼─────┐               │
       ↓                ↓     ↓     ↓               ↓
 Runtime Manager      Tools Memory RAG           Plugins
       │                │     │     │
       └────────────────┼─────┼─────┘
                        ↓
                  Workflow Engine
                        │
                ┌───────┼───────┐
                ↓       ↓       ↓
              Model A Model B Model C
                        │
                        ↓
                Trace / Evaluation
                        │
                        ↓
                 OpenAI Compatible API
```

------------------------------------------------------------------------

# 二、V1.1 --- Agent Runtime

## 目标

把：

``` text
Model → Runtime → Chat
```

升级为：

``` text
User → Agent → Model Runtime → Tool/Memory/RAG → Final Answer
```

## 1. Agent 核心对象

增加或统一：

``` text
AgentDefinition
AgentRun
AgentMessage
AgentToolCall
AgentToolResult
```

AgentDefinition 至少包含：

``` text
id
name
description
model_id
system_prompt
tools
memory_config
max_iterations
generation_config
created_at
updated_at
```

## 2. Agent Runtime

Agent 不得直接：

``` text
llama_cpp.Llama
Transformers
model_path
```

统一：

``` text
Agent
 ↓
ModelResolver
 ↓
ModelRuntimeManager
 ↓
RuntimeInstance
```

## 3. Tool System

建立：

``` text
ToolRegistry
ToolDefinition
ToolExecutor
ToolResult
```

第一批工具：

``` text
file_read
file_search
python
shell
http_request
```

每个 Tool 必须声明：

``` text
name
description
input_schema
permission
timeout
```

## 4. Tool Calling

``` text
User
 ↓
Agent
 ↓
LLM
 ↓
Tool Call?
 ├─ No → Final
 └─ Yes
      ↓
 ToolExecutor
      ↓
 Tool Result
      ↓
 LLM
      ↓
 Final
```

必须限制：

``` text
max_iterations
timeout
output size
tool count
```

## 5. Permission

至少：

``` text
READ_ONLY
FILESYSTEM_WRITE
NETWORK
PROCESS_EXECUTE
DANGEROUS
```

高风险操作支持：

``` text
用户确认
```

## 6. Memory

Agent 使用现有 Memory 能力，并统一：

``` text
Conversation Memory
Short-term Memory
Long-term Memory
```

不要再造第二套 Memory。

## 7. Trace

每个 Agent Run 保存：

``` text
run_id
agent_id
model_id
input
model calls
tool calls
tool results
memory retrieval
final output
error
timestamps
```

## 8. Agent UI

新增：

``` text
Agents
 ├─ Agent List
 ├─ Create
 ├─ Edit
 ├─ Run
 └─ Trace
```

## 9. API

``` http
GET    /api/v1/agents
POST   /api/v1/agents
GET    /api/v1/agents/{id}
PUT    /api/v1/agents/{id}
DELETE /api/v1/agents/{id}

POST   /api/v1/agents/{id}/runs
GET    /api/v1/agents/runs/{run_id}
GET    /api/v1/agents/runs/{run_id}/trace
```

## V1.1 验收

-   [ ] Agent 能调用 V1.0 Runtime
-   [ ] Agent 能调用 Tool
-   [ ] Tool 有权限
-   [ ] Agent 能使用 Memory
-   [ ] Trace 完整
-   [ ] Agent UI 完成
-   [ ] API 完成
-   [ ] E2E Agent 测试通过

------------------------------------------------------------------------

# 三、V1.2 --- Multi-Runtime

## 目标

ModelForge 不再绑定单一推理引擎。

统一抽象：

``` python
class RuntimeAdapter:
    load()
    unload()
    chat()
    stream_chat()
    status()
    capabilities()
```

## Runtime

优先支持：

``` text
llama.cpp
Transformers
Remote OpenAI-compatible
```

后续可扩展：

``` text
Ollama
MLX
其他 Runtime
```

## Runtime Resolver

``` text
ModelRecord
 ↓
supported_runtimes
 ↓
preferred_runtime
 ↓
RuntimeAdapter
```

ModelRecord 增加：

``` text
supported_runtimes
preferred_runtime
```

## Remote Model

统一进入 Model Registry：

``` text
source = remote
runtime = remote_openai
```

配置：

``` text
base_url
model
api_key
timeout
```

API Key 必须安全存储。

## Runtime Health

``` http
GET /api/v1/runtimes
GET /api/v1/runtimes/{id}/health
```

## V1.2 验收

-   [ ] llama.cpp Adapter
-   [ ] Transformers Adapter
-   [ ] Remote Adapter
-   [ ] Runtime Resolver
-   [ ] Runtime Health
-   [ ] Chat 可切换 Runtime
-   [ ] Agent 可切换 Runtime

------------------------------------------------------------------------

# 四、V1.3 --- Multi-Model & Resource Manager

## 目标

从：

``` text
一个 Loaded Model
```

升级为：

``` text
多个 Runtime Instance
```

架构：

``` text
RuntimeManager
 ├─ RuntimeInstance A
 ├─ RuntimeInstance B
 ├─ RuntimeInstance C
 └─ RuntimeInstance D
```

## Resource Manager

统一管理：

``` text
CPU
RAM
GPU
VRAM
Disk
```

实时记录：

``` text
memory
vram
cpu
last_used
busy
owner
```

## LRU

资源不足：

``` text
寻找最久未使用模型
 ↓
确认不 busy
 ↓
Unload
 ↓
Load 新模型
```

禁止强制卸载正在执行请求的模型。

## Queue

资源不足时：

``` text
Request
 ↓
Queue
 ↓
Resource Available
 ↓
Load
```

## Priority

支持：

``` text
HIGH
NORMAL
LOW
```

## V1.3 验收

-   [ ] 多 Runtime Instance
-   [ ] Resource Manager
-   [ ] RAM/VRAM tracking
-   [ ] LRU
-   [ ] Load Queue
-   [ ] Priority
-   [ ] 多模型 Agent
-   [ ] 内存泄漏测试

------------------------------------------------------------------------

# 五、V1.4 --- Knowledge / RAG

## 目标

让 Agent 可以使用用户自己的知识。

``` text
Document
 ↓
Parse
 ↓
Chunk
 ↓
Embedding
 ↓
Qdrant
 ↓
Retriever
 ↓
Context
 ↓
LLM
```

## Knowledge 对象

``` text
KnowledgeBase
Document
DocumentChunk
Embedding
Retrieval
```

支持：

``` text
PDF
TXT
Markdown
DOCX
CSV
代码文件
```

## Pipeline

``` text
Upload
 ↓
Parse
 ↓
Normalize
 ↓
Chunk
 ↓
Embedding
 ↓
Index
```

已有 Qdrant 能力优先复用。

## Embedding

Embedding Model 进入 Model Registry：

``` text
capability = EMBEDDING
```

## Retrieval

第一阶段：

``` text
semantic search
```

随后：

``` text
keyword
hybrid
rerank
```

## Agent RAG

Agent 配置：

``` text
Knowledge Bases:
[x] Project Docs
[x] My Documents
```

运行：

``` text
Question
 ↓
Retriever
 ↓
Context
 ↓
Agent
 ↓
Answer
```

## V1.4 验收

-   [ ] Knowledge Base
-   [ ] Document ingestion
-   [ ] Chunking
-   [ ] Embedding
-   [ ] Qdrant
-   [ ] Retrieval
-   [ ] Agent RAG
-   [ ] Knowledge UI
-   [ ] Index progress
-   [ ] E2E RAG

------------------------------------------------------------------------

# 六、V1.5 --- Workflow / Multi-Agent

## 目标

从单 Agent 升级为任务编排平台。

## Workflow

``` text
Workflow
 ├─ Node
 ├─ Edge
 ├─ Variables
 ├─ Input
 └─ Output
```

Node：

``` text
LLM
Agent
Tool
Condition
Loop
Parallel
Human Approval
Input
Output
```

## Execution

支持：

``` text
Sequential
Parallel
Condition
Loop
Retry
Timeout
```

## Multi-Agent

示例：

``` text
Planner
 ↓
Researcher
 ↓
Coder
 ↓
Tester
 ↓
Reviewer
```

每个 Agent 可以拥有：

``` text
不同 Model
不同 Tools
不同 Prompt
```

## Human-in-the-loop

危险操作：

``` text
Shell
File Write
Network
Publish
```

允许：

``` text
Pause
 ↓
User Approval
 ↓
Continue
```

## UI

第一阶段：

``` text
Workflow List
Workflow Form
Run
Trace
```

后续再做：

``` text
Node Graph Editor
```

## V1.5 验收

-   [ ] Workflow Engine
-   [ ] Node / Edge
-   [ ] Sequential
-   [ ] Parallel
-   [ ] Condition
-   [ ] Loop
-   [ ] Retry
-   [ ] Human Approval
-   [ ] Multi-Agent
-   [ ] Trace
-   [ ] API
-   [ ] UI

------------------------------------------------------------------------

# 七、V1.6 --- Developer Platform

## 目标

让第三方可以基于 ModelForge 开发。

## API

统一：

``` text
/v1/models
/v1/chat/completions
/v1/embeddings
/v1/agents
/v1/knowledge
/v1/workflows
```

## SDK

优先：

``` text
Python SDK
HTTP API
OpenAI Compatible API
```

Python 示例：

``` python
client.models.list()
client.models.load()
client.chat.completions.create(...)
client.agents.run(...)
client.knowledge.search(...)
client.workflows.run(...)
```

## Plugin System

插件可以提供：

``` text
Tool
Model Provider
Embedding Provider
Workflow Node
UI Extension
```

PluginManifest：

``` text
id
name
version
permissions
entrypoint
dependencies
```

## Plugin Permission

例如：

``` text
filesystem.read
filesystem.write
network.request
process.execute
database.read
```

安装前展示权限。

## V1.6 验收

-   [ ] Python SDK
-   [ ] API
-   [ ] API Auth
-   [ ] Plugin System
-   [ ] Permission
-   [ ] Developer Docs
-   [ ] Example Plugin
-   [ ] Example Agent
-   [ ] Example Workflow

------------------------------------------------------------------------

# 八、V1.7 --- Package / Marketplace Foundation

## 目标

先建立可导入、导出、安装的 Package 体系，不急着做大型在线商城。

## Model Package

``` text
manifest.json
metadata
runtime requirements
capabilities
README
license
```

## Agent Package

``` text
agent
prompt
tools
memory configuration
runtime requirements
```

## Tool Package

``` text
manifest
schema
implementation
permissions
version
```

## Workflow Package

支持：

``` text
Export
Import
Version
Dependency
```

## Marketplace Foundation

未来可接：

``` text
Model Registry
Agent Registry
Plugin Registry
```

客户端首先支持：

``` text
Local Package
```

## V1.7 验收

-   [ ] Model Package
-   [ ] Agent Package
-   [ ] Tool Package
-   [ ] Workflow Package
-   [ ] Import
-   [ ] Export
-   [ ] Version
-   [ ] Dependency
-   [ ] License metadata

------------------------------------------------------------------------

# 九、V1.8 --- Observability / Evaluation / Security

## Trace

统一：

``` text
Request
 ↓
Agent
 ↓
Model
 ↓
Tool
 ↓
RAG
 ↓
Workflow
```

形成：

``` text
Trace
 └─ Span
     └─ Event
```

## Metrics

至少：

``` text
TTFT
tokens/sec
input tokens
output tokens
latency
RAM
VRAM
CPU
GPU
tool latency
RAG latency
```

## Evaluation

增加：

``` text
EvaluationDataset
EvaluationRun
EvaluationResult
```

指标：

``` text
success rate
accuracy
JSON validity
tool success
latency
token usage
```

## Agent Evaluation

支持：

``` text
Agent A
vs
Agent B
```

同 Dataset 比较：

``` text
成功率
耗时
工具调用
错误率
Token
```

## Security

重点：

``` text
Path Traversal
Command Injection
SSRF
Prompt Injection
Secret Leakage
Plugin Abuse
File Permission
API Authentication
```

## Secret Manager

API Key：

``` text
OpenAI
Anthropic
Remote Providers
```

必须使用：

``` text
OS Keychain
```

或项目已有安全方案。

## V1.8 验收

-   [ ] Trace
-   [ ] Metrics
-   [ ] Evaluation
-   [ ] Security Audit
-   [ ] Secret Manager
-   [ ] Tool Sandbox
-   [ ] API Auth
-   [ ] Audit Log

------------------------------------------------------------------------

# 十、V1.9 --- Production Hardening

这一版本原则：

> **少加功能，重点提高稳定性。**

## Crash Recovery

Runtime 崩溃：

``` text
Detect
 ↓
ERROR
 ↓
Release Resource
 ↓
Release Lease
 ↓
Allow Reload
```

## Training Recovery

训练进程异常：

``` text
Detect
 ↓
Update Task
 ↓
Release Lease
 ↓
Preserve Logs
```

## Startup Recovery

启动：

``` text
Scan Models
 ↓
Validate Files
 ↓
Clear Stale Runtime
 ↓
Recover Tasks
 ↓
Ready
```

## Performance

建立 benchmark：

``` text
Startup
Model Load
Model Unload
TTFT
Tokens/sec
RAG
Agent
Workflow
Memory
VRAM
```

## Cache

按需增加：

``` text
Metadata Cache
Embedding Cache
Retrieval Cache
Prompt Cache
```

必须有明确失效策略。

## Upgrade

支持：

``` text
Database Migration
Config Migration
Model Metadata Migration
Plugin Migration
```

## V1.9 验收

-   [ ] Runtime Recovery
-   [ ] Training Recovery
-   [ ] Startup Recovery
-   [ ] Performance Benchmark
-   [ ] Memory Leak Test
-   [ ] Migration Test
-   [ ] Upgrade Test
-   [ ] Windows/macOS/Linux Regression

------------------------------------------------------------------------

# 十一、V2.0 --- ModelForge Local AI Platform

V2.0 不是"再增加几个页面"，而是完成平台化。

最终：

``` text
Models
Chat
Agents
Knowledge
Training
Workflows
Tools
Plugins
Runtime
API
SDK
Evaluation
Trace
```

全部统一。

------------------------------------------------------------------------

# 十二、V2.0 Model Platform

完整生命周期：

``` text
Discover
 ↓
Download
 ↓
Install
 ↓
Register
 ↓
Analyze
 ↓
Capability
 ↓
Load
 ↓
Inference
 ↓
Unload
 ↓
Remove
```

支持：

``` text
Local
Remote
Multi Runtime
Multi Model
```

------------------------------------------------------------------------

# 十三、V2.0 Agent Platform

Agent：

``` text
Model
Tools
Memory
RAG
Workflow
Trace
Evaluation
```

统一运行。

------------------------------------------------------------------------

# 十四、V2.0 Training Platform

最终：

``` text
Base Model
 ↓
Dataset
 ↓
Training Config
 ↓
Training
 ↓
Artifact
 ↓
Register
 ↓
Evaluate
 ↓
Deploy
```

训练产物能够：

``` text
Load
Chat
Agent
API
```

如果是 LoRA Adapter，必须明确：

``` text
Adapter
+
Base Model
```

是否支持直接推理，取决于实际 Runtime 能力，不能虚假标记。

------------------------------------------------------------------------

# 十五、V2.0 Developer Platform

开发者可以：

``` text
ModelForge SDK
 ↓
Models
Agents
Tools
RAG
Workflow
Runtime
```

开发：

``` text
自己的 Agent
自己的 Tool
自己的 Runtime Adapter
自己的 Workflow
```

------------------------------------------------------------------------

# 十六、V2.0 OpenAI Compatible API

至少：

``` http
GET  /v1/models
POST /v1/chat/completions
POST /v1/embeddings
```

并提供：

``` http
POST /v1/agents/{id}/runs
POST /v1/workflows/{id}/runs
```

外部应用：

``` text
Flutter
Web
Python
Java
Node.js
IDE
第三方 Agent
```

均可以连接 ModelForge。

------------------------------------------------------------------------

# 十七、V2.0 Dashboard

首页显示：

``` text
System Status

Loaded Models
CPU
RAM
GPU
VRAM

Recent Chats
Recent Agent Runs
Training Tasks
Knowledge Bases
Runtime Status
Errors
```

------------------------------------------------------------------------

# 十八、V2.0 Unified Task Center

统一：

``` text
Download
Training
Embedding
Indexing
Agent
Workflow
```

为：

``` text
Task
```

字段：

``` text
task_id
type
status
progress
started_at
finished_at
error
metadata
```

------------------------------------------------------------------------

# 十九、V2.0 Unified Event System

事件：

``` text
ModelEvent
RuntimeEvent
AgentEvent
ToolEvent
TrainingEvent
KnowledgeEvent
WorkflowEvent
TaskEvent
```

第一阶段可以 polling，成熟后使用 SSE/WebSocket。

------------------------------------------------------------------------

# 二十、V2.0 数据模型

核心实体：

``` text
Model
Runtime
RuntimeInstance
Agent
AgentRun
Tool
ToolCall
Memory
KnowledgeBase
Document
Embedding
Workflow
WorkflowRun
TrainingTask
TrainingArtifact
Package
Plugin
Trace
Evaluation
Task
```

所有实体统一：

``` text
id
status
created_at
updated_at
```

------------------------------------------------------------------------

# 二十一、V2.0 ID 规范

统一：

``` text
model_id
runtime_id
instance_id
agent_id
run_id
tool_id
knowledge_id
document_id
workflow_id
task_id
artifact_id
package_id
plugin_id
trace_id
evaluation_id
```

禁止用：

``` text
name
filename
path
display_name
```

作为跨模块关联 ID。

------------------------------------------------------------------------

# 二十二、V2.0 权限

至少：

``` text
MODEL_READ
MODEL_WRITE
RUNTIME_CONTROL
CHAT
AGENT_RUN
TOOL_EXECUTE
FILE_READ
FILE_WRITE
NETWORK
PROCESS_EXECUTE
TRAINING
KNOWLEDGE_READ
KNOWLEDGE_WRITE
PLUGIN_INSTALL
```

核心原则：

``` text
LLM ≠ Trusted Code
```

所有：

``` text
Shell
Python
Network
File Write
```

必须经过：

``` text
Permission
Policy
Executor
Audit
```

------------------------------------------------------------------------

# 二十三、V2.0 测试体系

``` text
Unit
 ↓
Service
 ↓
API
 ↓
Runtime
 ↓
Integration
 ↓
E2E
 ↓
Performance
 ↓
Security
```

必须有以下 E2E：

### Model

``` text
Download
 ↓
Register
 ↓
Load
 ↓
Chat
 ↓
Unload
```

### Agent

``` text
Model
 ↓
Agent
 ↓
Tool
 ↓
Memory
 ↓
Final
```

### RAG

``` text
Document
 ↓
Index
 ↓
Retrieve
 ↓
Agent
 ↓
Answer
```

### Training

``` text
Base Model
 ↓
Dataset
 ↓
Training
 ↓
Artifact
 ↓
Register
 ↓
Load
 ↓
Chat
```

### Workflow

``` text
Input
 ↓
Planner
 ↓
Research
 ↓
Tool
 ↓
Coder
 ↓
Review
 ↓
Output
```

### External API

``` text
External Client
 ↓
/v1/models
 ↓
/v1/chat/completions
 ↓
Runtime
 ↓
Response
```

------------------------------------------------------------------------

# 二十四、跨版本不可违反的架构原则

## 1. Model Registry 是唯一模型事实来源

禁止出现：

``` text
ChatModels
TrainingModels
AgentModels
```

三套独立模型列表。

必须：

``` text
ModelRegistry
```

统一提供。

## 2. Runtime Manager 是唯一模型执行入口

禁止：

``` text
Chat → llama_cpp
Agent → llama_cpp
API → llama_cpp
```

正确：

``` text
Chat ─┐
Agent ├→ ModelRuntimeManager → RuntimeAdapter
API  ─┘
```

## 3. Agent 不直接操作模型路径

统一：

``` text
agent
 ↓
model_id
 ↓
resolver
 ↓
runtime
```

## 4. UI 不直接操作 Runtime

统一：

``` text
UI
 ↓
API
 ↓
Service
 ↓
RuntimeManager
```

## 5. Tool 不得绕过权限

统一：

``` text
Agent
 ↓
Permission
 ↓
ToolExecutor
 ↓
Tool
```

------------------------------------------------------------------------

# 二十五、每个版本的开发顺序

每个版本严格：

``` text
1. 阅读现有代码
2. 输出架构差异
3. Schema / Migration
4. Service
5. API
6. UI
7. Unit Test
8. Integration Test
9. E2E
10. Documentation
```

禁止：

``` text
先改 UI
再临时补 API
最后再补数据库
```

------------------------------------------------------------------------

# 二十六、Codex 执行规则

Codex / OpenCode 执行本路线时：

1.  先读后改。
2.  优先复用已有 Service。
3.  不删除现有功能。
4.  不重复实现 Model Registry。
5.  不重复实现 Runtime。
6.  不改变现有 Chat Memory。
7.  不改变 Dataset / Training 核心逻辑。
8.  数据库变更必须 migration。
9.  跨模块关联统一使用 ID。
10. UI 不保存模型绝对路径作为业务 ID。
11. Agent 不直接实例化 Runtime。
12. Tool 必须经过 Permission。
13. 所有异步任务必须有状态。
14. 所有资源必须能够释放。
15. 每个 Phase 独立测试。
16. 每个 Phase 完成后才能进入下一个 Phase。
17. 当前 Runtime 不支持的能力必须明确标记 unavailable。
18. 不为了未来功能提前实现复杂系统。

------------------------------------------------------------------------

# 二十七、推荐开发方式

**不要把 V1.1 → V2.0 一次性扔给 Codex。**

正确方式：

``` text
总路线图
   ↓
V1.1 独立任务书
   ↓
开发
   ↓
测试
   ↓
验收
   ↓
V1.2 独立任务书
   ↓
开发
   ↓
测试
   ↓
验收
   ↓
……
   ↓
V2.0
```

本文件作为：

``` text
Roadmap
Architecture
Dependencies
Definition of Done
```

每次真正开发时，再生成具体版本任务书：

``` text
V1.1_TASK.md
V1.2_TASK.md
V1.3_TASK.md
...
V2.0_TASK.md
```

------------------------------------------------------------------------

# 二十八、最终产品形态

V1.0：

``` text
Local Model Manager
```

V1.1：

``` text
Local Agent Runtime
```

V1.2：

``` text
Multi-Runtime AI
```

V1.3：

``` text
Multi-Model AI Runtime
```

V1.4：

``` text
Local Knowledge AI
```

V1.5：

``` text
AI Workflow / Multi-Agent Platform
```

V1.6：

``` text
AI Developer Platform
```

V1.7：

``` text
AI Package Ecosystem
```

V1.8：

``` text
Observable / Evaluatable / Secure AI Platform
```

V1.9：

``` text
Production-grade Local AI Runtime
```

V2.0：

``` text
ModelForge Local AI Platform
```

------------------------------------------------------------------------

# 二十九、最终闭环

``` text
                         ModelForge
                             │
               ┌─────────────┼─────────────┐
               ↓             ↓             ↓
             Models        Agents       Training
               │             │             │
               ↓             ↓             ↓
            Runtime        Tools         Dataset
               │             │             │
               └─────────────┼─────────────┘
                             ↓
                          Knowledge
                             ↓
                          Workflow
                             ↓
                         Evaluation
                             ↓
                           Trace
                             ↓
                         API / SDK
                             ↓
                      Third-party Apps
```

最终用户体验：

``` text
下载模型
 ↓
加载模型
 ↓
Chat
 ↓
创建 Agent
 ↓
给 Agent Tools
 ↓
绑定 Knowledge
 ↓
执行 Workflow
 ↓
查看 Trace
 ↓
Evaluation
 ↓
通过 API 给其他 App 使用
```

最终目标：

> **ModelForge 不再是"模型下载 + Chat + Training
> 三个功能拼在一起"，而是以 Model Registry 和 Runtime Manager
> 为底座，向上统一承载
> Chat、Agent、Knowledge、Training、Workflow、Plugin、SDK 和 API 的
> Local AI Platform。**

------------------------------------------------------------------------

# 三十、V2.0 最终 Definition of Done

## Model

-   [ ] Registry
-   [ ] Lifecycle
-   [ ] Capability
-   [ ] Download
-   [ ] Install
-   [ ] Load
-   [ ] Unload
-   [ ] Multi Model

## Runtime

-   [ ] Runtime Manager
-   [ ] Adapter
-   [ ] llama.cpp
-   [ ] Transformers
-   [ ] Remote
-   [ ] Resource Manager
-   [ ] LRU
-   [ ] Recovery

## Chat

-   [ ] Local
-   [ ] Remote
-   [ ] Streaming
-   [ ] Session
-   [ ] Memory

## Agent

-   [ ] Definition
-   [ ] Runtime
-   [ ] Tools
-   [ ] Permission
-   [ ] Memory
-   [ ] RAG
-   [ ] Trace
-   [ ] Evaluation

## Knowledge

-   [ ] Knowledge Base
-   [ ] Document
-   [ ] Chunk
-   [ ] Embedding
-   [ ] Vector Search
-   [ ] Retrieval
-   [ ] RAG

## Training

-   [ ] Dataset
-   [ ] Base Model
-   [ ] LoRA
-   [ ] Training Task
-   [ ] Artifact
-   [ ] Registration
-   [ ] Evaluation
-   [ ] Deployment

## Workflow

-   [ ] Workflow
-   [ ] Node
-   [ ] Edge
-   [ ] Sequential
-   [ ] Parallel
-   [ ] Condition
-   [ ] Loop
-   [ ] Retry
-   [ ] Human Approval
-   [ ] Multi-Agent

## Developer

-   [ ] REST API
-   [ ] OpenAI Compatible API
-   [ ] Python SDK
-   [ ] Plugin System
-   [ ] Package System
-   [ ] Developer Documentation

## Platform

-   [ ] Dashboard
-   [ ] Task Center
-   [ ] Trace
-   [ ] Metrics
-   [ ] Evaluation
-   [ ] Security
-   [ ] Recovery
-   [ ] Migration
-   [ ] Upgrade

------------------------------------------------------------------------

# 三十一、最终一句话

**V1.0 打通"模型能跑"；V1.1 打通"模型能成为 Agent 的大脑"；V1.2--V1.5
打通 Runtime、Multi-Model、RAG、Workflow；V1.6--V1.8
建立开发生态和可观测/安全体系；V1.9 做生产级稳定性；V2.0 最终形成完整的
ModelForge Local AI Platform。**
