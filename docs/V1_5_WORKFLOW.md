# V1.5 — Workflow / Multi-Agent

目标：从单 Agent 升级为任务编排平台（节点、边、变量、多 Agent、人工审批）。

## 数据模型

| 表 | 说明 |
|---|---|
| `workflows` | 定义（`definition_json`：nodes/edges/variables/entry）、版本号、状态 |
| `workflow_runs` | 单次执行：status / input / output / state（每节点结果 + 变量）/ current_node |
| `workflow_run_events` | 每运行的事件流（`sequence` 严格递增） |

## 引擎

`services/workflow_engine.py`

| 能力 | 实现 |
|---|---|
| 节点类型 | `input` / `output` / `llm` / `agent` / `tool` / `condition` / `loop` / `parallel` / `approval` |
| 顺序 / 条件 | `next`、`true_next`/`false_next` + AST 白名单表达式（禁止 `__import__`、属性逃逸、任意调用） |
| 并行 | `parallel.branches` 使用 `asyncio.gather` 并发执行各分支 |
| 循环 | `loop.body` + `while` + `max_iterations` |
| 重试 / 超时 | 节点 `config.retry{attempts,backoff_seconds}` 与 `config.timeout_seconds` |
| 人工审批 | `approval` 节点 → `workflow.approval.required` → run 置 `WAITING_HUMAN`，`approve` 从下一节点续跑 |
| 多 Agent | `agent` 节点通过 Agent Runtime 执行真实 Agent Run（不同 Agent 可用不同模型/工具/Prompt） |
| 工具 | `tool` 节点经 `ToolRegistry` + `PolicyEngine`（默认拒绝网络/Shell/写文件） |
| 模板 | `{{input.x}}`、`{{nodes.<id>.output}}`、`{{variables.y}}` |

## API 与 UI

`api/workflows.py`：`GET/POST /workflows`、`POST /workflows/validate`、
`GET/PUT/DELETE /workflows/{id}`、`GET/POST /workflows/{id}/runs`、
`GET /workflows/runs/{id}`、`/events`、`/trace`、`POST /runs/{id}/approve|cancel`。

桌面端 `pages/workflow_page.py`（导航「工作流」）：定义查看/新建/删除、JSON
输入运行、运行列表与状态轮询、Trace 查看、审批与取消。

## 验收

| 验收项 | 证据 |
|---|---|
| Workflow Engine | `tests/test_workflow_engine.py`（8 用例） |
| Node / Edge | `validate_definition` + `test_definition_validation_reports_problems` |
| Sequential / Parallel / Condition / Loop | `test_sequential_condition_and_output`、`test_parallel_branches_and_loop` |
| Retry / Timeout | `test_retry_until_success`、`test_node_timeout_is_reported` |
| Human Approval | `tests/test_workflow_api.py::test_human_approval_pauses_and_resumes` |
| Multi-Agent | `agent` 节点 + `tests/test_platform_e2e.py::test_chain_workflow_and_external_api` |
| Trace | `GET /workflows/runs/{id}/trace`（shape 与 Agent Trace 一致） |
| API / UI | 上表端点 + 桌面页面 + `tests/test_desktop_model_runtime_pages.py::test_workflow_page_lists_definitions_and_runs` |
