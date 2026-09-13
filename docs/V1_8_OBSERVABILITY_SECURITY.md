# V1.8 — Observability / Evaluation / Security

## Trace

Agent Run 与 Workflow Run 都投影为同一形状：

```json
{"trace_id", "status", "summary": {"span_count","model_calls","tool_calls","retrievals","node_count"},
 "spans": [{"span_id","name","type","status","started_at","ended_at","duration_ms","attributes","events"}],
 "events": [...]}
```

* `GET /api/v1/traces?kind=agent|workflow` — 统一索引；
* `GET /api/v1/traces/{trace_id}` — 自动识别 Agent / Workflow；
* Agent Trace 由持久化事件投影（`services/agent_trace.py`），Workflow Trace 由
  每运行事件投影（`services/workflow_trace.py`），两者都保留原始事件流。

## Metrics

`GET /api/v1/metrics/overview`：按模型聚合请求数、成功率、平均延迟、
input/output token 与 **tokens/sec**；`GET /api/v1/metrics/resources`：CPU/RAM/
GPU/VRAM/Disk 与实例、队列、运行时事件。

TTFT 目前**未采集**，因此接口显式返回 `ttft_ms: null` 与
`ttft_unavailable_reason`，不伪造数值。

## Evaluation

| 实体 | 表 |
|---|---|
| EvaluationDataset | `evaluation_datasets`（cases: input/expected/expect_json） |
| EvaluationRun | `evaluation_runs`（metrics + per-case results） |

API：`GET/POST /evaluations`、`GET/DELETE /evaluations/{id}`、
`POST /evaluations/{id}/runs`、`GET /evaluations/runs`、`GET /evaluations/runs/{id}`、
`POST /evaluations/compare`（A/B 对比 success_rate / accuracy / json_validity /
tool_success / latency / tokens）。

指标都是确定性的：`success_rate` 来自目标运行的终态，`accuracy` 来自期望子串匹配，
`json_validity` 来自解析结果，`tool_success` 来自 Trace 中工具 span 的状态，
不使用 LLM-as-judge。

## Security

| 项目 | 状态 |
|---|---|
| Path Traversal | 模型/数据集/知识文件路径统一经 `_contained_model_path` 或工作区根校验 |
| Command Injection | Shell 工具经 `PolicyEngine` 默认拒绝（需显式 `shell_access` + 人工审批） |
| SSRF | 远程 provider 走 `validate_provider_target`（网络策略） |
| Prompt Injection | 知识上下文以固定模板注入并在 RAG 提示中标注来源 |
| Secret Leakage | 事件负载脱敏（`[REDACTED]`）；Trace/metrics/错误响应不含密钥；`/security/secrets` 只报告后端与是否已配置 |
| Plugin Abuse | manifest 权限声明 + 安装/启动需管理员确认 + 审计 |
| File Permission | 生成的密钥/配置目录 `0700`/owner-only（Windows 走 ACL） |
| API Auth | JWT Bearer + HttpOnly Cookie + CSRF（写请求）+ 项目 API Key（`/api/v2`） |

Secret Manager：`core/secret_store.py` 优先使用操作系统钥匙串（`keyring`），
不可用时回落到既有的 Fernet 加密列 + 本机 owner-only 密钥文件，并通过
`GET /api/v1/security/secrets` 如实报告使用中的后端。

## 验收

| 验收项 | 证据 |
|---|---|
| Trace | `tests/test_observability_v18.py::test_trace_index_and_lookup_across_agent_and_workflow` |
| Metrics | `test_metrics_and_resource_overview` |
| Evaluation | `test_evaluation_dataset_run_and_compare` |
| Security Audit | 上表 + 既有 `test_security_hardening.py` / `test_downloader_security.py` |
| Secret Manager | `test_secret_backend_reports_state_without_values` |
| Tool Sandbox | `PolicyEngine` 默认拒绝网络/Shell/写文件 + Approval |
| API Auth | 既有 `test_auth_security.py` / `test_cookie_auth.py` |
| Audit Log | 既有 `services/audit_log.py` + 各写操作 `record_operation` |
