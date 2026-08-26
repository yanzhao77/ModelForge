# v0.1.3 平台发行职责矩阵

本矩阵定义未来验证和发行的责任分工，不授予构建、签名、标签、上传或发布权限。

| 阶段 | Windows 负责人 | Linux 负责人 | 发行负责人 | 用户/批准人 | 必需脱敏产物 |
|---|---|---|---|---|---|
| 候选输入锁定 | 核对固定 SHA、版本和 checksum 输入。 | 核对固定 SHA、版本和 checksum 输入。 | 锁定候选身份和 evidence manifest。 | 批准候选进入验证。 | SHA、版本、SBOM 引用。 |
| 原生构建与安装 | 在原生 Windows 环境完成构建、安装、升级/卸载 smoke。 | 在原生 Linux 环境完成构建、安装、升级/卸载 smoke。 | 核对输入与候选 SHA 一致。 | 无。 | 脱敏安装日志、截图、SHA-256。 |
| 签名 | 使用受保护 Authenticode 环境并验证时间戳。 | 使用受保护 GPG 环境并验证签名。 | 审阅签名验证结果。 | 批准受保护环境操作。 | 签名验证摘要、指纹摘要、审批记录。 |
| 证据汇总 | 提交 Windows gate 证据引用。 | 提交 Linux gate 证据引用。 | 维护 manifest，不复制原始密钥或完整日志。 | 审阅 No-Go/Go 材料。 | 完整但脱敏的 manifest。 |
| 正式标签与 Release | 无。 | 无。 | 仅在所有 gate 通过后创建 tag/Release。 | 明确批准 tag 与 Release。 | 批准记录、Release URL、资产校验。 |

> 没有“用户/批准人”的明确授权，发行负责人不得创建正式标签、上传资产或发布 Release。平台负责人不得在文档、日志或 manifest 中写入证书、私钥、API Key、令牌或用户正文。

## References

[1]: ./V0_1_3_RELEASE_GO_NO_GO.md "v0.1.3 候选发行 Go/No-Go 模板"
[2]: ./H7_VALIDATION_EVIDENCE_TEMPLATE.md "H7 验证与发行证据模板"
