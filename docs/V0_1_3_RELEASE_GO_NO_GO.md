# ModelForge v0.1.3 候选发行 Go/No-Go 模板

**用途：** 此文档仅定义未来获得明确授权后的验证与发行决策记录，不运行测试、构建、签名、安装、标签创建或 Release 操作。

## 1. 候选身份

| 字段 | 待填值 | 要求 |
|---|---|---|
| 候选完整 SHA | `TBD` | 必须是固定 40 位 Git SHA，不得使用分支名或开发标签。 |
| 应用版本 | `TBD` | 正式候选必须不是 `-dev` 版本。 |
| 开发快照 | `v0.1.3-dev` | 仅用于追溯，不得作为正式发行依据。 |
| 决策时间 | `TBD` | 使用 UTC。 |
| 决策人 | `TBD` | 具备发行批准权限。 |
| 脱敏证据清单 | `TBD` | 不含密钥、令牌、证书私钥、正文、完整日志或用户输入。 |

## 2. 阻断门槛

| 门槛 | 必需证据 | Go 条件 | No-Go 条件 |
|---|---|---|---|
| I1 迁移预检与升级验证 | 固定 SHA、ledger、升级副本摘要、失败处理记录。 | 新库与副本升级均通过且 schema 账本一致。 | 缺任一记录、ledger 不一致或升级失败。 |
| I2 并发/事件诊断 | CAS、lease、occurrence、event key、outbox/SSE 脱敏证据。 | 无重复 Run/终态事实，慢消费者可恢复。 | 重复执行、未释放 lease 或无法 resync。 |
| I3 控制面与审计 | 结构化 error、correlation、审计保留期证据。 | 写入口不回显敏感字段且审计可追溯。 | 缺少管理员边界、关联标识或脱敏。 |
| I4/I5 生命周期与桌面 | 关闭、恢复、超时、语言切换、二次确认截图/日志。 | 关闭无残留任务，过期 UI 结果不覆盖当前状态。 | 强制终止、过期覆盖或混合语言关键路径。 |
| Windows/Linux 签名与安装 | 签名验证、checksum、SBOM、原生安装/卸载和审批记录。 | 与候选 SHA 一一对应且受保护审批完成。 | 任一平台缺签名、安装或批准证据。 |
| 用户发行批准 | 明确的正式 tag 与 Release 批准记录。 | 用户/发行负责人批准。 | 未批准或版本仍为 `-dev`。 |

## 3. 建议的脱敏 JSON 清单

```json
{
  "commit": "<FULL_SHA>",
  "version": "<RELEASE_VERSION>",
  "candidate_type": "release-candidate",
  "gates": {
    "i1_migration": {"status": "passed", "evidence_ref": "evidence/i1.json"},
    "i2_concurrency_events": {"status": "passed", "evidence_ref": "evidence/i2.json"},
    "i3_control_plane_audit": {"status": "passed", "evidence_ref": "evidence/i3.json"},
    "i4_lifecycle": {"status": "passed", "evidence_ref": "evidence/i4.json"},
    "i5_desktop": {"status": "passed", "evidence_ref": "evidence/i5.json"},
    "windows_signing_install": {"status": "passed", "evidence_ref": "evidence/windows.json"},
    "linux_signing_install": {"status": "passed", "evidence_ref": "evidence/linux.json"},
    "release_approval": {"status": "passed", "evidence_ref": "evidence/approval.json"}
  }
}
```

## 4. 最终决定

| 决定 | 值 | 说明 |
|---|---|---|
| 正式 tag | `TBD` | 仅在全部门槛通过且版本非开发版后允许。 |
| GitHub Release | `TBD` | 仅在正式 tag 后、资产和签名证据齐备时允许。 |
| 当前默认状态 | **No-Go** | 目前未执行任何验证或签名，且 `APP_VERSION` 仍为开发版本。 |

> **安全约束：** 该模板不得被解释为发布授权。任何正式标签、签名、资产上传或 Release 仍需用户的明确指令和完整的当期证据。

## 5. References

[1]: ./V0_1_3_DEVELOPMENT_PLAN.md "v0.1.3-dev 下一迭代技术计划"
[2]: ./H7_VALIDATION_EVIDENCE_TEMPLATE.md "H7 验证与发行证据模板"
[3]: ./RELEASE_SIGNING_CONFIGURATION.md "受保护签名配置说明"
