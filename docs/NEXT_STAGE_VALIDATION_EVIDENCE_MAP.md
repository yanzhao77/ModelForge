# 下一阶段稳定性加固验证与证据映射

**用途：** 本文将稳定性加固工作包映射到未来获得授权后的验证证据。它不执行测试、启动服务、访问凭据、迁移数据库、创建 Run、运行计划、调用模型、构建、签名、打标签或发布。

## 1. 候选身份

| 字段 | 当前值 | 规则 |
|---|---|---|
| 基线提交 | `c92ae0a77ad7e7b9fcabc46f6556c14b0b3047cd` | 仅为开发基线，不代表候选通过。 |
| 加固候选 SHA | `TBD` | 验证前必须替换为固定 40 位 SHA。 |
| 应用版本 | `0.1.2-dev` | 未经版本提升与批准不得变更。 |
| 当前决定 | **No-Go** | 任何未执行的 gate 均阻断 tag、签名和 Release。 |

## 2. 工作包验证映射

| 工作包 | 未来验证目标 | 所需脱敏证据 | No-Go 条件 |
|---|---|---|---|
| SH1：事务与审计 | 草稿创建/更新、默认模型设置/清除在同一事务中完成；审计写入失败时领域变更回滚。 | 固定 SHA、数据库前后状态摘要、关联标识、审计计数与失败路径记录。 | 变更提交但审计缺失；错误响应仍显示成功；跨用户审计。 |
| SH2：只读审计查询 | 管理员分页、筛选、时间游标和桌面摘要可读；metadata/正文绝不返回。 | API 响应字段清单、分页边界、PySide6 截图、敏感字段缺失断言。 | 返回 `metadata_json`、token、正文、完整请求或无界导出。 |
| SH3：遗留对话隔离 | 相同 Agent 名称的不同用户不共享内存消息；匿名兼容 scope 不与真实用户合并。 | 两用户会话状态摘要、运行时内存键诊断、策略 guard 记录。 | 跨用户消息可见；用户范围未传递；策略 guard 回退。 |
| SH4：策略与事件诊断 | ToolExecutionContext 权限与声明一致；EventBus 写失败/队列溢出只读可见。 | tool context 摘要、lifecycle diagnostics 响应、失败计数变化记录。 | allow/deny 行为因摘要改动而改变；诊断导致事件重放、删除或恢复。 |
| SH5：文档与兼容性 | 证据、版本、候选 SHA 和 Go/No-Go 材料一致。 | 本文、证据 manifest、兼容矩阵、发行决定记录。 | 使用分支名替代 SHA；把未验证实现标为 passed。 |

## 3. 兼容性矩阵

| 表面 | 保持行为 | 加性/内部变化 | 未来复核 |
|---|---|---|---|
| `ScheduleService.create_draft/update_draft` | 默认仍自行提交，直接服务调用者无需变更。 | 新增可选 `commit=False`，供 API 将审计与变更置于同一事务。 | 直接调用、API 成功/失败、rollback。 |
| `ModelReadinessService.set_default/clear_default` | 默认仍自行提交并返回 readiness snapshot。 | 新增可选 `commit=False`。 | 默认模型存在/不存在、审计失败 rollback。 |
| `/workspaces/operation-audits` | 新增管理员只读端点。 | 固定字段白名单、上限 200、时间游标。 | 角色边界、分页稳定性、metadata 不泄露。 |
| `AgentEngine` | 无用户参数的内部遗留调用继续使用匿名 scope。 | 真实 API 调用以 `(user_id, agent_name)` 存储对话状态。 | 多用户同名 Agent、删除缓存、匿名兼容。 |
| `ToolExecutionContext` | 既有 policy 决策与执行顺序不变。 | 新增实际工具声明权限摘要。 | 工具声明、deny/approval 行为与事件顺序。 |

## 4. 证据文件约束

每份未来证据必须声明 `commit_sha`、`application_version`、UTC 时间、执行人、环境、gate ID、结果及脱敏引用。允许保留计数、状态、错误码、关联标识、截图和 checksum；禁止保留 API Key、Bearer token、密码、私钥、证书、完整 URL、请求/响应正文、知识内容、模型输入输出和原始数据库文件。

> **操作限制：** 本映射不是验证授权。只有用户单独授权并锁定候选 SHA 后，才能执行 H7/I6 所列的测试、迁移、桌面、签名和发行验证。[1] [2]

## References

[1]: ./NEXT_STAGE_STABILITY_HARDENING_PLAN.md "下一阶段稳定性加固计划"
[2]: ./H7_VALIDATION_EVIDENCE_TEMPLATE.md "H7 验证与发行证据模板"
[3]: ./V0_1_3_RELEASE_GO_NO_GO.md "v0.1.3 候选发行 Go/No-Go 模板"
