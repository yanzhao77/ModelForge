# ModelForge API 参考

> 与 `master` 当前代码核对（spec 82）。基础前缀 `/api/v1`；OpenAI 兼容端点保持标准路径 `/v1/*`。

---

## 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/auth/register | 注册 |
| POST | /api/v1/auth/login | 登录（返回 JWT） |
| GET | /api/v1/auth/me | 当前用户 |
| POST | /api/v1/auth/change-password | 改密码 |

## 会话与消息

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/v1/sessions | 会话列表 / 创建 |
| GET/PATCH/DELETE | /api/v1/sessions/{id} | 会话详情 / 改名 / 删除 |
| GET/POST/DELETE | /api/v1/sessions/{id}/messages | 消息列表 / 添加 / 清空 |
| POST | /api/v1/sessions/{id}/title | 自动标题 |

## 记忆

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/v1/memories | 记忆列表 / 创建 |
| GET | /api/v1/memories/search?q= | 检索 |
| DELETE | /api/v1/memories/{id} | 删除 |

## 模型 / 运行时

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST/DELETE | /api/v1/models | 模型列表（支持 `capability`/`status`/`format`/`source` 过滤）/ 登记 / 删除 |
| POST | /api/v1/models/scan | 扫描目录 |
| GET | /api/v1/models/{model_id} | 模型详情（返回 capabilities / metadata / ready / runtime_status） |
| GET | /api/v1/models/default | 当前默认模型（与"已加载模型"无关） |
| POST | /api/v1/models/{model_id}/default | 设为默认模型 |
| POST | /api/v1/models/{model_id}/load | 加载到共享本地运行时（单实例） |
| POST | /api/v1/models/{model_id}/unload | 卸载并释放内存 |
| GET | /api/v1/models/{model_id}/runtime | 该模型的运行时状态 |
| GET | /api/v1/models/search | HF 搜索 |
| POST | /api/v1/models/download | 下载 GGUF |
| GET | /api/v1/models/download/{task_id} | 下载进度 |
| POST | /api/v1/models/download/{task_id}/pause | 暂停下载 |
| POST | /api/v1/models/download/{task_id}/resume | 继续下载 |
| POST | /api/v1/models/download/{task_id}/restart | 重新开始下载（重新校验本地字节，仅重下损坏/缺失部分；不删除共享目录） |
| GET | /api/v1/runtime | 当前活跃运行时实例 + 加载配置（运行时管理员） |
| POST | /api/v1/runtime/start / chat / stop | 推理运行时（模型名解析为注册模型时走统一运行时管理器） |
| GET | /api/v1/runtime/status | 运行时状态 |

## 聊天（2.1 保持兼容）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/chat | JSON 聊天（可选 `model_id`：经注册表解析并自动加载本地模型） |
| POST | /api/v1/chat/stream | SSE 流式（同样支持 `model_id`） |

## Agent（2.1 + 3.0）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/agent/create | 创建 Agent（含 system_prompt/policy/runtime_config/knowledge_config） |
| GET | /api/v1/agent/list | Agent 列表 |
| DELETE | /api/v1/agent/{name} | 删除 Agent |
| POST | /api/v1/agent/{name}/chat | 2.1 LangGraph 对话 |

### Agent Run API（3.0，spec 25）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/agent/runs | 创建 Run（`{agent_id, input, session_id?, metadata?, execute?}`，返回 `{run_id, status}`） |
| GET | /api/v1/agent/runs | 列表（user 隔离；agent_id/status/limit/offset 过滤） |
| GET | /api/v1/agent/runs/{run_id} | Run 详情（状态/输出/token 用量/tool_call_count/iteration_count） |
| POST | /api/v1/agent/runs/{run_id}/cancel | 取消 |
| POST | /api/v1/agent/runs/{run_id}/approve | 人工批准（WAITING_HUMAN 恢复） |
| POST | /api/v1/agent/runs/{run_id}/reject | 人工拒绝 |
| GET | /api/v1/agent/runs/{run_id}/events?after_sequence=N | 持久化事件列表（resume） |
| GET | /api/v1/agent/runs/{run_id}/stream?after_sequence=N | SSE 事件流（先回放再实时） |

### 工具 / MCP / 调度 / 指标

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/agent/tools | 注册的工具（含权限/超时/重试策略） |
| POST | /api/v1/agent/mcp/servers | 注册 MCP Server（工具自动进 ToolRegistry） |
| GET | /api/v1/agent/mcp/servers | MCP Server 列表 |
| DELETE | /api/v1/agent/mcp/servers/{name} | 注销 MCP Server |
| POST | /api/v1/agent/schedules | 定时任务（`delay_seconds` 或 `interval_seconds`） |
| GET | /api/v1/agent/schedules | 任务列表 |
| DELETE | /api/v1/agent/schedules/{job_id} | 取消任务 |
| GET | /api/v1/agent/metrics | 运行时指标 |

## 数据集 / 训练 / 知识库 / 插件 / 系统（2.1 保持）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/datasets/upload | 上传数据集 |
| GET/POST/DELETE | /api/v1/datasets | 列表 / 校验 / 删除 |
| GET | /api/v1/train/templates | 训练模板 |
| POST | /api/v1/train/start | 启动训练（full/LoRA） |
| GET | /api/v1/train/status/{task_id} / tasks | 训练状态 |
| GET | /api/v1/train/stream/{task_id} | 训练日志 SSE |
| POST | /api/v1/train/stop/{task_id} | 停止训练 |
| POST | /api/v1/knowledge/upload | 上传知识文档 |
| GET/DELETE | /api/v1/knowledge/documents | 文档列表 / 删除 |
| GET | /api/v1/knowledge/documents/{name}/chunks | 分块查看 |
| POST | /api/v1/knowledge/query / answer | 检索 / RAG 问答 |
| GET | /api/v1/plugins | 插件列表 |
| GET | /api/v1/system/status / logs | 系统状态 / 日志 |
| GET/PUT | /api/v1/system/download-source | Hugging Face 下载源（官方 / HF Mirror） |
| GET/PUT | /api/v1/system/model-storage | 模型默认存放地址（下载目录 = 扫描根目录，写入后持久化） |

## 插件（3.x，additive）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/plugins/discover?directory= | 文件系统 manifest 发现 |
| POST | /api/v1/plugins/load | 加载插件（manifest dict 或 manifest_path） |
| POST | /api/v1/plugins/{name}/start | 启动 |
| POST | /api/v1/plugins/{name}/stop | 停止 |
| POST | /api/v1/plugins/{name}/mount | 挂载（确认工具生效） |
| POST | /api/v1/plugins/{name}/unmount | 卸载（移除本插件工具） |
| DELETE | /api/v1/plugins/{name} | 卸载插件 |
| GET | /api/v1/plugins/capabilities?scope= | 能力索引（工具/技能/Agent 扩展） |

## OpenAI 兼容

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /v1/chat/completions | 聊天补全（含流式）；模型来自统一注册中心，未命中回落后端 |
| GET | /v1/models | 模型列表（来自统一注册中心，附 `model_id`/`capabilities`/`ready`） |

## 错误模型（spec 47）

## V1.1 → V2.0 新增接口组

| 组 | 路径 | 说明 |
|---|---|---|
| AgentDefinition | `/api/v1/agents`（GET/POST）、`/agents/{id}`（GET/PUT/DELETE）、`/agents/{id}/versions`、`/agents/{id}/runs`、`/agents/runs/{run_id}`、`/agents/runs/{run_id}/trace` | 规范 Agent 入口；`model_id` 绑定统一运行时 |
| 多运行时 | `/api/v1/runtimes`、`/api/v1/runtimes/{id}/health`；`POST /models/{id}/load` 支持 `runtime` | 适配器目录、健康、运行时覆盖 |
| 多模型/资源 | `/api/v1/runtime/instances`、`/runtime/resources`、`/runtime/queue`、`POST /runtime/evict`、`POST /runtime/unload-all` | 多实例、LRU、队列、资源 |
| 知识库 | `/api/v1/knowledge/bases`（GET/POST）、`/knowledge/bases/{id}`（GET/PATCH/DELETE）、`/knowledge/bases/{id}/documents`（GET/POST）、`/knowledge/bases/{id}/documents/{doc}`（DELETE）、`/knowledge/embedding`、`/knowledge/embed` | 知识库 CRUD、文档绑定、embedding provider |
| 工作流 | `/api/v1/workflows`（GET/POST）、`/workflows/validate`、`/workflows/{id}`（GET/PUT/DELETE）、`/workflows/{id}/runs`（GET/POST）、`/workflows/runs/{id}`、`/workflows/runs/{id}/events`、`/trace`、`POST /runs/{id}/approve`、`/cancel` | 编排、审批、Trace |
| 开发者 | `/v1/embeddings`、`/v1/agents`、`/v1/agents/{id}/runs`、`/v1/agents/runs/{id}`、`/trace`、`/v1/knowledge/search`、`/v1/workflows/{id}/runs`、`/v1/workflows/runs/{id}`、`/trace`、`/v1/platform/capabilities` | OpenAI 兼容扩展 |
| 包管理 | `/api/v1/packages`、`POST /packages/export`、`POST /packages/import`、`/packages/{id}`（GET/DELETE） | model/agent/tool/workflow 包 |
| 可观测 | `/api/v1/traces`、`/traces/{id}`、`/metrics/overview`、`/metrics/resources`、`/evaluations*`、`/security/secrets` | Trace、指标、评测、密钥后端 |
| 加固 | `/api/v1/system/hardening`、`POST /api/v1/system/recovery` | 恢复与加固视图（需运行时管理员） |
| 平台 | `/api/v1/dashboard`、`/api/v1/events` | 总览与统一事件流 |

完整说明见 `docs/V1_1_AGENT_RUNTIME.md` … `docs/V2_0_PLATFORM.md`。

```json
{"error": {"code": "RUN_NOT_FOUND", "message": "Run not found", "details": {}}}
```

错误码：AGENT_NOT_FOUND / RUN_NOT_FOUND / RUN_CANCELLED / RUN_TIMEOUT / TOOL_NOT_FOUND / TOOL_DENIED / TOOL_TIMEOUT / MODEL_NOT_FOUND / MODEL_UNAVAILABLE / CONTEXT_TOO_LARGE / POLICY_DENIED / HUMAN_APPROVAL_REQUIRED / AGENT_LOOP_LIMIT / AGENT_TOOL_CALL_LIMIT / RUNTIME_ERROR。

## 行为与错误契约（2026-09-12 更新）

完整行为变更见 [行为变更说明](BEHAVIOR_CHANGES_2026-09-12.md)。接口层需注意：

- **单账户占用**：推理与训练同一时刻只允许一个账户占用。其他账户的推理入口
  （`/chat`、`/chat/stream`、`/v1/chat/completions`、`/runtime/start`、`/runtime/chat`、
  `/knowledge/answer`）返回 `409 RUNTIME_BUSY`，训练入口返回 `409 TRAINING_BUSY`，
  响应消息中带占用者用户名；同一账户可重入。
- **加载失败即释放占用**：`POST /api/v1/runtime/start` 只有在模型真正加载成功后才保留
  推理占用；加载失败返回 `502 MODEL_LOAD_FAILED`、运行时不可用返回 `503 RUNTIME_UNAVAILABLE`，
  两种情况都会立即释放占用，不会让其他账户长期收到 `409 RUNTIME_BUSY`。
- **Agent Run**：执行期间持有推理占用；拿不到时该 Run 以 `RUNTIME_BUSY` 结束，
  `error` 字段为占用者提示，事件流中有对应的 `run.failed`。
- **任务中心**：`POST /api/v1/tasks/{id}/cancel` 现在会把取消传递到执行器
  （训练停止子进程、Agent Run 取消运行），任务行随后收敛为 `CANCELLED`；
  `QUEUED` 状态的任务同样可取消。`POST /api/v1/tasks/{id}/retry` 会对 Agent Run
  真正重新执行。
- **认证**：`POST /api/v1/auth/change-password` 成功后会立即使此前签发的 token 失效
  （需重新登录）。使用 Cookie 会话的写请求（含 `/v1/*`）必须携带 `X-CSRF-Token`，
  值取自登录返回的 `csrf_token`。
- **重启结算**：服务重启后，上一进程遗留的活跃记录会被结算为终态并写入稳定原因
  （下载 → PAUSED/CANCELLED，训练 → error，项目调用 → `PROCESS_RESTARTED`，
  Agent Run → `PROCESS_RESTARTED`）。
- **新增稳定错误码**：`KNOWLEDGE_QUERY_REJECTED`、`KNOWLEDGE_ANSWER_REJECTED`、
  `DATASET_NOT_FOUND`、`RUNTIME_BUSY`、`TRAINING_BUSY`、`PROCESS_RESTARTED`、
  `MODEL_LOAD_FAILED`、`RUNTIME_UNAVAILABLE`、`PLUGIN_EXECUTION_FAILED`。
- **数据集错误不再回显内部文本**：解析失败时 `error`/`detail` 只含
  `DATASET_PARSE_FAILED:<异常类型>`，`reason` 为固定提示，绝不包含服务器路径或原始异常正文。

## Run 状态机（spec 4）

`PENDING -> RUNNING -> (WAITING_TOOL | WAITING_HUMAN) -> COMPLETED | FAILED | CANCELLED | TIMEOUT`
