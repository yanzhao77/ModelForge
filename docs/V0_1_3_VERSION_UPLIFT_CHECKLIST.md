# v0.1.3 版本提升清单

**当前状态：** 仅供审阅；`APP_VERSION` 保持开发版本。本清单不授权修改版本、构建、签名、标签或 Release。

| 顺序 | 审阅项 | 完成条件 | 当前状态 |
|---|---|---|---|
| 1 | 锁定候选 SHA | 所有待发行变更位于固定 40 位 SHA。 | 未执行。 |
| 2 | 完成验证证据 | I1–I5、Windows、Linux 与审批 gate 有当期脱敏证据。 | 未执行。 |
| 3 | 批准版本号 | 用户明确批准从 `-dev` 提升到正式语义版本。 | 未执行。 |
| 4 | 更新唯一版本源 | 审阅并更新 `client/pyside6/version.py` 的 `APP_VERSION`。 | 禁止提前执行。 |
| 5 | 对齐元数据 | 审阅 release manifest、SBOM、候选 changelog 与证据 manifest 的同一 SHA/版本。 | 禁止填充虚构证据。 |
| 6 | 签名与原生安装 | 完成受保护签名、checksum、原生安装/卸载与审批。 | 未执行。 |
| 7 | Go/No-Go | 发行负责人和用户基于当前证据作出 Go/No-Go。 | 当前为 No-Go。 |
| 8 | 创建正式标签与 Release | 仅在 Go 和用户明确命令后执行。 | 严禁自动执行。 |

## 版本一致性规则

候选 SHA、`APP_VERSION`、release manifest、SBOM、变更日志、证据 manifest、正式 tag 和 Release Notes 必须逐项一致。任意一项不一致时，默认 No-Go；不得仅重建资产或移动标签以“修复”不一致。

## References

[1]: ./V0_1_3_RELEASE_GO_NO_GO.md "v0.1.3 候选发行 Go/No-Go 模板"
[2]: ./V0_1_3_CANDIDATE_CHANGELOG_TEMPLATE.md "v0.1.3 候选变更日志模板"
