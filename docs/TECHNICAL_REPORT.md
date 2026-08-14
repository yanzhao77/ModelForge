# ModelForge 3.0 架构与技术报告

> **文档与代码同步声明**：本报告与 `master` 分支当前代码逐项核对（核对时点：本次更新），所有指标均为实测：
> **339 个测试全绿 · 92 条 API 路由 · 14 张数据表 · 真 LangGraph Agent（2.1） + Agent Runtime 3.0 + 3.x Composable Plugin · 5 个客户端标签页**。
>
> 旧版 v2.0 桌面端代码已整体迁移至 `gui_old` 分支（`master` 上已移除）。
>
> 3.0 增量：Agent Run / Event System / Tool Registry / Context Engine / Policy / MCP / Scheduler / Multi-Agent，详见 [AGENT_RUNTIME.md](AGENT_RUNTIME.md) 与 [API_REFERENCE.md](API_REFERENCE.md)。

---

## 目录

1. [项目现状（实测指标）](#1-项目现状实测指标)
2. [架构总览](#2-架构总览)
3. [技术选型](#3-技术选型)
4. [数据库设计](#4-数据库设计)
5. [API 全量清单（58 条，已全部接线）](#5-api-全量清单58-条已全部接线)
6. [后端模块详解](#6-后端模块详解)
7. [Agent Runtime 3.0（新增）](#7-agent-runtime-30新增)
8. [Agent 引擎：真 LangGraph tool loop（2.1，保持兼容）](#8-agent-引擎真-langgraph-tool-loop21保持兼容)
9. [聊天与 SSE 流式](#9-聊天与-sse-流式)
10. [数据集与微调训练](#10-数据集与微调训练)
11. [知识库与 RAG](#11-知识库与-rag)
12. [客户端（PySide6 瘦客户端）](#12-客户端pyside6-瘦客户端)
13. [测试](#13-测试)
14. [依赖分层](#14-依赖分层)
15. [配置](#15-配置)
16. [部署](#16-部署)
17. [分支与版本](#17-分支与版本)
18. [已知边界与后续待办](#18-已知边界与后续待办)
19. [附录 A：开发历程（从空壳到完整实现）](#19-附录-a开发历程从空壳到完整实现)
20. [附录 B：旧版功能迁移映射（历史参考）](#20-附录-b旧版功能迁移映射历史参考)

---

## 1. 项目现状（实测指标）

| 指标 | 数值 | 验证方式 |
|---|---|---|
| 测试 | **339 通过 / 0 失败** | `pytest tests/` 实测 |
| API 路由 | **92 条**（其中 agent 相关 20 条 + plugins 3.x 9 条） | FastAPI 路由表实测（含 /docs、/healthz、/v1/*） |
| 数据库表 | **14 张**（新增 agent_runs / agent_events / tools） | SQLAlchemy metadata 实测 |
| 后端代码 | ~7800 行（api 13 模块 + services 21 模块 + runtime 包 + repositories） | 统计 |
| 客户端代码 | ~2300 行（api_client + 7 页面/组件） | 统计 |
| 测试代码 | ~3500 行（23 个测试文件） | 统计 |
| 分支 | master（新版）/ gui_old（旧版存档） | git |

### 已实现功能全景

- **认证**：注册/登录/me/改密码，JWT（HS256）+ PBKDF2，用户数据隔离
- **会话/消息**：多会话 CRUD、软删除、分页、自动标题、所有权校验
- **跨会话记忆**：规则提取（偏好/事实）、搜索、重要性评分、上下文注入
- **模型管理**：扫描/登记/删除、HF 搜索、后台下载任务+进度
- **推理运行时**：Ollama（SSE 流式）、本地 transformers/GGUF、OpenAI 兼容接口（后两者懒加载）
- **聊天**：统一 chat service + **SSE 流式** + 记忆注入 + 自动持久化
- **Agent**：**真 LangGraph tool loop** + 5 个工具
- **知识库**：持久化、文档管理、分块查看、检索、**RAG 问答**
- **数据集**：jsonl/csv/json/txt 上传/解析/预览/预检/删除
- **微调训练**：full/LoRA 子进程任务、进度/loss、SSE 日志、停止、产物注册
- **OpenAI 兼容**：`/v1/chat/completions`（含流式）+ `/v1/models`
- **系统**：CPU/GPU/内存/磁盘/日志/健康检查

---

## 2. 架构总览

### 2.1 架构图

```
              ┌──────────────────────────────────────┐
              │      PySide6 桌面客户端（瘦客户端）     │
              │  client/pyside6/                      │
              │  聊天 │ 数据集 │ 训练 │ 知识库（标签页）  │
              └───────────────┬──────────────────────┘
                              │ REST (httpx) + SSE 流式
              ┌───────────────▼──────────────────────┐
              │       FastAPI 后端 (backend/app)       │
              │  api/（13 路由模块，前缀 /api/v1）       │
              │  services/（20 业务模块）                │
              │  core/（配置/数据库/安全/日志）           │
              └───┬──────────┬────────────┬───────────┘
                  │          │            │
       ┌──────────▼──┐  ┌────▼─────┐  ┌───▼───────────┐
       │ SQLite       │  │ 推理运行时 │  │ 外部服务        │
       │ SQLAlchemy   │  │ Ollama    │  │ HF Hub /      │
       │ 11 张表      │  │ 本地 HF/  │  │ ModelScope /  │
       │              │  │ GGUF/OpenAI│ │ OpenAI 兼容 API│
       └─────────────┘  └──────────┘  └───────────────┘
```

### 2.2 设计原则（已落地）

1. **后端承载全部业务逻辑**，客户端零业务逻辑（只做展示与交互）。
2. **用户数据按 user_id 隔离**（会话/消息/记忆/模型/数据集/任务均带 user_id）。
3. **推理/下载/训练全部异步化**：训练走子进程，下载走后台任务，日志走 SSE。
4. **聊天流式输出**：SSE 逐 token，客户端打字机渲染。
5. **配置驱动**：可调参数全部进 config.yaml / 环境变量。

---

## 3. 技术选型

| 领域 | 选型 | 落地位置 |
|---|---|---|
| 后端框架 | FastAPI 0.115 / Uvicorn | backend/app/main.py |
| 数据校验 | Pydantic v2 | 各 api 模块内联模型 |
| ORM | SQLAlchemy 2.x | core/database.py + models/records.py |
| 认证 | PyJWT + PBKDF2（原生 hashlib） | core/security.py + services/auth_service.py |
| 配置 | pydantic-settings 风格 + yaml + dotenv | core/config.py |
| HTTP | httpx（客户端与服务端均用） | services/、client/api_client |
| 流式 | StreamingResponse（SSE） | api/chat.py、api/train.py、api/openai_api.py |
| Agent | langgraph + langchain-core | services/agent_engine.py |
| 本地推理 | transformers + llama-cpp-python（懒加载） | services/runtimes/local_runtime.py |
| 在线搜索 | duckduckgo_search | services/searcher.py |
| 向量检索 | numpy TF-IDF（内存 + 可选 DB 持久化） | services/knowledge_base.py |
| 微调 | transformers Trainer + peft | services/runtimes/training_jobs.py |
| 客户端 | PySide6 6.x | client/pyside6/ |
| 测试 | pytest + pytest-asyncio + httpx TestClient | tests/ |
| 部署 | Docker（单阶段）、PyInstaller（预留） | Dockerfile |

---

## 4. 数据库设计

11 张表（models/records.py），全部经 SQLAlchemy 声明式定义：

| 表 | 关键字段 | 用途 |
|---|---|---|
| users | username(unique), password_hash, email | 账户 |
| sessions | user_id, title, model_id, is_active | 会话（软删） |
| messages | session_id, role, content, token_count | 消息 |
| memories | user_id, memory_type, key, value, importance, access_count | 跨会话记忆 |
| models | user_id, name, provider, path, size, status, format, quant | 模型台账 |
| agents | name(unique), user_id, model, tools, memory, system_prompt | Agent 配置 |
| api_keys | user_id, name, key_hash | OpenAI 兼容接口密钥（预留） |
| datasets | user_id, name, file_path, format, row_count, columns, sample | 训练数据集 |
| train_tasks | task_id(unique), user_id, dataset_id, base_model, method, status, progress, loss | 训练任务 |
| knowledge_documents | user_id, filename, filetype, chunk_count | 知识库文档 |
| knowledge_chunks | doc_id, chunk_index, content, meta | 知识库分块 |

> 迁移策略：当前用 `init_db()` 的 `create_all` 建表（兼容旧库增量建新表）；Alembic 迁移尚未引入（见第 17 节待办）。

---

## 5. API 全量清单（84 条，已全部接线）

所有业务路由统一前缀 `/api/v1`，除 register/login 外均需 Bearer Token（chat 与 knowledge 支持匿名/可选认证）。

| 模块 | 端点（已实现） | 说明 |
|---|---|---|
| auth | /auth/register · /auth/login · /auth/me · /auth/change-password | 认证 |
| sessions | /sessions（GET/POST）· /sessions/{id}（GET/PATCH/DELETE）· /sessions/{id}/messages · /sessions/{id}/title | 会话与消息 |
| memories | /memories（GET/POST）· /memories/search · /memories/{id}（PATCH/DELETE） | 记忆 |
| models | /models（GET）· /models/scan · /models/install · /models/{id}（GET/DELETE）· /models/search · /models/download · /models/download/{task_id} | 模型台账 + HF 搜索 + 下载任务 |
| runtime | /runtime/start · /runtime/chat · /runtime/stop · /runtime/status | Ollama 运行时 |
| chat | /chat · /chat/stream（SSE） | 统一聊天 + 流式 |
| datasets | /datasets/upload · /datasets（GET）· /datasets/{id} · /datasets/{id}/validate · /datasets/{id}（DELETE） | 数据集管理 |
| train | /train/start · /train/status/{id} · /train/stream/{id}（SSE）· /train/stop/{id} · /train/tasks · /train/templates · /train/{id}/register-model | 训练任务 |
| knowledge | /knowledge/upload · /knowledge/documents · /knowledge/documents/{name}（DELETE）· /knowledge/documents/{name}/chunks · /knowledge/query · /knowledge/answer（RAG）· /knowledge/stats | 知识库 |
| agent | /agent/create · /agent/list · /agent/{name}/chat | Agent |
| plugins | /plugins · /plugins/install-all · /plugins/{name}/install | 插件（已接线，目录为空） |
| openai | /v1/chat/completions（含流式）· /v1/models | OpenAI 兼容 |
| system | /system/status · /system/logs | 监控 |
| 其他 | / · /healthz · /docs · /redoc · /openapi.json | 入口 |

接线方式：`backend/app/main.py` 用 `lifespan` 初始化 DB 并注入单例（runtime/agent/knowledge/plugin），然后 `include_router` 全部路由模块。

---

## 6. 后端模块详解

### 6.1 core/（基础设施）

| 模块 | 职责 |
|---|---|
| config.py | Settings（pydantic）+ load_config（yaml → .env → 环境变量），进程级 settings 单例 |
| database.py | engine/SessionLocal/Base/get_db/init_db（SQLite，check_same_thread=False） |
| security.py | PBKDF2 哈希、JWT 签发/校验、get_current_user / get_current_user_optional 依赖 |
| logging_config.py | 控制台 + 文件双 handler 日志 |
| plugin_base.py | SPI 基类（Plugin/ModelPlugin/ToolPlugin/RuntimePlugin） |

### 6.2 services/（业务层，20 模块）

| 模块 | 职责 | 关键实现 |
|---|---|---|
| auth_service | 注册/登录/改密码 | 用户名 3-32、密码 ≥6、唯一性校验 |
| session_service | 会话/消息 CRUD、自动标题 | 所有权校验、游标分页、首条用户消息取 30 字标题 |
| memory_store | DB 版记忆：提取/搜索/格式化 | 中文关键词规则（偏好 0.8 / 事实 0.9）、LIKE 检索、重要性排序 |
| memory | 内存版 ConversationMemory/LongTermMemory | 兼容既有 phase9 测试 |
| model_manager | 模型台账 | 扫描（文件/目录识别）、大小格式化、可选 user 隔离 |
| hf_provider / ms_provider / model_provider | 模型源抽象 | HF 搜索/下载、ModelScope 懒加载 |
| downloader | 后台下载任务 | asyncio 任务 + 信号量 + 内存任务注册表 + HF 搜索 |
| runtime_registry | 运行时注册表 | 懒加载 Ollama/本地/OpenAI，LRU 上限 3，委托 load/chat/stop |
| ollama_runtime | Ollama 实现 | chat + **stream_chat（NDJSON→chunk 生成器）** |
| runtimes/local_runtime | 本地 transformers/GGUF | 懒导入 torch/llama_cpp，GGUF/目录识别，OOM 降级 |
| runtimes/openai_api_runtime | OpenAI 兼容接口 | 懒导入 openai 库，参数透传 |
| chat_service | 统一聊天 | 历史 + 记忆注入 → runtime → 持久化 → 自动标题；run_chat/stream_chat |
| agent_engine | 真 LangGraph Agent | 见第 7 节 |
| agent_tools | 工具注册表 | file_read/code_search/command_execute/web_search/knowledge_search |
| knowledge_base | RAG | 上传→分块→TF-IDF→检索；DB 持久化（懒加载重建索引）；answer（检索+生成） |
| dataset_service | 数据集 | jsonl/csv/json/txt 解析、预览、预检、删除 |
| training | 训练任务管理 | 子进程启动、状态轮询落库、停止=terminate、register-model |
| runtimes/training_jobs | 训练执行（CLI） | TrainerCallback 上报进度/loss 到 state 文件，full/LoRA |
| searcher | 在线搜索 | DDGS + lru_cache + 关键词触发 |
| plugin_manager | 插件注册/执行 | register/unregister/list/execute/install_all |

---

## 7. Agent Runtime 3.0（新增）

> 从 2.1 的"功能集合"演进为 Local-first Agent Runtime Platform（spec 见 AGENT_RUNTIME_DEVELOPMENT.md）。
> 架构文档：[AGENT_RUNTIME.md](AGENT_RUNTIME.md)；API：[API_REFERENCE.md](API_REFERENCE.md)。

### 7.1 新增对象与存储

| 对象 | 表 | 说明 |
|---|---|---|
| Agent | agents（扩展列） | 新增 policy / runtime_config / knowledge_config / description / status |
| Run | agent_runs | PENDING/RUNNING/WAITING_TOOL/WAITING_HUMAN/COMPLETED/FAILED/CANCELLED/TIMEOUT，全量持久化 |
| Event | agent_events | 23 类事件，(run_id, sequence) 联合索引，SSE 可断线恢复 |
| Tool | tools | 统一 Tool 协议；builtin/MCP/plugin 统一注册 |

### 7.2 已实现模块（backend/app/runtime/）

- **ExecutionEngine**：Create Run -> Load Agent -> Context -> LLM -> Tool Loop；max_iterations(20)/max_tool_calls(50)/timeout(600s)；CancellationToken 取消；并发 run 无全局状态。
- **EventBus + EventStore**：进程内 pub/sub + 异步持久化 + SSE（`/agent/runs/{id}/stream?after_sequence=N` 先回放再实时）。
- **ToolRegistry + ToolExecutor**：schema/权限/超时/重试；legacy 名称别名保留（spec 67）。
- **ContextBuilder**：System + Session History + Memory + Knowledge + 预算裁剪。
- **PolicyEngine**：默认拒绝网络/shell/写文件系统；`human_approval_required` 人工门（approve/reject 端点）。
- **MCP**：MCPRegistry/MCPClient/MCPToolAdapter，工具自动进 ToolRegistry。
- **Scheduler**：schedule_once/interval/cancel，触发创建 Run。
- **Multi-Agent**：`agent.delegate` 工具（嵌套 Run + 同步等待，禁止自委托）。
- **Metrics / 结构化日志**：`/agent/metrics`；run 日志带 run_id/agent_id/session_id。

### 7.3 API 一览（3.0 增量，全部 /api/v1/agent/*）

`POST/GET /agent/runs`、`GET /agent/runs/{id}`、`POST /agent/runs/{id}/cancel|approve|reject`、`GET /agent/runs/{id}/events|stream`、`GET /agent/tools`、`POST/GET/DELETE /agent/mcp/servers`、`POST/GET/DELETE /agent/schedules`、`GET /agent/metrics`。

## 8. Agent 引擎：真 LangGraph tool loop（2.1，保持兼容）

`services/agent_engine.py` 使用 `langgraph.graph.StateGraph` 构建真实工具循环（已核对代码）：

```
  Agent (call_model)
     │
     ▼
   LLM (llm.bind_tools(tools))
     │
     ▼
  Tool Call ?
   ├── No ──────▶ END
   └── Yes
         │
         ▼
      ToolNode
         │
         └────────▶ Agent（循环）
```

### 实现要点（与代码一一对应）

- **状态**：`AgentState(TypedDict)` + `messages: Annotated[list, add_messages]`（LangGraph 消息累加 reducer）。
- **图结构**：`StateGraph` → `add_node("agent", call_model)` → `add_node("tools", ToolNode(tools))` → `set_entry_point("agent")` → `add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})` → `add_edge("tools", "agent")` → `compile()`。
- **条件路由**：`should_continue` 检查最后一条消息的 `tool_calls`，有则进 ToolNode，无则 END。
- **LLM 注入**：`chat(name, msg, llm=None, llm_callback=None)` —— 真实部署传 LangChain 兼容 LLM；测试/简单场景用 `_CallbackLLM` shim 包装字符串回调；两者都没有时返回静态工具说明。
- **消息类型**：全程使用 `HumanMessage` / `AIMessage` / `ToolMessage`（langchain_core.messages）。
- **工具**：`AGENT_TOOLS` 注册表 5 个工具 —— file_read、code_search、command_execute、web_search（接 searcher）、knowledge_search（接全局知识库）。

### 验证

- `tests/test_api_integration.py::TestLangGraphAgent::test_tool_calling_loop`：构造带 tool_calls 的 LLM → 验证 Human→AI(toolcall)→Tool→AI 四步循环与 `ToolMessage` 落盘。
- 消息历史以 LangChain 对象持久化于 `agent["messages"]`（`test_chat_preserves_history` 验证 4 条消息结构与内容）。

---

## 9. 聊天与 SSE 流式

- **统一入口** `services/chat_service.py`：
  1. 有 session 时：加载历史（≤50 条）→ 记忆注入（`[系统记忆]\n问题`）→ 追加用户消息 → 调 runtime；
  2. 无 session：直接透传 messages（匿名可用）；
  3. 完成后：保存 user/assistant 两条消息 → 首轮自动生成标题 → 提取并保存记忆。
- **流式**：`POST /api/v1/chat/stream` 返回 `text/event-stream`，事件格式 `{"type":"delta"|"done"|"error","data":...}`；优先走 `runtime.stream_chat`（Ollama NDJSON 逐 token），无流式实现时回退整段。
- **客户端**：`StreamWorker(QThread)` 消费 SSE 生成器，`insertPlainText` 逐 chunk 打字机渲染。

---

## 10. 数据集与微调训练

### 数据集（`services/dataset_service.py` + `api/datasets.py`）

- 上传：multipart + Form 名称参数；扩展名白名单（jsonl/csv/json/txt）+ 大小上限（200MB，`max_dataset_size`）。
- 解析：jsonl（对象/标量行）、csv（DictReader 表头探测）、json（数组/{"train":[]}/单对象）、txt（每行一条）；产出 row_count/columns/sample(前 5 行)。
- 预检：`/datasets/{id}/validate` 返回 `{ok, row_count, columns}`，供训练前校验。

### 训练（`services/training.py` + `runtimes/training_jobs.py` + `api/train.py`）

- **架构：子进程隔离**（torch 训练不能跑在 FastAPI 事件循环内）：
  1. `POST /train/start`：校验 torch 可用 + 数据集 → 写 `train_tasks` 表 → 写 config.json → `subprocess.Popen` 启动 `training_jobs.py --config --state --log`；
  2. 子进程：加载模型 →（LoRA: peft LoraConfig）→ 加载数据集 → Trainer + **ProgressCallback**（on_log 把 progress/epoch/loss 写入 state.json）→ 保存到 output_dir；
  3. 父进程 `_poll` 线程每 2s 读 state.json 落库（进度/epoch/loss/状态）；
  4. 取消：`/train/stop` → `proc.terminate()` → 状态置 stopped；
  5. 产物：`/train/{id}/register-model` → `ModelManager.install`（provider=training，format=safetensors 或 peft-adapter）→ 模型列表可见。
- **SSE 日志流**：`/train/stream/{id}` 增量尾读 train.log + state.json，推送 log/progress/done 事件。
- **模板**：`/train/templates` 返回 full/lora 默认超参。

---

## 11. 知识库与 RAG

- **持久化**：上传时写 `knowledge_documents` + `knowledge_chunks`（content + meta JSON）；进程启动/首次访问时懒加载重建内存 TF-IDF 索引。
- **检索**：`/knowledge/query` → 余弦相似度 top_k，返回 `{source, score, text, chunk_index}`。
- **RAG 问答**：`/knowledge/answer` → 检索 top_k → 拼 `[知识库内容]...\n\n问题` → 调运行时生成 → 返回 `{answer, sources}`（引用来源+评分）。
- **文档管理**：`/knowledge/documents`（列表）、DELETE（按文件名，清 DB+内存）、`/{name}/chunks`（分块查看）。
- **与聊天/Agent 联动**：聊天页"知识库(RAG)"开关走 `/answer`；Agent 的 `knowledge_search` 工具共享同一全局 KB。

---

## 12. 客户端（PySide6 瘦客户端）

- **api_client/client.py**：REST + SSE 客户端，Bearer token 管理，覆盖全部端点（auth/models/runtime/chat/sessions/memories/datasets/train/knowledge/agent/system），`stream_chat`/`train_stream` 返回 SSE 事件迭代器。
- **页面（pages/，5 个文件）**：
  - `login_dialog.py`：登录/注册对话框；
  - 主窗口 **4 个标签页**：聊天（会话侧边栏 + SSE 流式聊天 + 知识库开关）/ 数据集（上传/列表/预览/预检/删除）/ 训练（配置表单+数据集下拉联动+任务列表+进度/loss/日志+停止+注册模型）/ 知识库（文档管理/分块/检索/RAG 问答）；
  - 另有模型中心、GGUF 下载器对话框（菜单入口）。
- **线程模型**：SSE 消费在 QThread，QTimer 轮询训练/任务状态，UI 不阻塞。

---

## 13. 测试

**152 个用例 · 13 个文件**，四层覆盖：

| 层 | 文件 | 内容 |
|---|---|---|
| 结构/配置 | test_structure、test_phase1_backend | 目录结构、FastAPI 根端点、config 三层加载 |
| 单元 | test_phase2~phase11 | DB CRUD、模型管理、provider、运行时、client、Agent 工具、RAG、记忆、插件、工程 |
| API 集成 | test_api_integration（20 用例） | 认证流、会话/记忆/模型 API、聊天（SSE）、OpenAI 兼容、真 LangGraph 工具循环 |
| 数据集/训练/知识库 | test_dataset_service（解析器单测）、test_train_kb（20 用例） | 数据集解析、训练任务状态机（mock 子进程）、知识库持久化 + RAG |

训练相关用例通过 `monkeypatch` mock 子进程（`_launch`）与 `_torch_available`，不依赖真实 GPU，CI 可跑。

---

## 14. 依赖分层

| 文件 | 内容 | 用途 |
|---|---|---|
| requirements.txt（14 行） | fastapi/uvicorn/sqlalchemy/pydantic/dotenv/yaml/httpx/jwt/numpy/hf_hub/langgraph/langchain-core/multipart/psutil | 后端 base，CI 秒级安装 |
| requirements-dev.txt | pytest/pytest-asyncio/ruff | 开发/测试 |
| requirements-gui.txt | PySide6/Markdown | 桌面客户端 |
| requirements-ai.txt | torch/transformers/llama-cpp-python/datasets/peft/openai/duckduckgo_search | AI 推理/训练（按需） |

> 已解决历史问题：`torch==2.2.0+cu118` 不再进 CI（macOS 装不上、CI 拖慢）。

---

## 15. 配置

`config.yaml` 默认值 + 环境变量覆盖（`MODEL_PATH`、`DATABASE_PATH`、`JWT_SECRET`、`OLLAMA_BASE_URL`、`HF_ENDPOINT`、`DATASET_DIR`、`TRAIN_OUTPUT_DIR`、`MAX_DATASET_SIZE` 等）。完整 Settings 见 `core/config.py`。

---

## 16. 部署

- **Docker**：`Dockerfile` 基于 python:3.10-slim，装 base 依赖（不含 torch），`CMD uvicorn backend.app.main:app`。
- **本地**：`uvicorn backend.app.main:app --reload --port 8000`（详见 README）。
- **客户端**：`python client/pyside6/main.py`，通过 `MF_BACKEND_URL`/默认 http://localhost:8000 连后端。

---

## 17. 分支与版本

| 分支 | 内容 | 状态 |
|---|---|---|
| master | 新版架构（本报告描述的全部内容） | 152 测试全绿，已推送远程 |
| gui_old | 旧版 v2.0 桌面端存档（gui/pytorch/api/database/...） | 只读参考，不再维护 |

版本：v2.1（后端 root 返回 `{"name":"ModelForge","version":"2.1","status":"ok"}`）。

## 17.5 3.x Composable Agent & Tool Plugin（新增）

> 详细架构见 [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md)。

| Phase | 内容 |
|---|---|
| P0 加固 | Policy 下沉 ToolExecutor（权威兜底）/ 2.1 路径策略门 / 内存清理 / 事件失败可见 / 终态 try-finally |
| P1 Scope | PluginScope + PluginContext（作用域挂载/卸载 + per-plugin 句柄，单一注册表） |
| P2 Manager | PluginManager：manifest / 发现 / 依赖 / 生命周期 / 挂载卸载 + plugin.* 事件（复用 EventBus）+ API |
| P3 组合 | AgentConfig.plugins + AgentPlugin（extend_agent 行为扩展）+ 策略合并 |
| P4 贡献 | ContextContributor 协议 + SkillPlugin（技能/知识注入，优先级排序） |
| P5 护栏 | parent_run_id / 深度 / 循环 / 子数限制 / 取消级联 / 预算传播 |
| P6 发现 | Capability Discovery（工具/技能/Agent 扩展索引 + scope 过滤 + API） |

新增 API：`/api/v1/plugins/{discover,load,capabilities}`、`/api/v1/plugins/{name}/{start,stop,mount,unmount}`、`DELETE /api/v1/plugins/{name}`。

---

## 18. 已知边界与后续待办

| # | 项 | 状态说明 |
|---|---|---|
| 1 | 本地推理/训练真机验证 | 代码就绪、状态机有 mock 测试；需安装 requirements-ai.txt 后在真实模型上验证（CPU 小模型即可） |
| 2 | LoRA 产物加载 | 训练产物注册为 peft-adapter，LocalRuntime 尚未实现 base+adapter 组合加载分支 |
| 3 | Alembic 迁移 | 当前用 create_all；引入 Alembic 基线迁移是工程化待办 |
| 4 | 下载任务持久化 | downloader 任务注册表为内存态（train_tasks 已落库） |
| 5 | 插件示例 | plugins/ 目录为空（SPI 已接线，无示例插件） |
| 6 | Agent 生产接入 | Agent 的 LLM 需外部注入（测试用 _CallbackLLM shim），生产需接 LangChain ChatOpenAI/自定义运行时 |
| 7 | api_keys 使用 | OpenAI 兼容接口目前未强制鉴权，api_keys 表预留 |
| 8 | 3.0 Agent Runtime 真机验证 | ExecutionEngine 全套测试用 MockProvider；接真实 Ollama 的 tool-calling 已验证 Provider 适配层但未跑真机模型 |
| 9 | Agent 定义持久化 | agents 表已扩展并写入（policy/runtime_config 等），DB 与 AgentEngine 内存注册表以 DB 优先合并 |
| 10 | 事件保留 | agent_events 支持 delete_older_than 接口，尚未接入自动清理任务 |
| 11 | MCP 传输 | 仅 HTTP JSON-RPC；stdio/SSE 传输留接口未实现 |
| 12 | 分布式调度 | Scheduler 为进程内 asyncio；跨进程/持久化调度未实现 |

---

## 19. 附录 A：开发历程（从空壳到完整实现）

> 以下为历史记录（对应旧文档中"待修复"清单的最终结果），当前代码已全部落实。

| 原问题 | 解决方式（已落地） |
|---|---|
| 后端只有根路由，4 个 router 未接线、无 /models 路由 | main.py lifespan 注入 + include_router（/api/v1 前缀），新增 models/datasets/train 等路由，58 条 |
| requirements.txt 缺 sqlalchemy/dotenv/yaml/langgraph/langchain-core，CI 必挂 | 依赖拆分四份并补全，CI 秒级安装 |
| test_download 硬编码 /test/cache 只读路径 | 改用 tmp_path fixture |
| AgentEngine 假 LangGraph（死 import） | 重写为真 StateGraph + ToolNode 工具循环（见第 7 节） |
| JWT secret 进程内随机导致重启失效 | settings.jwt_secret 持久化 + 32+ 字节默认值 |
| model_generate 重复定义/None 崩溃/写死路径 | 重构为 LocalRuntime（懒加载、判空、配置化） |
| 记忆/知识库 O(n) 全量重嵌、词表重建丢向量 | 增量词表 + 全量重建策略（上传时统一重嵌，注释说明） |
| trainer_model 参数逗号 tuple bug、E:\\ 写死 | 重写为 training_jobs.py CLI + 配置驱动 |
| datetime.utcnow 弃用、chr(39) 混淆、日志单文件无限增长 | timezone-aware、引号、RotatingFileHandler |
| 客户端页面空目录 | 补齐 5 个页面 + 4 标签页主窗口 + SSE 客户端 |

---

## 20. 附录 B：旧版功能迁移映射（历史参考）

旧版（gui_old 分支）桌面端功能已全部迁移到新版架构：

| 旧版 | 新版去向 |
|---|---|
| gui/login_dialog.py | client/pyside6/pages/login_dialog.py |
| gui/session_sidebar.py + api/session_service.py | client 会话侧边栏 + services/session_service.py + api/sessions.py |
| api/memory_service.py | services/memory_store.py + api/memories.py |
| gui/dialog/gguf_download_dialog.py | services/downloader.py + 客户端下载对话框 + /models/download |
| pytorch/model_generate.py | services/runtimes/local_runtime.py |
| pytorch/interface_generate.py | services/runtimes/openai_api_runtime.py |
| pytorch/webSearcher.py | services/searcher.py |
| pytorch/trainer_model.py / loRA_model.py | services/training.py + runtimes/training_jobs.py |
| interface/api_interface_fastapi.py | api/openai_api.py |
| database/db_manager.py + models/database_models.py | core/database.py + models/records.py |

> 旧版完整代码与运行方式见 `gui_old` 分支。