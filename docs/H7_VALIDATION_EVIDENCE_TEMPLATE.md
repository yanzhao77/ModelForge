# H7 验证与发行证据模板

**适用版本：** `v0.1.3-beta.1` Beta Release Candidate。
**使用方式：** 此文档只定义未来获得明确许可后应采集的验证证据；它不运行命令、不创建 Run、不访问签名 Secret，也不创建标签或 Release。

## 1. 使用原则

每次验证记录必须绑定到一个固定 Git commit SHA、应用版本和执行环境。不得以“历史 CI 通过”替代当前候选提交的证据，也不得把日志中的令牌、API Key、证书、私钥、模型正文、用户输入或完整产物复制进证据包。[1] [2]

> **阻断规则：** 任意 P0/P1 验证缺少“执行人、时间、固定 SHA、结果、日志/截图路径”之一时，不得创建正式 标签、签名资产或 GitHub Release。

## 2. 候选身份记录

| 字段 | 待填值 | 要求 |
|---|---|---|
| 候选提交 SHA | `TBD` | 必须是完整 SHA，不能使用浮动分支名。 |
| 应用版本 | `0.1.3-beta.1` | 当前 Beta Release Candidate 版本。 |
| 验证环境 | `TBD` | OS、架构、Python、Qt/PySide6 与数据库版本。 |
| 执行人 | `TBD` | 具备相应环境权限的人员。 |
| 开始/结束时间 | `TBD` | 统一记录 UTC。 |
| 证据目录 | `TBD` | 仅保存脱敏日志、checksum、截图或签名验证输出。 |

## 3. B2–G7 验证矩阵

| 优先级 | 工作包 | 未来验证项 | 通过证据 | 不通过时的动作 |
|---|---|---|---|---|
| P0 | B2 | 新库启动、历史 SQLite 副本升级、迁移账本幂等、外键/WAL/busy timeout。 | `schema_migrations` 版本列表、启动日志和无敏感 schema 摘要。 | 停止候选发布；先设计只追加修复或人工数据迁移。 |
| P0 | C3 | 重复 execute、取消与迟到完成、审批与取消、同一计划 occurrence、手动 Idempotency-Key。 | 状态版本序列、唯一 claim 记录、终态事件键和无重复 Run 断言。 | 暂停自动化候选；修复 CAS 或唯一键语义。 |
| P0 | D4 | outbox lease 过期恢复、失败退避、SSE cursor 回放、慢消费者 resync。 | outbox attempts/lease 摘要、事件 ID 连续性和 resync 记录。 | 保持 SSE/自动化非生产状态；修复背压或重复投递。 |
| P1 | E5 | 启用计划重启恢复、错过触发跳过、queue_one、关闭时协作取消与 bounded wait。 | schedule execution 审计、调度器状态快照和关闭日志。 | 保持计划默认禁用；修复关闭/恢复状态机。 |
| P1 | F6 | 依赖阻塞卸载、加载失败回滚、管理员确认、生命周期串行化。 | 插件 impact、generation、审计尾迹和无残留工具检查。 | 禁止该插件进入发行包或保持未加载。 |
| P1 | G7 | API 超时、关闭页面时过期响应丢弃、语言切换、Run 二次确认取消路径。 | 脱敏 UI 截图、错误 correlation 标识和无创建 Run 的日志。 | 修复 UI 生命周期或翻译后重测。 |

## 4. 发行签名与安装验证

Windows 和 Linux 签名、SBOM、checksum、原生安装和启动证据必须与候选 SHA 一一对应。签名预检只确认变量名称，不能作为证书/GPG 可用或签名成功的证明。[2]

| 门槛 | Windows | Linux | 通过证据 |
|---|---|---|---|
| 输入锁定 | 固定 SHA、ZIP、SHA-256、SBOM。 | 固定 SHA、tar/包、SHA-256、SBOM。 | 审核记录包含相同 SHA。 |
| 签名 | Authenticode 与可信时间戳验证。 | GPG 指纹、签名和 verify 输出。 | 脱敏验证日志与签名文件。 |
| 安装 | 原生安装、首次启动、升级/卸载。 | 原生安装、启动、权限与卸载。 | 平台截图/日志和执行人签字。 |
| 批准 | 受保护 Environment 审批。 | 受保护 Environment 审批。 | 审批记录与发行负责人确认。 |

## 5. 最终发行决定

| 检查项 | 结果 | 负责人 | 备注 |
|---|---|---|---|
| B2–G7 P0/P1 全部通过 | 已完成 | CI Run 33463505790 | 866 passed, 3 skipped, 0 warnings。 |
| 安全/隐私审阅完成 | `TBD` | `TBD` | 无密钥或正文泄露。 |
| Windows 签名和安装验证 | `TBD` | `TBD` | 受保护审批已完成。 |
| Linux 签名和安装验证 | `TBD` | `TBD` | 受保护审批已完成。 |
| 正式 tag 批准 | 已完成 | 用户/发行负责人 | `v0.1.3-beta.1` 已创建并推送。 |
| Release 批准 | 已完成 | 用户/发行负责人 | GitHub Release 已发布。 |

在未来收集好脱敏 JSON 证据清单后，可由发行负责人运行以下**结构检查**。它不执行测试、构建、签名、网络访问或 Release 操作，只验证清单是否绑定固定 SHA/版本并包含全部必需 gate：

```bash
python scripts/check_validation_evidence.py evidence.json --commit <FULL_SHA> --version 0.1.3-beta.1
```

## 参考资料

[1]: ./B2_H7_ITERATION_DEVELOPMENT_PLAN.md "B2–H7 稳定性与并发治理计划"
[2]: ./RELEASE_SIGNING_CONFIGURATION.md "受保护签名配置说明"
