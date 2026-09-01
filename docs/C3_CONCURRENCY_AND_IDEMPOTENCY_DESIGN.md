# C3 并发状态机与幂等控制技术方案

> **注意：** 历史设计文档，基于 v0.1.2-dev 基线编写。不代表 v0.1.3-beta.1 发行状态。

**适用基线：** `v0.1.2-dev`，提交 `a529ecd` 之后的 B2 改造工作区。
**决策状态：** 已审查并确认，待后续 C3 实施与用户批准的验证阶段。
**范围：** Agent Run、持久化计划、取消/审批、事件/SSE 和模型指标的并发一致性。

## 1. 已确认的架构决策

本方案采用**数据库乐观并发控制（compare-and-set，CAS）**作为事实来源，而不是依赖 Python 进程内集合或全局锁。对于本地 SQLite 部署，单条受条件限制的 `UPDATE` 与唯一索引能够提供足够明确的 claim 和终态归属；内存集合仅保留为性能优化，不能作为授权执行或确定终态的依据。[1] [2]

> **核心不变量：** 每个 Run 只能有一个持久终态；每个计划 occurrence 最多创建一个关联 Run；每个终态事实最多写入一条对应的可重放事件；失败的指标或通知写入不能改变 Run 的主结果。

| 决策 | 采用方案 | 不采用方案 | 原因 |
|---|---|---|---|
| Run 归属 | `state_version` 条件更新与 executor lease。 | 仅检查 `_running` 内存集合。 | 支持重启、竞争取消和多回调安全失败。 |
| 计划触发 | 按 `(schedule_id, occurrence_key)` 唯一插入 claim。 | 先查 active run 再创建。 | “先查后写”在竞争回调下会重复创建 Run。 |
| 终态事件 | 按 `(run_id, event_key)` 幂等写入。 | 只依赖递增 sequence。 | sequence 不能单独防止重试写入重复终态。 |
| 队列策略 | `queue_one` 使用唯一待处理 claim。 | 内存 `pending_trigger` 布尔值。 | 重启和双回调后仍需保留一个可审阅的待处理 occurrence。 |
| 指标/通知 | 独立、幂等的 outbox 或 emission 记录。 | 在 Run 事务后静默 best-effort 调用。 | 主结果必须稳定，但失败也必须可诊断。 |

## 2. Run 状态机

### 2.1 持久字段

`AgentRun` 应新增 `state_version`、`executor_lease_id`、`lease_expires_at` 与 `terminal_event_key`。其中 `state_version` 初始为 `1`，每次合法状态改变加一；lease 仅证明某执行器暂时拥有执行权，不证明 Run 已完成。新增字段必须通过 B2 的具名、仅追加迁移引入。[3]

| 字段 | 目的 | 数据安全边界 |
|---|---|---|
| `state_version` | CAS 条件与事件版本。 | 仅整数，不含输入/输出。 |
| `executor_lease_id` | 区分当前执行器与迟到回调。 | 随机标识，不使用用户/密钥信息。 |
| `lease_expires_at` | 允许明确恢复过期、未完成 claim。 | UTC 时间。 |
| `terminal_event_key` | 终态事实幂等键。 | 派生自 run id 与终态版本。 |

### 2.2 合法迁移

| 当前状态 | 允许目标状态 | 条件 | 副作用 |
|---|---|---|---|
| `PENDING` | `RUNNING` | CAS 成功且取得未过期 claim。 | 写 `started_at`、lease、`run.started`。 |
| `PENDING` | `CANCELLED` | 用户拥有 Run，CAS 成功。 | 清理未开始执行权，写一次终态事件。 |
| `RUNNING` | `WAITING_HUMAN` | 当前 lease 与版本匹配。 | 写审批等待事件；保留 lease。 |
| `WAITING_HUMAN` | `RUNNING` | 审批结果和当前版本匹配，且未取消。 | 写审批决策事件。 |
| `RUNNING` / `WAITING_HUMAN` | `COMPLETED` / `FAILED` / `CANCELLED` | CAS 成功；终态不可逆。 | 清 lease、写 terminal event key、发出指标 emission。 |
| 任何终态 | 任意状态 | 不允许。 | 返回当前快照，不重新执行。 |

执行器在调用模型、工具或写入最终结果前后都必须使用预期版本进行 CAS。若 CAS 失败，说明取消、另一个执行器或恢复流程已经胜出；当前协程只清理本地资源并读取最新持久快照，**不得覆盖输出、错误或终态**。

```text
claim(PENDING, v=1) -> RUNNING, v=2, lease=A
cancel(RUNNING, v=2) -> CANCELLED, v=3
late executor A finalize(v=2) -> CAS 失败 -> 读取 CANCELLED(v=3) -> 退出
```

## 3. 计划 occurrence claim 与并发策略

### 3.1 ScheduleExecution 扩展

`ScheduleExecution` 应从“事后审计记录”提升为“occurrence claim + 审计记录”。新增 `occurrence_key`、`claim_token`、`claim_expires_at`、`state_version` 和 `attempt_count`；为 `(schedule_id, occurrence_key)` 建立唯一索引。`occurrence_key` 由计划 ID、计划 UTC 时间与触发类型派生，手动运行使用用户点击生成的随机 operation ID。

| 场景 | occurrence key | 数据库行为 | 用户可见结果 |
|---|---|---|---|
| 正常计划 | `schedule:{id}:{planned_utc}` | 唯一插入成功者拥有 claim。 | 一条 triggered/linked 记录。 |
| 重启恢复 | 同一个 `planned_utc`。 | 已存在则只读取，不重复创建。 | 显示已跳过、已 claim 或已完成。 |
| `skip` | 当前 occurrence。 | 活跃 Run 存在时写 `skipped_concurrency`。 | 明确说明未执行原因。 |
| `queue_one` | `queue:{id}`。 | 仅允许一个 active queued claim。 | 保留一条 pending 记录。 |
| `allow_parallel` | 当前 occurrence。 | 每个唯一 occurrence 可单独 claim。 | 仍不允许相同 occurrence 重复。 |

### 3.2 调度回调顺序

计划回调必须先在一个短事务内完成 claim 和 next-run 推进，再由成功 claim 的调用方创建 Run。Run 创建成功后，同一事务或紧接的 CAS 将 `ScheduleExecution.agent_run_id` 绑定；Run 创建失败时 occurrence 记录为 `failed_to_create`，错误经脱敏后可审阅。不得在创建 Run 后再尝试判断并发状态。

`once` 计划在 claim 成功后立即转换为不启用；周期计划仅推进到下一个逻辑 occurrence。恢复流程只处理用户此前明确启用的计划，并对已过期 occurrence 写 `skipped_misfire`，不补跑历史工作。[4]

## 4. 取消、审批与子 Run

取消是一个优先级高于审批和正常完成的持久状态迁移。根 Run 取消成功后，系统以有界批次扫描子 Run；每个子 Run 使用自己的 CAS 迁移至 `CANCELLED`。审批请求只在 `WAITING_HUMAN` 且预期版本仍匹配时生效，迟到批准不会让已取消 Run 回到 `RUNNING`。

为避免递归取消造成深度风险，C3 实现使用批次队列，并为每个取消操作赋予 `correlation_id`。事件和审计仅保存 Run ID、状态、版本、原因 code 和脱敏摘要，不保存审批输入、工具参数或模型正文。

## 5. 事件、SSE 与指标隔离

### 5.1 终态事件与 SSE

`AgentEventRecord` 新增非空 `event_key`，并以 `(run_id, event_key)` 建唯一索引。普通事件可由 `event_key=sequence:{n}` 表示；终态事件使用 `terminal:{state_version}`。事件必须先持久化再通知内存总线；SSE 断线恢复始终以持久 cursor 为准。[5]

每个订阅者使用有限容量队列。队列满时不无限缓存：标记该订阅者为 `resync_required`、停止继续入队，并在下一次连接时要求从最后已确认 cursor 回放。心跳只证明连接活跃，不推进已确认 cursor。

### 5.2 指标、审计和通知

Run 终态事务不直接依赖模型指标、预算计算、桌面通知或外部派送完成。它们应写入具备唯一 `emission_key=run_id:state_version` 的本地 emission/outbox 记录；派送失败增加有限 attempt 并保存脱敏错误 code。这样，指标失败不会改变 Run 结果，且“静默忽略”会被替换为可聚合诊断。

## 6. 实施顺序与不变量检查表

| 顺序 | 改造项 | 完成判断 | 前置依赖 |
|---:|---|---|---|
| C3-1 | 追加 AgentRun/ScheduleExecution/AgentEvent 的版本与唯一键字段。 | B2 迁移账本可记录升级。 | B2。 |
| C3-2 | 在 store/service 增加 CAS claim、transition 和 terminal writer。 | 所有终态路径调用同一服务。 | C3-1。 |
| C3-3 | 改造计划 callback 与 recovery，使 occurrence claim 先于 Run 创建。 | 同一 occurrence 无重复 Run。 | C3-2。 |
| C3-4 | 改造取消/审批/子 Run 的版本检查和批次传播。 | 迟到批准/完成不覆盖取消。 | C3-2。 |
| C3-5 | 加入 event key、有限 SSE 队列、指标 emission outbox。 | 背压、重放和失败诊断可观察。 | C3-2。 |

## 7. 当前非目标与验证门槛

本方案不在当前工作轮执行模型、自动启用计划、启动常驻服务、跨主机协调或分布式队列。它首先保证本地 SQLite/单应用进程下的持久状态可以安全失败并可恢复；若未来启用多进程或 24/7 执行，应重新评估数据库和 lease 的部署边界。

> **未验证声明：** 本文是已确认的实现方案，不是测试报告。C3 的迁移、CAS 竞态、计划重复触发、取消/审批竞争、SSE 慢消费者、指标 emission、插件相关 Run 和旧库升级均尚未运行验证。验证、构建、签名、发布与正式标签仍需用户明确许可。

## 参考资料

[1]: ../backend/app/runtime/runtime.py "AgentRuntime 现有 Run 生命周期"
[2]: ../backend/app/services/schedule_service.py "持久化计划和执行记录服务"
[3]: ../backend/app/models/records.py "AgentRun、AgentEventRecord 与 ScheduleExecution ORM"
[4]: ./B2_H7_ITERATION_DEVELOPMENT_PLAN.md "B2–H7 数据基线与计划生命周期目标"
[5]: ../backend/app/services/task_realtime.py "SSE outbox 与 cursor 重放"
