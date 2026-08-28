# ModelForge 技术开发实施状态（2026-08-28）

本文记录 `TECHNICAL_DEVELOPMENT_SPEC_2026-08-27.md` 的实际实施结果。实施按 M0、M1、M2、M3、M4 顺序进行；每一阶段的兼容性验证完成后才进入下一阶段。

| 阶段 | 状态 | 已完成的关键交付 |
|---|---|---|
| M0：可运行性 | 已完成 | 修复运行时诊断导入与状态引用；修复人工审批后的状态版本更新；增强 Agent Run SSE 对多行、无空行和 EOF 帧的解析；同步确认与执行契约测试。 |
| M1：安全与隔离 | 已完成 | 默认拒绝文件系统读取；新增每用户受限工作区与敏感文件拦截；收紧 Runtime、模型、系统日志和下载任务的认证/管理员/用户范围；下载状态改为持久化。 |
| M2：输入与质量 | 已完成 | 数据集和知识库上传改为流式限额处理；升级版本化 PBKDF2 散列与登录限流；统一桌面端安全错误提示；CI 加入格式、导入、生命周期、健康检查和覆盖率门禁。 |
| M3：服务端基础 | 已完成 | 数据库支持显式 `DATABASE_URL` 服务端档；新增 Alembic 基线/项目 API 迁移；提供 PostgreSQL 编排、非 root 镜像和卷权限初始化；补充部署说明。 |
| M4：API 产品化基础 | 已完成 | 新增组织、项目、项目 Agent 授权绑定、哈希 API Key、调用回执、强制配额和不可变 UsageLedger；提供 `/api/v2` 控制面和项目密钥调用入口。 |

## 验证证据

| 验证项 | 命令或方式 | 结果 |
|---|---|---|
| 静态检查与空白检查 | `ruff check backend/app client/pyside6 tests`；`git diff --check` | 通过，0 个 Ruff 问题。 |
| 全量测试与覆盖率 | `QT_QPA_PLATFORM=offscreen pytest tests -q --cov=backend/app --cov-fail-under=30` | **413 passed，3 skipped**；总覆盖率 **71.85%**，高于 30% 门禁。 |
| 应用入口与关键安全回归 | `/healthz` 生命周期、文件 containment、下载隔离测试 | 6 passed。 |
| 项目 API | `pytest -q tests/test_api_platform_v2.py` | 3 passed，覆盖密钥撤销、项目绑定、幂等、账本和配额拒绝。 |
| 依赖漏洞与 SBOM | `pip-audit -r requirements.txt`；CycloneDX JSON | 未发现已知漏洞；已在验证环境生成 SBOM。 |
| 服务端编排 | `docker compose -f docker-compose.server.yml config`（使用仅校验用环境变量） | 通过；生产密钥变量缺失时会故意拒绝渲染。 |

## 发布决策与已知边界

当前变更满足本地 SQLite 档与受控单副本服务端试点的代码级准入条件。容器镜像在当前验证环境构建超过 90 秒且没有输出，已主动终止；因此 **Docker 端到端启动验证尚未完成**，CI 仍应在干净执行器上继续承担该门禁。

PostgreSQL 服务端档要求先运行 Alembic，随后才允许应用启动。未引入外部队列或 Pub/Sub 前，服务端部署仍应固定为单应用副本；SSE 的数据库 cursor 保持权威，进程内 EventBus 仅为单副本加速通知。`trial-v1` 用量账本支持配额、用量导出和人工对账，不应在完成一个账期对账与多副本压测前接入自动支付。
