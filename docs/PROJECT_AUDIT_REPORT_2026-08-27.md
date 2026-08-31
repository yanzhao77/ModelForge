# ModelForge 项目详细审核报告

**初次审核：** 2026-08-27

**复核日期：** 2026-08-28

**复核基线：** `master`，HEAD `c561a29923fc14516925156bb918c6c901900a0c`，并包含复核时工作区中的未提交桌面端与测试改动。

**工作区：** 非干净；本报告仅更新审核结论，未回滚任何既有改动。

**范围：** `backend/app/`、`client/pyside6/`、`tests/`、CI、Docker/发布脚本、README 与相关设计文档。
**性质：** 代码与工程交付审核，不等同于渗透测试、性能认证或正式发布批准。

## 1. 执行摘要

ModelForge 已形成 FastAPI 后端 + PySide6 桌面客户端 + 本地优先 Agent Runtime 的完整骨架，功能覆盖认证、会话、模型、知识库、训练、Agent Run、事件流、工具策略、MCP、调度和插件。代码按 API、服务、运行时、仓储和客户端分层，数据库也有 WAL、追加式迁移、事件序列和 outbox 设计。

截至 2026-08-28，初审发现的 2 个 P0 和 5 个 P1 已在代码中关闭：应用入口恢复、runtime 控制面改为管理员授权、模型与下载任务按用户隔离、日志改为管理员专属且脱敏、上传改为流式限额处理、模型路径增加 containment 校验，Agent Run SSE 解析也覆盖无空行与 EOF 场景。

本次实测为 **418 passed、3 skipped、后端覆盖率 71.87%**；`ruff check backend client tests`、当前 CI 的较窄 lint 范围和 `git diff --check` 均通过，应用 import smoke 通过。**代码级整改验收：Pass；正式发布：Conditional No-Go。** 剩余门禁是干净候选提交、CI 中的依赖审计与 Docker 启动、三个环境型测试，以及当前不在质量门禁内的仓库根目录/发布脚本 Ruff 问题。

## 2. 评分与结论

| 维度 | 评分 | 结论 |
|---|---:|---|
| 架构与模块边界 | 8/10 | 分层保持清晰，新增 Alembic、服务端部署档和项目 API；多副本仍受进程级状态限制。 |
| 功能完整度 | 8/10 | 核心桌面与 API 能力可测试，新增项目级 API、配额与用量账本；真实模型依赖环境验证。 |
| 安全与租户隔离 | 8/10 | 初审 P0/P1 均已关闭；仍需完成依赖审计和更高强度的滥用/多副本验证。 |
| 测试与质量门禁 | 8/10 | 418 passed、3 skipped、71.87% 覆盖率；CI lint 范围通过，仍有环境测试与全仓 lint 口径差异。 |
| 可运维性 | 7/10 | 诊断修复并引入 Alembic/PostgreSQL 档；Docker 端到端和多副本协调尚未验证。 |
| 发布准备度 | 7/10 | 已达到候选代码级准入，尚未达到正式发布证据门槛。 |

## 3. 架构与实现概况

### 3.1 已确认结构

- 后端位于 `backend/app`，`main.py` 负责 FastAPI 路由和 lifespan 接线。
- 运行时主链为 API → `AgentRuntime` → `ExecutionEngine` → Ports/Repositories/Adapters。
- 数据库使用 SQLAlchemy + SQLite，启用 WAL、busy timeout、显式迁移和事务 outbox。
- 桌面端通过 `ModelForgeClient` 调 REST/SSE，网络请求主要通过 Qt Worker 移出 GUI 线程。
- 安全设计包含 JWT、PBKDF2 密码哈希、HttpOnly Cookie/CSRF、Fernet 加密远程 API Key、工具 Policy 和确认门。
- 复核静态统计：后端 132 个 Python 文件约 16,992 行；桌面端 53 个文件约 8,202 行；测试 61 个文件约 7,386 行；约 417 个测试函数；API 文件静态统计 157 个路由装饰器。pytest 的 418 个通过项包含参数化收集，因此与函数数不要求相等。

### 3.2 主要优点

1. 运行时执行、事件、工具、策略、MCP、调度均有独立模块，API 大多不直接操作仓储。
2. 会话、记忆、数据集、知识文档、Agent Run 等多数查询带 `user_id` 条件，远程密钥不通过公开 DTO 返回。
3. Agent Run 有状态机、取消令牌、事件序列、SSE 恢复、租约和终态幂等字段；Task Outbox 具备重试和租约字段。
4. 生产环境校验 JWT/CORS，桌面发布脚本生成 checksum，发布决策脚本要求固定 SHA 和门禁证据。
5. `ApiWorker`/`AsyncApiMixin` 对请求生命周期、过期结果和关闭处理有清晰边界。

## 4. 阻断问题复核（P0：2/2 已关闭）

### P0-1 应用启动导入失败：已关闭

**证据：** `backend/app/services/runtime_diagnostics.py:7` 导入 `models.records.AgentEvent`，实际模型类名是 `AgentEventRecord`（`backend/app/models/records.py:486`）。该服务被 `backend/app/api/workspaces.py` 导入，最终阻断 `backend/app/main.py`。

**复现：**

```text
$ PYTHONPATH=backend/app .venv/bin/python -c 'import main'
ImportError: cannot import name 'AgentEvent' from 'models.records'
```

**影响：** Uvicorn、FastAPI TestClient、API/桌面集成测试和 Docker healthcheck 均不能证明服务可用。

**复核证据：** `runtime_diagnostics.py:7` 已使用 `AgentEventRecord`，状态集合也改为 `PENDING/RUNNING/WAITING_HUMAN`。`PYTHONPATH=backend/app .venv/bin/python -c 'import main'` 输出 `IMPORT_OK`；CI 已增加 `tests/test_app_boot.py` 和 import/lifespan smoke gate。

### P0-2 `/api/v1/runtime` 控制面无认证：已关闭

**证据：** `backend/app/api/runtime.py:44-68` 的 `runtime_start`、`runtime_chat`、`runtime_stop`、`runtime_status` 没有 `Depends(get_current_user)`；`main.py:92-109` 将该 router 暴露到 `/api/v1`。Docker 监听 `0.0.0.0:8000`。

**影响：** 端口可达时，未登录调用方即可加载/卸载模型并发起推理，形成高成本资源滥用和模型控制入口。

**复核证据：** `backend/app/api/runtime.py:46-66` 的 start/chat/stop/status 均要求 `get_runtime_admin`，输入也增加模型、消息数量和内容长度边界；`tests/test_security_hardening.py` 覆盖普通用户被拒绝和管理员访问。

## 5. 高风险问题复核（P1：5/5 已关闭）

### P1-1 模型详情跨用户读取：已关闭

`backend/app/api/models.py:167-175` 现调用 `info(model_id, user.id)`；服务层仅返回当前用户或明确的全局模型。用户隔离行为已有模型管理回归测试。

### P1-2 全局日志暴露：已关闭

`backend/app/api/system.py:43-64` 已要求 `get_runtime_admin`，限制每页最多 500 行，使用有界 `deque` 读取并调用 `redact_text`。普通用户 403 与管理员成功路径已由安全测试覆盖。

### P1-3 下载任务无用户归属与持久化：已关闭

下载任务改为 `DownloadTaskRecord` 持久化，创建和查询均带 `user_id`，上游异常只持久化稳定错误码；`tests/test_downloader_security.py` 验证持久化、用户隔离和安全路径。

### P1-4 上传限额校验过晚：已关闭

数据集改用 `DatasetService.upload_stream`，知识库以 64 KiB 分块读取；两者超限后立即返回 413 并清理临时文件。应用层内存 DoS 路径已关闭，生产反向代理仍应保留独立 body limit。

### P1-5 模型扫描允许任意服务器路径：已关闭

`ModelManager._contained_model_path` 将扫描和安装限制在配置模型根目录，越界统一返回 `MODEL_PATH_OUTSIDE_ALLOWED_ROOT`；测试覆盖根目录外路径拒绝。

## 6. 中风险问题（P2）

### P2-1 运行时诊断状态不可靠：已关闭

诊断模型和活动状态值已与持久化 RunStatus 对齐。后续可进一步直接引用共享枚举，降低字符串再次漂移的概率。

### P2-2 客户端 Agent Run SSE 解析依赖空行：已关闭

SSE 解析器现支持空行分帧、多行 data、连续完整 JSON 帧、EOF flush 和协作取消；原失败用例已通过。

### P2-3 错误信息边界不统一：部分关闭

模型搜索和下载已改为稳定错误码；但 `backend/app/api/chat.py:67-70` 的普通聊天路径仍对部分异常返回 `str(exc)`。建议统一为 Problem Details + correlation id，保留为残余 P2。

### P2-4 OpenAI/旧 runtime 输入没有统一上限：部分关闭

旧 runtime 已增加字段和消息数量边界；`backend/app/api/openai_api.py:17-27` 仍缺少同等长度约束和总 prompt 预算，保留为残余 P2。

### P2-5 进程级单例限制多租户和水平扩展

`AgentRuntime`、`PluginManager`、`Downloader`、`RuntimeRegistry` 等使用进程级状态。该模式适合本机单用户，但在多用户或多 worker 部署中会产生状态不一致、任务不可恢复和插件作用域互相影响。应明确部署边界，或把可见状态迁移到持久化存储并引入用户/租户 scope。

### P2-6 开发环境重启会使 JWT 全部失效

`backend/app/core/config.py:173-175` 在 development 且 secret 为空/默认值时每次启动随机生成密钥。安全上优于可预测密钥，但会使重启后全部 token 失效。应在开发文档中明确，或使用仅限本地且明确生成/存储的开发密钥；生产校验应保留。

## 7. 测试、CI 与文档证据

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `.venv/bin/python -m pytest -q` | **418 passed、3 skipped、1 warning**，14.86 秒。 |
| 覆盖率门禁 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q --cov=backend/app --cov-fail-under=30` | **418 passed、3 skipped；71.87%**，高于 30% 门禁。 |
| 应用与迁移代码 lint | `.venv/bin/ruff check backend client tests` | 通过；包含本次修复的 3 个 Alembic import 排序问题。 |
| 当前 CI lint 范围 | `ruff check backend/app client/pyside6 tests` | 通过，但没有覆盖 `backend/alembic`。 |
| 空白检查 | `git diff --check` | 通过。 |
| 仓库根目录 lint | `.venv/bin/ruff check .` | 未通过：未跟踪 `.ui_validate.py` 有 5 个 E402，`scripts/` 有 5 个 I001；这些文件不在当前 CI lint 范围。 |
| 启动烟雾 | `PYTHONPATH=backend/app .venv/bin/python -c 'import main'` | 通过；应用对象存在，静态导入得到 23 条顶层 route 记录。 |
| 依赖审计 | CI 定义 `pip-audit -r requirements.txt` | 本轮本机未重跑；实施状态文档记录先前验证未发现已知漏洞，正式候选仍应由干净 CI 产出当期证据。 |

### 7.1 复核方法与口径

复核以当前文件系统为观察对象，基线包含 HEAD `c561a29` 和未提交改动；因此结果证明“当前工作区”通过，不自动证明该 commit 单独通过。测试通过数以 pytest 实际收集结果为分母，覆盖率只计算 `backend/app` 语句覆盖，不代表分支覆盖、安全覆盖或桌面端覆盖。风险关闭状态同时要求代码路径、对应测试和命令结果三者至少两项相互印证。

### 7.2 限制与稳健性检查

三个跳过项均为环境型验证：公网 Hugging Face 集成未启用、CPU smoke 未提供本地模型、GPU smoke 环境没有 `torch`。FastAPI TestClient 还产生 1 个 Starlette/httpx 弃用警告，不影响当前结果，但应在依赖升级前处理。

本轮 scheduler 测试同步了真实 API 契约：创建响应字段由 `job_id` 改为 `id`，缺少必填字段的验证响应由 400 改为 FastAPI/Pydantic 的 422。它们是测试期望修正，不是本轮新增的生产行为。

当前 CI 已加入 import/lifecycle smoke、30% 覆盖率阈值、依赖审计和 Docker healthcheck。需要注意：`ruff check backend client tests` 已实测通过，但 CI 仍使用更窄的 `backend/app`；“仓库全量 Ruff 通过”也不是当前可复现结论。README 的测试数和路由统计应更新并说明口径。

## 8. 剩余整改与发布路线

### 已完成：M0-M2 代码级整改

1. 应用入口、诊断状态、SSE 解析和确认/执行契约已恢复。
2. runtime、模型、日志、下载和 Agent 文件访问的授权/隔离边界已加固。
3. 上传改为流式限额；密码散列、登录限流、稳定错误和 CI 质量门禁已增强。

### 候选前剩余代码工作

1. 收敛 chat 非流式异常输出，避免 `str(exc)` 进入 API 响应。
2. 给 OpenAI 兼容接口增加消息长度、消息数和总 prompt/token 预算。
3. 将 CI lint 从 `backend/app` 扩到 `backend` 以持续覆盖 Alembic，并决定是否将 `.ui_validate.py` 与 `scripts/` 纳入 Ruff，或明确排除并记录理由。
4. 处理 Starlette TestClient/httpx 弃用警告，避免未来依赖升级突然阻断测试。

### 正式候选验证

1. 在干净 checkout/固定 SHA 上运行 CI lint、418+ 测试、覆盖率、pip-audit 和 SBOM。
2. 完成 Docker image build、容器 `/healthz`、PostgreSQL Alembic upgrade 和单副本服务端 smoke。
3. 按需执行公网 Hugging Face、真实 CPU 模型和 GPU smoke，并记录为何适用或不适用。
4. 将当前未提交桌面端/UI 改动纳入明确候选提交，避免验证结果与候选 SHA 不一致。

### 多副本与商业化边界

未引入外部队列/PubSub 前，PostgreSQL 服务端档保持单应用副本。项目 API 的配额与 UsageLedger 可用于试点，但在完整账期对账、多副本压测和计费审计完成前不接入自动支付。

## 9. 验收标准

- 已满足：应用 import/lifespan、418 tests、71.87% 覆盖率、CI lint、用户隔离、流式上传、路径 containment 和 SSE 边界测试。
- 候选必需：干净固定 SHA、当期 pip-audit/SBOM、Docker healthcheck、Alembic/PostgreSQL smoke。
- 按部署适用：公网集成、真实 CPU/GPU 模型、三平台安装/卸载和签名验证。
- 服务端约束：在分布式协调和多副本压测完成前固定单应用副本。

## 10. 后续问题

1. 正式候选是否只包含 HEAD `c561a29`，还是同时包含当前未提交的桌面 UI 与开发者 API 页面改动？候选范围会改变测试与截图证据。
2. 服务器档是否承诺多副本？若是，需要外部事件通知、分布式任务所有权和多副本故障注入；否则应把单副本限制写入部署检查。
3. `scripts/` 与一次性 UI 验证脚本是否属于受支持代码？该决定应反映在 Ruff 范围，而不是依赖团队口头约定。
4. OpenAI 兼容接口的最大 prompt、并发和用户配额应采用什么产品级默认值？在明确前不宜把它暴露为公网通用入口。

## 11. 最终审计意见

ModelForge 已实质性完成本报告初审要求：所有 P0/P1 均已关闭，测试、覆盖率、应用启动和 CI lint 恢复绿色，项目已从“不可运行”推进到“候选代码级准入”。新增 Alembic/PostgreSQL 档与项目 API 也为受控单副本试点提供了基础。

**复核决定：代码级整改 Pass；正式发布 Conditional No-Go。** 形成干净候选 SHA，并补齐当期 pip-audit、Docker/Alembic、环境型 smoke 与发布资产证据后，可进入最终 Go/No-Go 审核。
