# 全量测试与 bug 收敛（2026-09-13 第四轮）

## 1. 全量测试结果（修复前）

以 `bae39a5` 为基线，按 CI 口径执行全量测试（GUI + 后端）：

| 验证项 | 命令 | 结果 |
|---|---|---|
| 空白/静态检查 | `git diff --check`、`ruff check backend client tests scripts reports` | 通过 |
| 后端导入 + 启动生命周期 | `python -c "import main"`、`pytest tests/test_app_boot.py` | 通过 |
| **全量套件（GUI + 后端）** | `pytest tests/ -q --cov=backend/app --cov-fail-under=75` | **1079 passed / 4 skipped**，覆盖率 **83.29%** |
| GUI 离屏渲染审计 | `python reports/render_pages_offscreen.py` | `ALL_CAPTURES_OK`、退出码 0 |
| 4 条跳过项 | `pytest -rs` | 环境门槛：symlink 特权、`RUN_NETWORK_TESTS`、CPU smoke 模型、无 torch |

套件本身全绿，因此本轮继续用**真实后端流程**和**跨模块组合**挖掘缺陷，
发现 5 个产品缺陷与 2 个测试基础设施缺陷。

## 2. Bug 任务清单

| ID | 等级 | 问题 | 状态 |
|---|---|---|---|
| B-01 | P1 | `POST /agent/schedules/{id}/run-now` 以位置参数调用 keyword-only 的 `AgentRuntime.create_run()` → `TypeError` → 裸 HTTP 500；**手动运行计划必然失败** | 已修复 |
| B-02 | P1 | `DELETE /agent/schedules/{id}` 先删父行后删子行，撞 `schedule_executions` 外键 → `SCHEDULE_DELETE_PERSIST_FAILED`；**运行过的计划无法删除** | 已修复 |
| B-03 | P2 | `/agent/{name}/chat` 图构建失败时把 `Agent graph build failed: {exception}` 作为 200 响应回显，泄漏内部细节且无稳定错误码 | 已修复 |
| B-04 | P2 | `agent_chat`（含 `schedule_executions` / `schedule_preview`）用裸字符串 `detail` 返回 404，不符合项目统一 `{code, message, correlation_id}` 契约 | 已修复 |
| B-05 | P3 | 无 LLM provider 时 `/agent/{name}/chat` 返回 200 + 英文占位文案，客户端无法与真实回答区分 | 已修复（新增 `provider_required` 结构化标记） |
| B-06 | P2 | 测试进程的数据库路径由**首个导入 `core.database` 的模块**决定，后续模块的隔离设置失效 → 注册类用例撞上历史数据返回 400（干净 HEAD 亦可复现） | 已修复 |
| B-07 | P3 | `test_schedule_interval_fires_repeatedly` 固定睡 0.22s 断言 ≥3 次触发，负载下只触发 2 次而失败 | 已修复 |

## 3. 修复明细与证据

### B-01 手动运行计划（run-now）

- 现象：真实后端调用 `run_schedule_now` 返回 `HTTP_500`。
- 定位：服务端栈指向 `backend/app/api/agent.py` 的
  `rt.create_run(agent_id, input, user_id, session_id, metadata, execute=True)`，
  而 `AgentRuntime.create_run` 的签名是 `def create_run(self, *, agent_id, input_text, …)`
  → `TypeError: takes 1 positional argument but 6 positional arguments were given`。
- 修复：改为关键字调用，并把失败映射为稳定错误码：`AgentNotFoundError` → 404 `AGENT_NOT_FOUND`，
  其它异常 → 502 `SCHEDULE_RUN_FAILED`（同时 `fail_claim` 标记本次执行失败）。
- 证据：修复后 `run_schedule_now` 返回 `{"schedule_id":…, "run_id":…, "status":…}`；
  回归测试 `tests/test_schedule_run_and_delete.py`（关键字签名 fake runtime + 两种失败映射）。

### B-02 删除已运行过的计划

- 现象：`delete_schedule` 返回 `SCHEDULE_DELETE_PERSIST_FAILED`，服务端异常为
  `sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed`
  （`DELETE FROM scheduled_jobs`）。
- 根因：`ScheduleService.delete_desired` 直接删除 `scheduled_jobs` 行，而
  `schedule_executions.schedule_id` 外键仍指向它。
- 修复：删除前先清理该计划的执行记录（`query(ScheduleExecution).filter(schedule_id=…).delete()`），
  再删除计划本身。
- 证据：修复后删除返回 `{"ok": true, "runtime_sync": "not_required"}`，
  且 `list_schedules` 为空；回归测试用 **开启 `PRAGMA foreign_keys=ON` 的内存库**复现原约束并断言删除成功。

### B-03 / B-04 / B-05 Agent 对话契约

- 修复：`AgentEngine.chat` 图构建失败时返回 `{"error_code": "AGENT_GRAPH_FAILED"}`（不再拼接异常文本）；
  无 provider 的占位响应新增 `provider_required: True`；
  `/agent/{name}/chat` 路由把上述标记映射为 `problem(502, "AGENT_GRAPH_FAILED")`，
  缺失 agent 统一返回 `problem(404, "AGENT_NOT_FOUND", …, correlation_id)`；
  `schedule_executions` / `schedule_preview` 的裸 404 也改为 `SCHEDULE_NOT_FOUND` 契约。
- 证据：`tests/test_agent_chat_error_contract.py` 断言失败响应不含异常文本、包含 `error_code`，
  并通过桩引擎验证 502/404 的 problem 结构。

### B-06 测试数据库隔离

- 现象：在同一进程中按 `test_schedule_*` → `test_api_integration.py` 顺序运行时，
  `TestAuthFlow::test_register_login_me` 注册 `alice` 返回 400。
- 定位：应用在首次导入 `core.database` 时绑定引擎；`tests/test_api_integration.py` 在**自身导入时**
  才设置 `DATABASE_PATH`，若此前已有模块导入过应用，该设置失效，注册请求落到
  `./data/modelforge.db` 并撞上历史 `alice`。干净 HEAD 上同样复现（与功能修复无关）。
- 修复：`tests/conftest.py` 在**任何测试模块导入之前**用 `setdefault` 固定会话级临时库
  （`DATABASE_PATH` 指向 `tempfile.mkdtemp()` 下的 `test.db`，`JWT_SECRET` 亦给出长度合规的默认值），
  仍尊重外部显式设置的环境变量。
- 证据：`test_schedule_run_and_delete.py + test_agent_chat_error_contract.py + test_schedule_service.py +
  test_scheduler_phase9.py + test_api_integration.py` 组合由 **1 failed** 变为 **146 passed**。

### B-07 调度重复触发用例

- 修复：改为带截止时间（3s）的轮询等待 `len(fired) >= 3`，避免在繁忙 runner 上因调度抖动失败。

## 4. 修复后验证

| 验证项 | 结果 |
|---|---|
| `git diff --check` / `ruff check backend client tests scripts reports` | 通过 |
| 组合用例（调度服务 + 调度器 + API 集成 + 两个新回归） | 146 passed |
| **全量套件（GUI + 后端 + 覆盖率门槛）** | **1088 passed / 4 skipped**，覆盖率 **83.37%** |
| 真实后端 run-now / 执行记录 / 删除计划 | 全部 OK（`run_id` 返回、删除后列表为空） |
| GUI 离屏渲染审计 | `ALL_CAPTURES_OK`、`ENDPOINTS_TOUCHED 26`、退出码 0（54s） |
| 路由统计一致性 | 139 paths / 164 operations，README 一致 |

## 5. 残余风险与后续建议

- **无 provider 的占位回答**仍为英文文本（已有 `provider_required` 标记区分）；
  如有客户端要展示该状态，建议改由客户端按标记渲染本地化提示。
- **`runtime_*` 仍为管理员专属**：普通账号返回 `RUNTIME_ADMIN_REQUIRED`（设计如此）。
- **长链路定时任务**：`run-now` 现在返回稳定错误码，但底层推理/模型加载失败仍依赖
  `SCHEDULE_RUN_FAILED` 单一码；若需要区分“模型不可用/配置缺失”，可复用
  `services/inference_errors.py` 的分类结果细化。
