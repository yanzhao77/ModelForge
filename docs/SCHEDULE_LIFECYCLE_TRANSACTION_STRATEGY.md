# 计划生命周期事务与运行时协调策略

**状态：** 已实现静态结构；未执行验证。
**范围：** 已确认的计划启用、暂停和删除控制面动作。本文不授权调用这些端点、创建 Agent Run、恢复计划或执行迁移。

## 1. 问题与原则

计划生命周期同时涉及 SQLite 持久状态、脱敏操作审计和内存运行时调度器。SQLite 可以在一个事务内提交计划状态与审计记录，但无法与进程内 `schedule_once()` 或 `cancel_schedule()` 构成跨资源原子事务。因此实现采用**持久期望状态优先、提交后显式协调、可安全重试**的顺序，而不是把运行时副作用放在数据库提交之前。

> **安全不变量：** 只有已有 `confirm=true` 的用户请求才能进入这些端点。任何后提交协调失败都不会自行创建 Agent Run、恢复计划或改变用户的确认边界。

## 2. 启用、暂停与删除顺序

| 操作 | 事务内步骤 | 提交后步骤 | 协调失败时的安全状态 |
|---|---|---|---|
| 启用 | 将 `enabled=true`、下一触发时间与 `schedule.enable` 脱敏审计一次提交。 | 仅在提交成功后挂载运行时一次性回调。 | 返回 `runtime_sync=pending`；持久期望状态存在，但不会因失败路径创建 Run。 |
| 暂停 | 将 `enabled=false`、清空 runtime job ID 与 `schedule.pause` 审计一次提交。 | 尝试取消之前记录的运行时 job。 | 回调再次读取到禁用计划后会成为 no-op，不能创建 Run。 |
| 删除 | 删除计划记录与 `schedule.delete` 审计一次提交。 | 尝试取消之前记录的运行时 job。 | 回调找不到计划后会成为 no-op，不能创建 Run。 |

所有响应在保持原有字段的基础上增加 `runtime_sync`：`armed`、`cancelled`、`not_required` 或 `pending`。`pending` 是一致性状态提示，不是成功执行或恢复的宣称。

## 3. 手动立即运行的边界

“立即运行”具有不可逆的 Agent Run 创建副作用，不适合与普通计划状态 mutation 复用同一补偿策略。当前路径先写入带唯一 occurrence key 的持久 claim，再在已确认请求中尝试创建 Run，并将成功 Run ID 绑定回 claim。该路径保留为独立执行命令，未来必须在固定 SHA 上验证：重复 Idempotency-Key、Run 创建失败、claim 绑定失败、审计失败、取消竞争和回调重入。

在上述验证获得用户单独授权之前，本阶段不调整 run-now 的执行语义，不触发任何实际调用，也不将其标为验证通过。

## 4. 后续验证与演进

后续获得授权后，应验证提交失败时无 runtime 副作用、运行时协调失败时的 `pending` 语义、重启恢复、重复回调 occurrence claim、暂停/删除后的陈旧回调 no-op，以及审计条目的关联标识与脱敏。若需要跨进程可靠投递或自动反复协调，应单独设计持久化 schedule reconcile outbox，并提供迁移、退避、死信和 operator approval；该能力不在当前实现范围内。

## References

[1]: ./NEXT_STAGE_STABILITY_HARDENING_PLAN.md "下一阶段稳定性加固计划"
[2]: ./NEXT_STAGE_VALIDATION_EVIDENCE_MAP.md "下一阶段稳定性加固验证与证据映射"
