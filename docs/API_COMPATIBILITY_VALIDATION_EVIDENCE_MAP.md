# API 兼容性与远程模型配置：验证证据映射

**适用工作包：** AC1–AC5。
**候选提交 SHA：** `TBD`。验证开始前必须替换为单一、完整的 40 位 Git SHA。
**当前决定：** **No-Go**。本文只定义未来获得明确授权后应收集的脱敏证据，不代表已执行验证、已验证远程 provider、已创建 Agent Run、已构建签名，或已获准发行。

## 1. 统一证据与隔离规则

未来验证记录必须包含固定候选 SHA、应用版本、UTC 时间、执行人、平台/环境摘要、工作包、结果、脱敏日志或截图的位置及 SHA-256。不得保存 API Key、Bearer token、cookie、密码、私钥、证书、明文/密文密钥、密钥前缀/长度/哈希、模型输入输出、工具参数、知识正文、训练数据、完整异常、原始 SSE payload 或用户身份信息。

验证应当在独立、明确授权的会话中执行。任何验证失败、意外的 provider 网络访问、创建 Run、恢复计划、事件正文泄露、未经确认的写操作或版本/SHA 不一致，均应停止后续验证并保持 No-Go。

## 2. AC1–AC4 验证矩阵

| 工作包 | 将来验证目标 | 最小脱敏证据 | No-Go 条件 |
|---|---|---|---|
| AC1：Provider 配置 | 规范化 `base_url`；默认 `responses`；显式 `chat_completions`；拒绝嵌入凭据、query、fragment 和非本地 HTTP；公开摘要不包含密钥材料。 | 请求/响应字段白名单、配置摘要、稳定错误码、关联标识与无密钥断言。 | 响应、审计、日志、事件或桌面显示 API Key/密钥派生信息；URL endpoint 重复或协议回退非显式。 |
| AC1：验证确认 | `verify` 缺少 `confirm=true` 时不发出外部请求；桌面取消确认不发请求，确认后才调用。 | 请求计数、确认分支截图、`REMOTE_PROVIDER_VERIFY_CONFIRMATION_REQUIRED` 响应。 | 取消确认仍调用 provider，或错误响应包含底层异常/凭据。 |
| AC2：Problem 契约 | 本地模型、知识元数据和训练元数据不存在/不可用时保留兼容字段并返回 `{code,message,correlation_id}`。 | 每类稳定 code、HTTP 状态和响应字段白名单。 | `detail=str(exception)`、正文、路径敏感信息或缺少关联标识。 |
| AC3：任务 SSE | 同一用户的 query/header cursor 取最大有效值；无效 cursor 受控失败；达到连接批次上限后仅发 `resync_required` 控制事件。 | 用户作用域、事件 ID 序列、响应头、resync 控制帧和快照刷新记录。 | 跨用户事件、cursor 倒退、控制帧含事件正文，或重连创建任务/Run。 |
| AC3：Run SSE | `Last-Event-ID` 与 `after_sequence` 受 Run/用户作用域约束；事件帧带 sequence ID；Run 不存在错误脱敏。 | Run ID/用户 ID 的脱敏替代值、头字段、稳定错误码与序列断言。 | 跨 Run 重放、异常正文泄露，或重连恢复/创建 Agent Run。 |
| AC4：桌面配置 | 中英日下 provider endpoint、协议、凭据状态与错误关联提示可读一致；API Key 输入仅 write-only。 | 三种语言的脱敏截图、确认对话框、稳定错误码/关联标识截图。 | 显示密钥/派生信息、混合静态语言、取消确认触发验证或动态错误回显原文。 |

## 3. 候选身份与结果清单

| 字段 | 当前值 | 填写限制 |
|---|---|---|
| 候选 SHA | `TBD` | 仅完整 40 位 SHA，不得填分支名、短 SHA 或移动 tag。 |
| 应用版本 | `0.1.2-dev` | 当前为开发版本；不得据此创建正式 tag 或 Release。 |
| 验证授权 | `TBD` | 必须记录明确授权时间与范围。 |
| Provider 测试环境 | `TBD` | 只描述 provider 类型/协议和隔离环境；不得记录地址中的敏感部分或密钥。 |
| 证据目录 | `TBD` | 仅允许脱敏文件与校验和。 |
| 最终状态 | `not_run` | 只有矩阵全部完成且发行门槛获批后才可变更。 |

## 4. 发行隔离

AC1–AC5 完成代码或文档不构成发行审批。正式 tag、签名、构建、资产上传和 GitHub Release 仍取决于固定候选 SHA、完整验证证据、跨平台安装/签名证据、受保护审批以及用户或发行负责人的明确批准。`v0.1.3-dev` 是既有不可变开发标签，不得移动或重写。

## References

[1]: ./NEXT_STAGE_API_COMPATIBILITY_PLAN.md "API 兼容性与远程模型配置加固计划"
[2]: ./NEXT_STAGE_OBSERVABILITY_VALIDATION_MAP.md "运行时可观测性与脱敏：验证及证据映射"
[3]: ./H7_VALIDATION_EVIDENCE_TEMPLATE.md "H7 验证证据模板"
[4]: ./V0_1_3_RELEASE_GO_NO_GO.md "v0.1.3 候选发行 Go/No-Go 模板"
