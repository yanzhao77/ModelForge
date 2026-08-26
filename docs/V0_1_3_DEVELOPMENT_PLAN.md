# ModelForge v0.1.3-dev 下一迭代技术开发计划

**版本定位：** `v0.1.3-dev` 验证就绪与稳定性收敛迭代。
**基线提交：** `40f06c47f4f5dbf594d7c679cfb44d6e0a7d4887`。
**开发标签：** 本地注释标签 `v0.1.3-dev`，待 Git 传输恢复后推送。

## 1. 迭代目标与约束

本周期承接 B2–H7 的基础实现，目标不是扩大产品功能面，而是把迁移、状态机、事件流、生命周期、桌面异步和发行门槛收敛为可验证、可诊断、可回退的工程基线。当前仍遵守不执行测试、启动服务、真实模型调用、计划运行、构建、签名、发布或正式标签创建的约束。

| 目标 | 成功定义 | 本周期非目标 |
|---|---|---|
| 验证就绪 | 每项 P0/P1 验收均有固定 SHA、前置条件、脱敏证据位置和明确阻断结果。 | 不在未获许可时运行验证。 |
| 迁移安全 | 可在启动前诊断 ledger、schema 与索引差异，迁移失败不继续启动。 | 不提供破坏性自动降级。 |
| 并发可诊断 | Run、计划、事件和 outbox 的 claim/CAS/背压失败都可通过脱敏状态读取解释。 | 不引入分布式队列或云端常驻服务。 |
| 桌面稳定 | 高频刷新采用请求代次、有限超时和关闭协调；关键路径文案可在中英日间切换。 | 不重写整个 PySide6 页面体系。 |
| 发行治理 | 开发标签、固定 SHA、SBOM、签名预检和证据模板形成顺序清单。 | 不创建正式 `v0.1.3` 或 `v0.1.2` 标签。 |

## 2. 工作包 I1–I6

| 工作包 | 核心任务 | 主要代码边界 | 验收准备与阻断条件 |
|---|---|---|---|
| I1：迁移预检与恢复演练工程 | 增加只读 migration ledger/schema/索引预检、迁移结果摘要、旧库备份提醒和失败诊断规范。 | `backend/app/core/database.py`、`docs/LOCAL_DATABASE_MIGRATIONS.md`、诊断 API。 | 必须在副本数据库上保留升级前后 SHA-256、ledger 和失败日志；正式库未验证前不执行自动迁移演练。 |
| I2：C3/D4 可观测性与恢复诊断 | 为 Run CAS、lease、occurrence claim、event key、outbox lease 和 SSE resync 增加脱敏诊断读模型与管理员只读界面。 | run/event/schedule/task realtime 服务、控制中心。 | 诊断不得显示正文、密钥或完整 payload；需证明读取路径不创建 Run/计划。 |
| I3：契约与审计扩面 | 将其余控制面写端点收敛到 Pydantic 输入、稳定错误 code 和 `correlation_id`；统一审计保留期/导出边界。 | agent、plugin、models、knowledge 等 API。 | 需维护旧客户端兼容矩阵；错误契约不能回显密钥或认证数据。 |
| I4：运行时关闭与补偿状态 | 细化关闭阶段、取消超时、残留任务、插件补偿和 schedule retention 的只读状态；定义受用户确认的恢复动作。 | runtime、scheduler、plugin manager、automation/control 页面。 | 关闭/恢复验证未获许可前只记录状态与计划，不实际启停扩展或计划。 |
| I5：桌面请求编排与三语言审计 | 为高频页面接入 generation key、超时反馈、可丢弃结果与窗口关闭回收；清理剩余硬编码文案。 | `ApiWorker`、API client、automation/control/extensions/workbench 页、i18n。 | 不依赖强制终止线程；每个关键对话框须有 zh/en/ja 资源键。 |
| I6：H7 证据包与 Release Candidate 决策 | 固化证据 JSON schema、签名/安装清单、发行变更日志和 go/no-go 表。 | `docs/H7_VALIDATION_EVIDENCE_TEMPLATE.md`、`scripts/check_validation_evidence.py`、release 文档。 | 未有完整 P0/P1 证据、`APP_VERSION` 正式值和人工批准时，一律阻断正式标签。 |

## 3. 推荐实施顺序

推荐顺序为 `I1 → I2 → I3 → I4 → I5 → I6`。I1 提供安全的数据库事实来源；I2 把 B2–H7 引入的状态机与事件机制变为可诊断对象；I3 让控制面接口稳定承载这些信息；I4 与 I5 分别收敛后端和桌面生命周期；I6 最后仅准备验证和发行决策材料。

## 4. 当前已知阻塞项

| 阻塞项 | 当前状态 | 处理原则 |
|---|---|---|
| Git 传输 | GitHub 443 连接失败，远程对象库尚无 `40f06c4`。 | 恢复后先 `git fetch`，确认远端仍可快进，再推送 `master` 和 `v0.1.3-dev`。 |
| 验证授权 | 用户当前约束为不执行测试、构建和运行操作。 | 只编写验证工程与证据模板；实际验证必须由用户另行明确批准。 |
| 正式发行 | 应用版本仍为 `0.1.2-dev`，签名与跨平台证据未齐备。 | 保持开发标签；禁止创建正式标签、资产或 Release。 |

## 5. I1 实施记录与未验证边界

I1 已新增 `migration_preflight` 只读诊断服务。该服务仅针对文件型 SQLite 数据库以 `mode=ro` 打开连接，检查 `schema_migrations` ledger、由迁移目录推导的列/索引、只读连接的 pragma 摘要，以及缺失或未知版本。它不会调用 `init_db()`、SQLAlchemy metadata 创建、DDL 或迁移函数；返回内容不含数据库路径、表数据、密钥、模型内容或用户 payload。

工作区新增 `/api/v1/workspaces/migration-preflight`，仅运行时管理员可读取。桌面控制中心新增“数据库”标签页，用户显式点击后才请求预检，结果明确显示只读状态和“迁移未执行”说明。该实现尚未连接任何真实数据库、执行升级、启动服务或通过 API/PySide6 验证。

### I2–I6 基础实施记录

I2 新增只读运行时诊断，汇总 Run claim、计划 occurrence、事件键、outbox lease 与 SSE resync 的无内容计数；I3 将插件控制面生命周期动作收敛为 Pydantic 确认请求、稳定 `problem` 错误、`correlation_id` 和脱敏操作审计；I4 新增 Runtime/Scheduler 生命周期与 retention 候选的只读快照；I5 让控制中心和自动化页使用请求代次、协作取消和关闭回收，并补齐数据库诊断与自动化核心按钮的中英日文案；I6 新增 v0.1.3 候选的 Go/No-Go 模板和只做结构校验的决策清单脚本。

这些基础实现不执行状态修复、计划恢复、retention 删除、插件操作、数据库升级、测试、构建、签名、发布或网络发行操作。当前仍需在未来获准的验证阶段逐项产生固定 SHA 的脱敏证据。

## 6. 参考资料

[1] [B2–H7 下一迭代技术开发计划](./B2_H7_ITERATION_DEVELOPMENT_PLAN.md)

[2] [C3 并发状态机与幂等控制技术方案](./C3_CONCURRENCY_AND_IDEMPOTENCY_DESIGN.md)

[3] [H7 验证与发行证据模板](./H7_VALIDATION_EVIDENCE_TEMPLATE.md)

[4] [本地 SQLite 迁移说明](./LOCAL_DATABASE_MIGRATIONS.md)
