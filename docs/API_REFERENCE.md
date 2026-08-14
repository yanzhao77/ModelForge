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
| GET/POST/DELETE | /api/v1/models | 模型列表 / 登记 / 删除 |
| POST | /api/v1/models/scan | 扫描目录 |
| GET | /api/v1/models/search | HF 搜索 |
| POST | /api/v1/models/download | 下载 GGUF |
| GET | /api/v1/models/download/{task_id} | 下载进度 |
| POST | /api/v1/runtime/start / chat / stop | 推理运行时 |
| GET | /api/v1/runtime/status | 运行时状态 |

## 聊天（2.1 保持兼容）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/chat | JSON 聊天 |
| POST | /api/v1/chat/stream | SSE 流式 |

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

## OpenAI 兼容

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /v1/chat/completions | 聊天补全（含流式） |
| GET | /v1/models | 模型列表 |

## 错误模型（spec 47）

```json
{"error": {"code": "RUN_NOT_FOUND", "message": "Run not found", "details": {}}}
```

错误码：AGENT_NOT_FOUND / RUN_NOT_FOUND / RUN_CANCELLED / RUN_TIMEOUT / TOOL_NOT_FOUND / TOOL_DENIED / TOOL_TIMEOUT / MODEL_NOT_FOUND / MODEL_UNAVAILABLE / CONTEXT_TOO_LARGE / POLICY_DENIED / HUMAN_APPROVAL_REQUIRED / AGENT_LOOP_LIMIT / AGENT_TOOL_CALL_LIMIT / RUNTIME_ERROR。

## Run 状态机（spec 4）

`PENDING -> RUNNING -> (WAITING_TOOL | WAITING_HUMAN) -> COMPLETED | FAILED | CANCELLED | TIMEOUT`