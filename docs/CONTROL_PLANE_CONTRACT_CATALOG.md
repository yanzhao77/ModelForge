# 控制面契约目录

**代码单一事实来源：** `backend/app/core/control_plane_contracts.py`。本目录仅交叉引用已经迁移到 EI1–EI15 控制面契约的动作；它不进行运行性授权，也不会调用任何 API、运行时、provider、插件或数据库。

每个条目固定关联一个风险目录动作、确认错误码、无枚举泄露的不可用错误码（如适用）、审计持久化未知回执、所有权语义和只读预览资格。风险等级与允许审计字段继续由 `action_risk.py` 管理；HTTP 状态、可重试性和禁止暴露字段继续由 `control_plane_errors.py` 管理。

| 动作组 | 所有权 | 确认 | 不可用回执 | 审计未知回执 | 只读预览 |
|---|---|---|---|---|---|
| Agent Run 创建/取消/审批/拒绝 | 当前用户 | 四个专属 `AGENT_RUN_*_CONFIRMATION_REQUIRED` 代码 | 不在 CP1 中新增行为映射 | `AGENT_RUN_AUDIT_DURABILITY_UNKNOWN` | 仅创建、取消 |
| 任务重试/批量重试/取消 | 当前用户 | `TASK_RETRY_CONFIRMATION_REQUIRED` 或 `TASK_CANCEL_CONFIRMATION_REQUIRED` | `TASK_UNAVAILABLE` | 对应 `TASK_*_AUDIT_DURABILITY_UNKNOWN` | 是 |
| 训练开始/停止/模型注册 | 当前用户 | `TRAINING_*_CONFIRMATION_REQUIRED` | 不在 CP1 中新增行为映射 | 对应 `TRAINING_*_AUDIT_DURABILITY_UNKNOWN` | 是 |
| Memory、产物、集合、配置档删除/关联 | 当前用户 | `MEMORY_*`、`ARTIFACT_*`、`COLLECTION_*` 或 `PLUGIN_PROFILE_*` 确认码 | `MEMORY_UNAVAILABLE` 或 `WORKSPACE_RESOURCE_UNAVAILABLE` | `MEMORY_AUDIT_DURABILITY_UNKNOWN` 或 `WORKSPACE_AUDIT_DURABILITY_UNKNOWN` | 否 |
| 插件生命周期与 MCP 连接/移除 | 管理员 | `PLUGIN_CONFIRM_REQUIRED`、`MCP_*_CONFIRMATION_REQUIRED` | 不在 CP1 中新增行为映射 | `PLUGIN_AUDIT_DURABILITY_UNKNOWN` 或 `MCP_AUDIT_DURABILITY_UNKNOWN` | 否 |

> **渐进迁移规则：** 未列入本目录的低风险配置保存、历史端点和尚未核对的运行性动作不能被推断为安全、已验证或不需要确认。新增条目前必须同时核对动作风险登记、错误目录、审计字段白名单和目标端点的兼容字段。

## 静态审阅要求

目录条目不得包含用户输入、对象名称、稳定 ID、路径、endpoint、URL、token、API key、模型输出、工具参数、任意 metadata 或异常正文。预览资格只表示存在可设计的只读摘要契约，绝不表示预览令牌可执行动作。所有行为验证仍需要固定完整 40 位候选 SHA、独立授权和最小化脱敏证据。
