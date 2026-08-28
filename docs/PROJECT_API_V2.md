# ModelForge 项目级 Agent API（v2）

`/api/v2` 是面向自动化与后续计量计费的正式接口面。计费单位是 **一次已接受的 Agent Run API 调用及其记录的资源消耗**，而不是 UI 页面访问。现有 `/api/v1` 登录与桌面接口保持兼容，但不应作为外部商业调用入口。

## 控制面流程

首先使用现有 JWT 登录创建组织、项目和项目密钥。项目密钥只会在 `POST /api/v2/projects/{project_id}/keys` 的创建响应中以 `secret` 字段返回一次；数据库与后续列表接口只保存或返回不可逆哈希、前缀和状态。

| 操作 | 接口 | 鉴权 | 关键约束 |
|---|---|---|---|
| 创建组织 | `POST /api/v2/organizations` | JWT | 同一拥有者名称唯一。 |
| 创建项目 | `POST /api/v2/organizations/{org_id}/projects` | JWT | `environment` 为 `test` 或 `live`。 |
| 绑定 Agent | `POST /api/v2/projects/{project_id}/agents` | JWT | 只能绑定当前项目拥有者的 Agent；未绑定 Agent 不可被项目密钥调用。 |
| 签发密钥 | `POST /api/v2/projects/{project_id}/keys` | JWT | 作用域仅限 `agent:run`、`usage:read`；密钥仅展示一次。 |
| 撤销密钥 | `POST /api/v2/projects/{project_id}/keys/{key_id}/revoke` | JWT | 必须传入 `{"confirm": true}`。 |
| 修改额度 | `PUT /api/v2/projects/{project_id}/quota` | JWT | 强制并发、日/月及单 Run 令牌上限。 |
| 查看账本 | `GET /api/v2/projects/{project_id}/usage` | JWT | 仅项目拥有者可见。 |

控制面变更会写入脱敏的操作审计记录；密钥明文、用户输入和 Provider 凭据不得进入审计元数据。

## 调用 Agent Run

外部调用通过 `X-API-Key` 与 `Idempotency-Key` 进行身份识别和重放保护。`Idempotency-Key` 在同一项目中必须唯一；相同 key 与相同请求体会返回原调用回执，而同一 key 对应不同请求体会返回 `409 IDEMPOTENCY_KEY_REUSED`。

```bash
curl -X POST https://api.example.com/api/v2/runs \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: mf_<prefix>_<secret>' \
  -H 'Idempotency-Key: 2b0d5da8-15d5-4d32-b0bf-a760f6ad0a19' \
  -d '{"agent_id":"support-agent","input":"总结本周工单","max_tokens":2048}'
```

API 会在执行昂贵工作前创建项目级配额预留，并验证目标 Agent 已被显式授权给密钥项目。调用完成后，系统会写入不可变的 `UsageLedger` 令牌事实（包含零令牌终态，以保留完整审计链）。重复调用不会再次执行或追加账本行。

## 错误码与客户处理

| HTTP 状态 | 错误码 | 客户端处理 |
|---:|---|---|
| 401 | `API_KEY_INVALID` | 停止重试，检查密钥是否撤销、过期或配置错误。 |
| 403 | `API_KEY_SCOPE_DENIED` | 使用具备所需 scope 的密钥。 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 生成新的幂等键；不可复用到不同负载。 |
| 429 | `PER_RUN_QUOTA_EXCEEDED`、`DAILY_QUOTA_EXCEEDED`、`MONTHLY_QUOTA_EXCEEDED`、`CONCURRENCY_QUOTA_EXCEEDED` | 不重试昂贵动作；等待配额窗口或由项目所有者调整额度。 |
| 404 | `AGENT_NOT_FOUND`、`API_INVOCATION_NOT_FOUND` | 不透露其他用户或项目资源的存在性。 |

所有 v2 错误响应都有安全的 `detail.code` 和 `detail.correlation_id`。支持工单应引用 correlation ID，而不应要求客户上传密钥或完整请求体。

## 试点限制

当前账本版本为 `trial-v1`，用于用量记录、配额执行和人工对账，**不包含在线支付或自动扣款**。在接入支付之前，应至少完成一个账期的数据对账、并发配额压力测试、PostgreSQL 迁移演练和多实例队列/通知适配器验证。
