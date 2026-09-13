# V1.6 — Developer Platform

目标：第三方可以基于 ModelForge 开发（HTTP API、OpenAI 兼容 API、Python SDK、插件）。

## HTTP / OpenAI 兼容 API

`api/developer_api.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/embeddings` | OpenAI 形状的向量接口（`object=list`、`data[].embedding`、`usage`、附 `embedding` 元信息） |
| GET | `/v1/agents` | Agent 列表（`object=list`） |
| POST | `/v1/agents/{id}/runs` | 创建 Agent Run（异步执行） |
| GET | `/v1/agents/runs/{id}` `/trace` | 运行与 Trace |
| POST | `/v1/knowledge/search` | 知识检索（可选 `knowledge_id`、`retrieval_mode`） |
| POST | `/v1/workflows/{id}/runs`、GET `/v1/workflows/runs/{id}` `/trace` | 工作流执行 |
| GET | `/v1/platform/capabilities` | 运行时目录、节点类型、权限目录（机器可读） |

所有端点都是既有 Service 的薄适配层，第三方行为与第一方 UI 完全一致。

## Python SDK

`sdk/python/modelforge/`（`pip install ./sdk/python`）：

```python
client = ModelForge("http://127.0.0.1:8000"); client.login("alice", "secret123")
client.models.list(capability="CHAT"); client.models.load(3)
client.chat.completions.create(model="qwen", messages=[...])
client.embeddings.create(["hello"])
client.agents.run("writer", "...", wait=True); client.agents.trace(run_id)
client.knowledge.search("...", retrieval_mode="hybrid")
client.workflows.run(wf_id, {"question": "hi"}, wait=True)
```

错误统一抛 `ModelForgeError(status, code, message, correlation_id)`，
调用方按稳定错误码分支而不是解析文案。

## 插件与权限

`runtime/plugins/manifest.py` 已支持 manifest（name/version/type/entry/
dependencies/permissions）；`api/plugin.py` 暴露安装、启动、挂载、能力索引，
安装前后都展示权限，工具执行仍走 `PolicyEngine`。示例插件：
`examples/plugins/word_count/`（READ_ONLY 工具）。

## 示例

* `examples/plugins/word_count/plugin.json` + `plugin.py`
* `examples/agents/support_agent.json`
* `examples/workflows/research_pipeline.json`

## 验收

| 验收项 | 证据 |
|---|---|
| Python SDK | `tests/test_developer_platform.py::test_sdk_round_trips_the_platform_api`（httpx MockTransport） |
| API | 上表端点（`test_v1_embeddings_matches_openai_shape` 等） |
| API Auth | 复用 `get_current_user`（JWT / 会话 Cookie / CSRF 规则不变） |
| Plugin System | 既有插件子系统 + 示例插件 |
| Permission | `PermissionLevel.catalog()` 映射到 READ_ONLY / FILESYSTEM_WRITE / PROCESS_EXECUTE / DANGEROUS |
| Developer Docs | 本文件 + `sdk/python/README.md` |
| Example Plugin / Agent / Workflow | `examples/` |
