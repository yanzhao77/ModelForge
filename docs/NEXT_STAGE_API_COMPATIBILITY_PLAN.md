# 下一阶段：API 兼容性与远程模型配置加固计划

**规划基线：** `33c65a8e7875ffc6813f2fad4d31f5ddbeecef04`。
**当前状态：** 仅规划。本文不会启用远程模型、调用 provider、创建 Agent Run、运行计划、迁移数据库、构建、签名、打标签或创建 Release。

## 1. 目标

本阶段在既有本地优先运行时、OpenAI-compatible 服务和桌面模型页之上，收敛远程模型配置与 API 协议边界。重点是让远程 provider 默认采用 OpenAI **Responses API**，仅在用户明确选择时使用 Chat Completions 回退；确保 API Key 始终只在后端加密/解密并且 write-only；使模型、知识、训练与兼容接口的失败响应可被桌面客户端安全关联和解释。

> **不变量：** API Key、token、密码、cookie、私钥、原始模型消息、工具参数、知识正文、训练数据和完整底层异常不得进入 API 响应、桌面 UI、审计、诊断、事件、日志、导出、模板、manifest 或构建产物。

| 顺序 | 工作包 | 目标交付 | 明确排除 |
|---:|---|---|---|
| AC1 | 远程 provider 配置规范化 | 后端 URL/protocol/model 名称校验与 canonical 配置摘要；Responses 默认、Chat Completions 明确回退。 | 不发出 HTTP 请求、不探测 provider、不回显或持久化明文 API Key。 |
| AC2 | API 错误契约收敛 | 为模型/知识/训练等剩余控制面定义稳定 problem code、关联标识和脱敏信息。 | 不启动下载、上传、训练、扫描或实际推理。 |
| AC3 | SSE 恢复与事件 cursor 契约 | 定义 session/run 边界、cursor 失效、重连退避和只读 resync 的兼容响应。 | 不启动 SSE 服务或发布事件。 |
| AC4 | 桌面模型配置与多语言 | 模型页显示安全的 provider 配置摘要、协议选择和错误关联标识；补齐中英日文案。 | 不向 UI 回显密钥、不自动保存或连接远程 provider。 |
| AC5 | 文档与验证映射 | 固定候选 SHA 的协议兼容、密钥隔离、SSE 恢复和多语言证据清单。 | 不运行测试、网络调用、迁移、构建、签名或 Release。 |

## 2. AC1：远程 provider 配置规范化

服务层应把可持久化、非敏感配置限制为 provider 类型、HTTPS/HTTP base URL、模型名、协议枚举、超时和启用意图。协议枚举固定为 `responses` 与 `chat_completions`，默认选择 `responses`；`chat_completions` 只能作为已有供应商兼容场景的显式回退。Endpoint 路径应由后端依协议追加，不能要求桌面客户端拼接 `/v1/responses` 或 `/v1/chat/completions`。

API Key 必须继续通过既有 write-only 输入与后端加密路径处理。任何 list/detail/default/审计/诊断响应只可返回 `has_credentials`、`credential_updated_at` 等布尔/时间摘要，永远不返回密钥值、长度、前缀或哈希。

## 3. AC2：控制面失败响应

控制面端点应采用统一的 `{code, message, correlation_id}` problem 形状。`message` 是稳定、可翻译、无正文的简短描述；`code` 允许桌面客户端选择可行动提示；`correlation_id` 用于操作审计与支持排查。底层 `Exception` 文本只能在后端安全日志中以类型或内部关联方式记录，不得串接入 HTTP `detail`。

优先顺序是模型 provider CRUD/default、知识库元数据控制面、训练配置草稿，再评估执行型端点。上传、查询、回答、下载、安装、训练启动与 provider 调用不属于无运行性实施范围。

## 4. AC3：SSE cursor 与重连

协议设计要将 cursor 解释为某个用户作用域、session/run 与 event stream 的只读位置，而不是可跨用户重放的全局指针。应定义：无效/过期 cursor 的稳定错误码、客户端退避上限、重新读取的起点、事件已脱敏保证和关联 ID。实现时必须保留“服务器不因重连而创建 Run、恢复计划、补偿插件或调用模型”的不变量。

## 5. AC4：桌面体验

模型页及相关对话框应将协议文本、provider 配置摘要、关联 ID、错误状态和确认提示全部纳入 `ui_localizer.py`。页面只在用户明确保存后提交配置；保存前可进行本地字段格式校验，但不可自动检测 provider 联通性。界面不能混用中文、英语和日语，也不能将 `has_credentials` 推断为密钥有效。

## 6. AC5：后续验证与发行门槛

未来验证必须冻结一个完整 40 位 SHA，分别验证：Responses 默认请求形状、显式 Chat Completions 回退、API Key 非回显、problem/correlation 兼容、SSE cursor 隔离/重连、桌面三语言与关闭路径。任一项未完成、出现敏感信息或产生未经确认的运行性副作用时，保持 **No-Go**；不得创建正式 tag、签名、上传资产或发布 Release。

## References

[1]: ./NEXT_STAGE_OBSERVABILITY_REDACTION_PLAN.md "运行时可观测性与脱敏加固计划"
[2]: ./NEXT_STAGE_OBSERVABILITY_VALIDATION_MAP.md "运行时可观测性与脱敏验证及证据映射"
[3]: ./V0_1_3_NON_TEST_DEVELOPMENT_DESIGN.md "v0.1.3 非测试型续开发设计"
