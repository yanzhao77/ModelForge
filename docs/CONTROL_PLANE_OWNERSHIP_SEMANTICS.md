# 控制面所有权与不可枚举语义

**代码单一事实来源：** `backend/app/core/resource_access.py`。本文件只说明 CP2 的静态访问语义，不代替路由查询、认证、授权或行为验证。

## 核心规则

对当前用户拥有的资源，路由必须将 `user_id == current_user.id`（或等价归属条件）直接并入查询。查询未返回资源时，只能返回对应的稳定 `*_UNAVAILABLE` 问题，不得先执行全局查询以区分“不存在”和“属于其他用户”。因此，调用者无法通过 404/403、提示文本、对象字段或计数推断其他用户资源是否存在。

管理员范围在资源查找之前通过稳定 `RUNTIME_ADMIN_REQUIRED` 拒绝。管理员通过后，仍必须遵守资源类别的最小化可用性响应；管理员身份不是返回原始连接、插件状态、目标详情或凭据的理由。

| 资源类别 | 作用域 | 不可用代码 | 冲突代码 | 允许最小化响应 |
|---|---|---|---|---|
| Agent Run | 当前用户 | `AGENT_RUN_UNAVAILABLE` | 无 | 稳定 code、关联标识和无正文安全消息。 |
| Task | 当前用户 | `TASK_UNAVAILABLE` | `TASK_VERSION_CONFLICT` | 稳定 code、关联标识；冲突不得返回当前状态或他人信息。 |
| Training Task | 当前用户 | `TRAINING_TASK_UNAVAILABLE` | 无 | 稳定 code、关联标识和无正文安全消息。 |
| Memory | 当前用户 | `MEMORY_UNAVAILABLE` | 无 | 稳定 code、关联标识和无正文安全消息。 |
| Workspace 资源 | 当前用户 | `WORKSPACE_RESOURCE_UNAVAILABLE` | 无 | 稳定 code、关联标识和无正文安全消息。 |
| Runtime Plugin | 运行时管理员 | `PLUGIN_UNAVAILABLE` | 无 | 在管理员授权后仍只返回稳定资源不可用信息。 |
| MCP Server | 运行时管理员 | `MCP_SERVER_UNAVAILABLE` | 无 | 在管理员授权后仍只返回稳定资源不可用信息。 |

## 冲突与刷新

版本冲突仅对调用者当前可见的 Task 使用 `TASK_VERSION_CONFLICT`。响应可提示客户端刷新当前用户的安全快照并重新确认，但不得返回现有版本、运行状态、另一个用户、原始异常、输入、模型输出、路径、endpoint、token 或 API key。

## 迁移边界

CP2 新增目录和问题构造器，不自动重写全部历史路由。后续每个路由迁移前必须确认：查询本身已按当前用户范围收敛；对应错误代码已登记；错误响应含关联标识；兼容字段不泄露对象正文；管理员检查不暴露配置的管理员列表。任何跨用户行为验证均需要固定完整候选 SHA、隔离用户、明确授权和最小化脱敏证据。
