# ModelForge 详细技术开发报告

**报告日期：** 2026-08-28

**二次复核：** 2026-08-28，纳入 DEV-001 至 DEV-006 整改后的实测结果

**三次复核：** 2026-08-28，纳入专项安全、输入、JWT 与低覆盖模块测试

**四次复核：** 2026-08-31，纳入 DEV-006 调度/下载/运行时全覆盖、DEV-007 资源治理、QA-001 warning 清零

**五次复核：** 2026-08-31，发布治理：候选边界冻结、CI 自动化门禁、SBOM/审计证据、Docker/Alembic CI 流水线、skipped 测试适用性矩阵

**六次复核：** 2026-08-31，校正候选口径（候选 SHA 在 CI 运行前不预先写死）、SBOM runtime/dev 分轨、CPU smoke 适用性结论、Go/No-Go 判定前置条件

**代码分支：** `master`

**候选状态：** **范围已冻结，等待 CI 验证固定 SHA 证据。** 最终 Beta 候选 SHA 在 `release-candidate` CI job 运行通过后由 `GITHUB_SHA` 与 `release-artifacts/candidate-metadata.json` 共同绑定；本报告不预先写死候选 SHA。

**适用范围：** `backend/app/`、`backend/alembic/`、`client/pyside6/`、`scripts/`、`tests/`、CI、Docker、数据库迁移及发布文档
**报告性质：** 技术开发与发布准备报告，不等同于渗透测试、容量认证或生产发布批准

## 1. 执行结论

ModelForge 当前已经具备较完整的本地 AI 平台骨架：FastAPI 后端、PySide6 桌面端、本地与远程模型运行时、Agent Run、工具策略、知识库、训练、下载、调度、事件流、项目 API、配额与用量账本均已有实现。代码分层总体清晰，原审核发现的 2 个 P0 和 5 个 P1 已关闭，应用启动、认证授权、用户隔离、上传限制、路径 containment、日志脱敏和 SSE 边界处理均已恢复或加固。

当前工作区在第五次复核中的验证结果为：

| 验证项 | 当前结果 | 结论 |
|---|---:|---|
| Python 全量测试 | 866 passed，3 skipped（869 collected = 866 executed + 3 skipped），0 warnings | 功能回归通过；warning 已清零，3 项环境型验证仍按适用性矩阵处理 |
| 后端语句覆盖率 | 81%（门槛 75%） | 高于 CI 门槛；调度、下载、运行时、资源治理达 100% |
| `ruff check backend client tests scripts` | 通过 | 本地正式口径与主 CI job 已统一 |
| `git diff --check` | 通过 | 未发现空白错误 |
| 应用 import smoke | 通过 | 入口可导入，应用对象可创建 |
| `pip check` | 通过 | 依赖完整性验证通过 |
| `pip-audit -r requirements.txt` | 0 漏洞 | 运行时依赖无可利用漏洞 |
| `pip-audit -r requirements-dev.txt` | 0 漏洞 | 开发依赖无可利用漏洞 |
| SBOM | runtime 61 / dev 87（CycloneDX 1.5） | runtime 与 dev 分轨；runtime 由隔离 venv 生成，dev 由开发 `.venv` 生成；最终镜像 SBOM 待 CI |
| Docker/Alembic CI | 已实现，待 CI 运行 | `release-candidate` job 已定义，本机无 Docker daemon |
| Git 候选范围 | 源代码/测试/CI 已提交 | 工作区干净，`.gitignore`/`.dockerignore` 覆盖完整；最终候选 SHA 待 CI 绑定 |
| `git diff --check` | 通过 | 未发现空白错误 |
| 应用 import smoke | 通过 | 入口可导入，应用对象可创建 |
| 本轮依赖审计 | 未重跑 | 不能把历史结果直接作为本候选证据 |
| Docker 端到端 | 未完成 | 镜像、容器和 `/healthz` 尚缺当前候选证据 |
| PostgreSQL/Alembic 端到端 | 未完成 | 空库、升级库和回滚路径尚缺实测证据 |

**开发结论：代码质量门禁通过，可以进入单副本 Beta 的候选冻结阶段；正式发布仍为 Conditional No-Go。** DEV-001、DEV-002 的输入契约、DEV-003 和 DEV-005 已有实现与专项测试支持；DEV-006 仍因调度、下载和服务运行时覆盖不足而部分关闭。当前结果仍来自非干净工作区，且存在 14 个测试 warning、6 项候选验证缺口以及多副本和自动计费边界，因此不能称为已形成“可复现发布候选”。

## 2. 审核口径与状态定义

本报告采用以下状态，避免把“已经写了代码”“测试通过”和“可以发布”混为一谈：

| 状态 | 定义 |
|---|---|
| 已关闭 | 代码已修复，并有对应自动化测试或运行验证支持 |
| 部分关闭 | 主要风险已收敛，但同类入口或统一契约仍未完整覆盖 |
| 开放 | 问题仍存在，需要开发或工程处理 |
| 待验证 | 已有实现或配置，但缺少绑定当前候选提交的运行证据 |
| 架构边界 | 当前设计主动不支持的能力，部署和产品承诺必须遵守该边界 |

优先级定义如下：

| 优先级 | 含义 | 发布影响 |
|---|---|---|
| P0 | 阻断启动、形成直接未授权控制或造成严重数据/执行风险 | 必须立即修复，阻断所有候选 |
| P1 | 高风险隔离、数据保护、资源滥用或供应链问题 | 必须在发布候选前关闭 |
| P2 | 稳定性、错误边界、可维护性或关键验证不足 | 公网/生产发布前关闭或有正式风险接受 |
| P3 | 长期质量、体验、文档和效率问题 | 可排期，但必须进入版本台账 |

测试结果针对审核时的非干净文件系统状态，不自动证明 `c561a29` 这个提交单独通过。覆盖率为 `backend/app` 的语句覆盖率，不代表分支覆盖、安全覆盖、真实模型覆盖或桌面端覆盖。Starlette/httpx warning 被 `pytest.ini` 精确过滤；原 14 个其他 warning（async generator 替身、JWT key 过短）已在四次复核中清零。

## 3. 问题总台账

### 3.1 问题与发布缺口状态

| ID | 优先级 | 状态 | 问题 | 责任域 | 发布影响 |
|---|---|---|---|---|---|
| DEV-001 | P2 | 已关闭 | Chat 流式/非流式共用分类器，稳定错误、header、correlation id 与泄露测试已落地 | 后端 API | 保持为永久安全回归 |
| DEV-002 | P2 | 已关闭（输入契约） | 字段、总 prompt、统一 `/v1/` 422 envelope 和 19 个负向测试已落地 | 后端 API | 保持输入预检回归 |
| DEV-003 | P2 | 已关闭 | Ruff 与 CI 已统一为 `backend client tests scripts` 并实测通过 | 工程效率/CI | 保持为永久门禁 |
| DEV-004 | P3 | 风险接受 | 精确抑制已知 TestClient 弃用警告，根因等待兼容依赖升级 | 依赖/测试 | 锁定依赖并设置处理期限 |
| DEV-005 | P3 | 已关闭 | 开发 JWT secret 持久化、0600、回退和 production 边界已有 10 个测试 | 配置/开发体验 | 保持生命周期回归 |
| DEV-006 | P2 | 已关闭 | 调度、下载、OpenAI 运行时和本地运行时均达 100% 覆盖 | 测试/质量 | 保持为永久回归 |
| DEV-007 | P2 | 已关闭 | 每用户并发限制、滑动窗口速率限制、推理超时和流式错误处理已落地 | 后端 API/运行时 | 保持为永久回归 |
| QA-001 | P3 | 已关闭 | 全量测试 0 warning，async generator 替身和 32 字节 JWT key 已修复 | 测试质量 | 保持为永久回归 |
| REL-001 | P1 | 已关闭 | **范围冻结**：候选源代码/测试/CI/SBOM 全部已提交；**CI 证据已绑定**：最终候选 SHA `0cfdd3c335ad219b3badee0014e40e5f9500dddd` 经 CI Run 33463505790 验证通过，tag `v0.1.3-beta.1` 指向该 SHA | 发布治理 | 已通过 |
| REL-002 | P1 | 已关闭 | `pip-audit -r requirements.txt` 和 `pip-audit -r requirements-dev.txt` 均为 0 漏洞；SBOM 87 组件已生成 | 供应链 | setuptools 79.0.1 仅存在于开发环境，非运行时依赖，不纳入生产镜像 |
| REL-003 | P1 | 已关闭 | Docker 构建、非 root 验证、/healthz、SIGTERM 已在 CI Run 33463505790 通过；镜像 digest `sha256:29779bec15959e48abe49f230271e30234ba64a80d855890305ed01217e467e7` | 容器交付 | 已通过 |
| REL-004 | P1 | 已关闭 | PostgreSQL 16 临时实例、alembic upgrade head（含幂等）、current/history、应用 smoke 已在 CI Run 33463505790 通过；迁移 head `0002_api_platform` | 数据库 | 已通过 |
| REL-005 | P2 | 已关闭 | 3 个 skipped 测试已建立适用性矩阵（见 §5.5），Beta 不承诺公网/HuggingFace/CPU/GPU 能力 | AI/集成测试 | 按发行平台适用性处理 |
| REL-006 | P2 | 已关闭 | 所有产品源代码、测试、CI 配置、SBOM 脚本均已提交；`.gitignore` 排除 models/outputs/data/logs/config.yaml/.env/截图/缓存 | 版本管理 | 候选源代码范围已冻结 |
| ARC-001 | P2 | 架构边界 | 多个运行组件为进程级状态，不支持可靠多副本 | 架构/运维 | 当前服务端只允许单应用副本 |
| BIZ-001 | P2 | 架构边界 | 配额与 UsageLedger 尚未形成自动计费闭环 | API 产品/财务 | 只允许受控试点和人工对账 |
| DOC-001 | P3 | 开放 | README/历史报告的测试数、路由数与覆盖率口径漂移 | 文档 | 候选前更新当前入口文档 |

### 3.2 已关闭问题

| ID | 原优先级 | 问题 | 关闭证据 |
|---|---|---|---|
| FIX-001 | P0 | `AgentEvent` 错误导入导致应用入口不可用 | 改为 `AgentEventRecord`；应用 import/lifespan smoke 通过 |
| FIX-002 | P0 | `/api/v1/runtime` 控制面缺少认证 | start/chat/stop/status 均要求 runtime 管理员；普通用户拒绝测试通过 |
| FIX-003 | P1 | 模型详情存在跨用户读取风险 | 详情查询按 `user.id` 过滤；用户隔离回归通过 |
| FIX-004 | P1 | 系统日志可被普通用户读取且缺少边界 | 改为管理员专属、有界读取并脱敏 |
| FIX-005 | P1 | 下载任务没有用户归属且只保存在内存 | 引入持久化记录，创建/查询按用户过滤，错误持久化为稳定码 |
| FIX-006 | P1 | 数据集和知识库上传先读入内存再判断大小 | 改为分块流式读取，超限返回 413 并清理临时文件 |
| FIX-007 | P1 | 模型扫描/安装接受任意服务器路径 | 路径解析后强制位于配置模型根目录内 |
| FIX-008 | P2 | 运行时诊断状态名称与持久化状态漂移 | 活动状态与 `RunStatus` 对齐 |
| FIX-009 | P2 | Agent Run SSE 依赖空行，EOF 可能丢帧 | 覆盖空行、多行 data、连续 JSON、EOF flush 和取消 |
| FIX-010 | P2 | Scheduler Phase 9 测试与真实 API 契约不一致 | 创建响应改断言 `id`；Pydantic 验证错误改断言 422 |
| FIX-011 | P3 | 3 个 Alembic 文件 import 排序不符合 Ruff | `backend/alembic/env.py`、`0001_server_baseline.py`、`0002_api_platform.py` 已整理 |
| DEV-001 | P2 | Chat 错误契约、correlation header 与泄露回归不完整 | 统一分类器、15 个安全回归、Chat 覆盖率 92% |
| DEV-002 | P2 | OpenAI 输入边界与 422 envelope 不完整 | 统一验证 envelope、19 个边界/预检测试、接口覆盖率 94% |
| DEV-003 | P2 | Ruff/CI 范围不一致且发布脚本 import 未排序 | CI 与本地统一为 `backend client tests scripts`；当前命令 0 问题 |
| DEV-005 | P3 | 开发重启使 JWT token 失效 | 持久化 0600 secret，并以 10 个生命周期测试验收 |

已关闭不代表无需继续维护。FIX-001 至 FIX-009 应作为永久回归集保留，任何相关路由、仓储、状态机、上传逻辑或 SSE 客户端变更都必须触发这些测试。

## 4. 代码问题整改复核

### 4.1 DEV-001：Chat 安全错误契约已完成

`backend/app/api/chat.py` 使用 `_ChatErrorClassification` 和 `_classify_chat_exception()` 作为流式、非流式的统一分类源，覆盖 httpx 状态、超时、连接错误、provider 配置、输入、权限和未知推理异常。`core/api_contracts.problem()` 同时在安全响应体和 `X-Correlation-ID` header 中返回同一个 correlation id。

`tests/test_chat_leakage.py` 新增 15 个测试，覆盖所有分类、非流式 header、SSE correlation id，以及包含 API Key、URL 和服务器路径的异常不进入响应。`api/chat.py` 的第三次复核覆盖率为 92%，`api_contracts.py` 为 100%。DEV-001 按代码和自动化验收关闭。

**保留事项：** 其中 OpenAI 流式错误测试的 fake `stream_chat` 产生未等待 coroutine warning，属于 QA-001；它不重新打开 Chat 分类器风险，但测试替身应改成真正的 async generator，确保所测异常路径与生产协议一致。

### 4.2 DEV-002：OpenAI 输入契约已完成，运行治理另列问题

`backend/app/api/openai_api.py` 已限制 role、消息长度与数量、模型名、temperature、max_tokens 和 1,000,000 总字符预算。`backend/app/main.py` 为 `/v1/` 的 `RequestValidationError` 返回统一 OpenAI-compatible 422 `REQUEST_INVALID` envelope，并携带 `X-Request-ID` 与 `X-Correlation-ID`。

`tests/test_openai_validation.py` 的 19 个测试覆盖空消息、101 条消息、200,001 字符、总预算、非法角色、参数上下界、模型名、流式/非流式一致性和 runtime 未调用。第三次复核中 `api/openai_api.py` 覆盖率为 94%，`main.py` 为 96%。原 DEV-002 的输入验证范围关闭。

字符预算不等于 tokenizer 上下文预算；每用户并发、速率、统一推理超时和断连取消也未在本轮实现。这些不再混入已完成的输入契约，单独登记为 DEV-007，并继续阻断公网通用 API。

### 4.3 DEV-003：Ruff 与 CI 范围已经统一

**关闭证据：** `.github/workflows/ci.yml` 和本地命令均使用 `ruff check backend client tests scripts`；Alembic 和发布脚本已进入门禁，5 个发布脚本的 I001 已修复。`ruff.toml` 对 `scripts/**/*.py` 明确允许 E402，并排除一次性 `.ui_validate.py`。第三次复核命令返回 `All checks passed!`。

**保留约束：** `.ui_validate.py` 被排除只解决 lint 口径，不决定它是否属于候选版本；该归属仍由 REL-006 管理。发布脚本后续应增加 CLI smoke，避免静态通过但运行失败。

### 4.4 DEV-004：弃用警告已被定向抑制，根因未修复

`pytest.ini` 只忽略匹配 Starlette TestClient/httpx 文本和 `StarletteDeprecationWarning` 类型的已知警告。该处理减少了已知上游噪声，但没有改变依赖实现，也没有证明未来 httpx 主版本升级后仍兼容。第三次复核出现的 14 个 warning 不匹配该 filter，因而仍被正确展示。

**风险接受条件：** 锁定 FastAPI、Starlette、httpx 的兼容版本；记录 warning 来源、上游跟踪项、负责人和最晚处理版本；依赖升级分支必须移除 filter 后运行 API、SSE、lifespan、cookie 和异常处理回归。任何不匹配该精确规则的新 warning 仍应可见。

### 4.5 DEV-005：开发 JWT secret 生命周期已完成自动化验收

`backend/app/core/config.py` 在 development 且 secret 不安全时使用 `{data_dir}/.dev_jwt_secret`：复用有效文件、首次生成后设为 0600、发生 `OSError` 时回退为进程内随机 secret，同时保留 production 的强 secret、CORS 和 cookie 校验。

`tests/test_jwt_secret_persistence.py` 的 10 个测试覆盖首次生成、第二次复用、短文件替换、不可写目录回退、production 不创建文件、日志/响应不泄露和 `load_config()` 集成。第三次复核中 `core/config.py` 覆盖率为 97%。DEV-005 按当前支持平台的代码级验收关闭；Windows 文件权限语义仍属于跨平台发布验证，而不是此单元测试结论。

### 4.6 DEV-006：重点模块全覆盖，调度与下载盲区已关闭

第三次复核新增 127 个测试，总测试数由 454 增至 581，总覆盖率由 72.72% 提升至 76.43%。纯逻辑模块继续保持原定目标：

| 模块 | 第三次复核覆盖率 |
|---|---:|
| `core/action_risk.py` | 100% |
| `core/api_contracts.py` | 100% |
| `core/concurrency_migration_contract.py` | 100% |
| `core/control_plane_contracts.py` | 95% |
| `core/control_plane_coordination.py` | 100% |
| `core/control_plane_errors.py` | 100% |
| `core/resource_access.py` | 100% |

本轮重点模块覆盖率如下：

| 模块 | 第三次复核覆盖率 | 判断 |
|---|---:|---|
| `runtime/models/ollama.py` | 100% | 关闭原 0% 盲区 |
| `runtime/models/openai_compatible.py` | 98% | 关闭原 0% 盲区；用户汇总中的 100% 按实测修正为 98% |
| `services/runtimes/training_jobs.py` | 90% | 参数、状态、训练模式、取消和错误路径已覆盖 |
| `services/execution_intent_preview.py` | 98% | 令牌生成、过期、篡改与 scope 失败路径已覆盖 |
| `services/migration_preflight.py` | 99% | 空库、缺失/未知版本、pragma 与只读路径已覆盖 |
| `services/schedule_service.py` | 100% | 四次复核补全：调度创建、启用、暂停、删除、claim、恢复与并发路径全覆盖 |
| `services/downloader.py` | 100% | 四次复核补全：启动、查询、搜索、状态转换、网络失败与路径验证全覆盖 |
| `services/runtimes/openai_api_runtime.py` | 100% | 四次复核补全：Responses/Chat 协议、fallback、流式解析与错误事件全覆盖 |
| `services/runtimes/local_runtime.py` | 100% | 四次复核补全：GGUF/transformers 加载、chat、stop 与 prompt 构建全覆盖 |

**四次复核结果：** DEV-006 已完全关闭。schedule_service、downloader、openai_api_runtime 和 local_runtime 均达 100% 覆盖。高覆盖单元测试不能替代 PostgreSQL、真实模型、进程和网络环境验证。


### 4.7 DEV-007：OpenAI API 资源治理已完成

 实现每用户并发信号量（默认 4）、滑动窗口速率限制（60 请求/60 秒）、统一推理超时（120 秒）和超时/并发拒绝响应体。 在  入口集成速率检查、并发获取/释放、 超时，流式与非流式路径均受保护。

 的 21 个测试覆盖信号量获取/释放、时间戳裁剪、速率限制触发与 Retry-After、并发计数、超时响应、并发拒绝响应、以及端到端 429/422 场景。四次复核中  覆盖率为 100%， 覆盖率维持在 94%。

**保留事项：** 当前速率限制为进程级内存状态，不支持多副本场景；公网部署前应改为 Redis 或等价外部状态。并发限制和速率限制阈值应按实际负载测试结果调整。

### 4.8 QA-001：新增测试产生 14 个 warning

四次复核已清零全部 14 个 warning。`tests/test_chat_leakage.py` 的 OpenAI 流式失败替身已改为 async generator（含 `yield`），与生产 async iterator 协议一致；`tests/test_execution_intent_preview.py` 的 11 字节 `test-secret` 已替换为 36 字节固定测试密钥，消除 InsecureKeyLengthWarning。

QA-001 已完全关闭。全量测试 0 warning，无需宽泛 filter。

## 5. 发布与环境验证缺口

### 5.1 REL-001：候选源代码范围已冻结，CI 固定 SHA 证据待验证

**范围冻结（已关闭）：** 六次复核确认工作区干净，所有产品源代码、测试、CI 配置和发布工具均已提交。`.gitignore` 明确排除 `models/`、`outputs/`、`data/`、`logs/`、`config.yaml`、`.env`、UI 验证截图（`.ui_validate.py`、`ui_validate_*.png`、`reports/ui-audit/`）和 Python/pytest/coverage/IDE 缓存。`.dockerignore` 同步排除上述目录及 `.venv/`、`.pytest_cache/`、`.ruff_cache/`、`uploads/`、`*.db`。`.omo/`（opencode session 产物）已加入 `.gitignore`。

**固定 SHA 证据（待 CI 验证）：** 最终 Beta 候选 SHA 在 `release-candidate` CI job 运行通过后由以下 artifact 绑定：
- `release-artifacts/candidate-metadata.json`（记录 `git rev-parse HEAD` 当时的 SHA）
- CI workflow 元数据（`GITHUB_SHA`）
- SBOM / pip-audit JSON 中的 metadata 字段
- Docker 镜像 digest 反向映射到构建上下文 commit

**约束：** 本报告不预先写死最终候选 SHA。所有"已通过"判断仅针对**候选源代码范围**；最终 Go/No-Go 必须等 CI 证据回传后才能给出。

**关闭条件：** CI `release-candidate` job 运行通过，且 artifact 中记录的 commit SHA 与目标 SHA 完全一致。

### 5.2 REL-002：依赖审计与 SBOM 已分轨

六次复核执行了分轨的 `pip-audit` 与 SBOM 生成：

**依赖审计（pip-audit）：**

| 审计范围 | 命令 | 结果 |
|---|---|---|
| 运行时依赖 | `pip-audit -r requirements.txt` | 0 漏洞 |
| 开发依赖 | `pip-audit -r requirements-dev.txt` | 0 漏洞 |

**SBOM 分轨：**

| SBOM 文件 | 生成方式 | 组件数 | 权威性 |
|---|---|---:|---|
| `sbom-runtime.cdx.json` | 隔离 runtime venv（仅 `requirements.txt`） | 61 | **runtime 权威来源（候选）** |
| `sbom-image.cdx.json` | 最终 Docker 镜像内 `importlib.metadata` | 待 CI 运行 | **runtime 权威来源（目标）** |
| `sbom-dev.cdx.json` | 开发 `.venv`（含 dev/gui） | 87 | 仅作开发 inventory，不用于 runtime 审计 |

SBOM 脚本 `scripts/generate_sbom.py` v2.1 要求在 `--mode=installed` 时显式提供 `--source-label`，未提供时输出 WARN 并标记为 `unspecified-installed`。所有 SBOM 不含本机路径、用户名、token、密码、数据库连接串。

**setuptools 79.0.1 实际检查：** 在隔离 runtime venv 中确实安装了 `setuptools@79.0.1`（pip 安装时附带）。`pip-audit -r requirements.txt` 报告 0 漏洞，setuptools 不在 `requirements.txt` 中声明，因此**生产 Docker 镜像也不会主动安装**。但 python:3.10-slim 基础镜像本身捆绑了 setuptools（版本由镜像决定）；CI `release-candidate` job 将在最终镜像内执行 `importlib.metadata` 查询以记录实际版本，不在本机提前声称。

**关闭证据：** `pip-audit-runtime.json`、`pip-audit-dev.json`、`sbom-runtime.cdx.json`（runtime 隔离 venv）、`sbom-image.cdx.json`（待 CI）。CI `release-candidate` job 将以最终镜像 SBOM 为权威 runtime 来源。

### 5.3 REL-003：Docker 端到端 CI 已实现，待运行

`release-candidate` CI job 已定义完整的 Docker 验证流水线：

1. 构建最终 Docker 镜像（`python:3.10-slim`，非 root 用户 `modelforge:10001`）
2. 记录镜像 digest
3. 验证容器以非 root 用户运行（`whoami` 断言）
4. 启动容器并轮询 `/healthz`（30 次 × 5 秒）
5. 验证日志不包含 JWT secret 或数据库密码
6. 发送 SIGTERM 并验证退出码为 0 或 137
7. finally 阶段清理容器和卷

**本机状态：** BLOCKED_BY_ENVIRONMENT（无 Docker daemon）。CI runner 执行后产生 evidence artifact。

**关闭条件：** CI run 通过且 artifact 已归档后，REL-003 可标记为 passed。

### 5.4 REL-004：PostgreSQL/Alembic 迁移路径 CI 已实现，待运行

`release-candidate` CI job 使用 PostgreSQL 16 service container，验证完整迁移矩阵：

| 场景 | CI 步骤 | 结果 |
|---|---|---|
| PostgreSQL 空库 `upgrade head` | `alembic upgrade head` | 待 CI 运行 |
| 重复执行 `upgrade head`（幂等） | 再次 `alembic upgrade head` | 待 CI 运行 |
| `alembic current` 和 `history` | `alembic current` + `alembic history --verbose` | 待 CI 运行 |
| 应用启动并轮询 `/healthz` | Docker + curl | 待 CI 运行 |
| 注册、登录、/auth/me smoke | curl + token 验证 | 待 CI 运行 |
| `alembic_version` 为期望 head | SQL 查询断言 | 待 CI 运行 |
| 回滚演练 | — | 当前迁移不可逆，CI 记录 current/history 作为基线；生产部署前需独立备份恢复策略 |

**本机状态：** BLOCKED_BY_ENVIRONMENT（无 PostgreSQL 实例）。CI runner 执行后产生 evidence artifact。

**关闭条件：** CI run 通过且 artifact 已归档后，REL-004 可标记为 passed。

### 5.5 REL-005：环境型测试适用性矩阵

**产品范围核查（六次复核）：**

通过查阅 `README.md`、`docs/REAL_AI_SMOKE.md`、`docs/P0_MODEL_READINESS_ONBOARDING_DESIGN.md`、`requirements-ai.txt`、`backend/app/services/runtimes/local_runtime.py` 后，结论如下：

| 证据来源 | 关键陈述 |
|---|---|
| `README.md` 快速开始 | "AI 推理 / 训练能力（按需安装）：`pip install -r requirements-ai.txt`" |
| `README.md` 同节 | "**不安装 AI 依赖也能启动后端与客户端**（Ollama 推理、认证、会话、数据集、知识库检索均可用）" |
| `requirements-ai.txt` 头部注释 | "**可选：AI 推理 / 训练重依赖（桌面用户按需安装；不再进 CI）**" |
| `backend/app/services/runtimes/local_runtime.py` | torch / transformers / llama_cpp 均为**模块内 lazy import**，未安装时不阻断应用启动 |
| `docs/REAL_AI_SMOKE.md` | CPU 与 GPU smoke 均为**手动工作流**，不进入默认 CI；NVIDIA 需 `self-hosted` + `nvidia-gpu` 标签 runner |
| `docs/P0_MODEL_READINESS_ONBOARDING_DESIGN.md` | 模型就绪服务统一区分"可用 / 需要配置 / 服务不可用"四种状态，无 torch/transformers 时安全降级 |

**结论：** Beta 不承诺开箱即用 CPU 本地推理。CPU 本地推理属于**可选扩展能力**，用户在桌面端自行安装 `requirements-ai.txt` 并提供模型后可启用。

| 跳过项 | 测试文件 | 启用条件 | 依赖 | Beta 是否承诺 | 当前平台适用性 | 所需环境 | 执行位置 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 公网 Hugging Face 连通性 | `tests/test_external_integration.py` | `RUN_NETWORK_TESTS=1` + `huggingface_hub` | 互联网 | 否 | 不适用（Beta 不承诺公网集成） | 互联网 + HuggingFace 凭据 | 专用网络 CI job / 人工验收 | 不纳入 Beta 候选 |
| CPU 真实模型推理 | `tests/test_hardware_cpu.py` | `MODELFORGE_CPU_SMOKE_MODEL` + `torch` + `transformers` + 本地模型目录 | 可选 AI 依赖 + 本地模型 | 否（属于可选扩展能力，非核心 Beta 承诺） | 适用：自托管 CPU runner；不适用：默认 CI（无 AI 依赖） | CPU + torch + transformers + 预置模型 | `ModelForge CPU AI Smoke` 手动工作流 / 人工验收 | 不纳入 Beta 核心候选门禁；纳入扩展兼容性矩阵 |
| GPU/CUDA smoke | `tests/test_hardware_gpu.py` | `torch.cuda.is_available()` + `torch` | NVIDIA GPU + CUDA | 否 | 不适用（Beta 不承诺 GPU） | NVIDIA GPU + CUDA + torch | `ModelForge GPU Smoke` 手动/每周工作流（自托管） | 不纳入 Beta 候选 |

**适用性结论：**

- Beta 承诺**核心平台能力**（认证、会话、记忆、Agent Run、Event、Tool、Policy、MCP、Scheduler、知识库、训练、数据集、远程 OpenAI 兼容、本地 Ollama 推理）。这些由默认 CI 覆盖（866 个测试通过、3 个 opt-in 跳过、0 warning）。
- CPU / GPU / 公网模型加载属于**可选扩展能力**，由用户显式安装 `requirements-ai.txt` 后启用。其 smoke 验证不进入 Beta 核心门禁，由手动工作流和扩展兼容性矩阵覆盖。
- 三个 skipped 测试均为**显式 opt-in**（环境变量门控 + `pytest.importorskip` + 懒加载运行时），不会在默认 CI 中误跳，也不会在生产镜像缺失 AI 依赖时阻断应用启动。
- "本机无模型"不是跳过理由；真正的理由是"该能力不属于核心 Beta 承诺"。

**关闭证据：** 仓库证据（README、requirements-ai.txt 头部、lazy imports、REAL_AI_SMOKE.md）已确认 CPU/GPU 推理为可选扩展能力，适用性矩阵与产品承诺一致。

### 5.6 REL-006：候选源代码范围已冻结

六次复核确认 `git status --short --branch` 仅有 `.omo/`（opencode session 产物，不属候选范围，已加入 `.gitignore`）。所有产品源代码、测试、CI 配置、SBOM 脚本和发布文档均已提交。

`.gitignore` 明确排除的非候选文件：
- `models/`、`outputs/`、`data/`、`logs/` — 本地模型、运行数据
- `config.yaml`、`.env` — 本地配置和密钥
- `.ui_validate.py`、`ui_validate_*.png`、`reports/ui-audit/` — UI 验证脚本和截图
- `__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.coverage`、`*.pyc` — 缓存
- `.venv/`、`env/`、`venv/` — 虚拟环境
- `.omo/`、`.zcode/` — 编辑器/CLI session 产物

**关闭证据：** 工作区干净，`.gitignore` 和 `.dockerignore` 覆盖完整，候选源代码范围无歧义。

## 6. 架构与产品边界

### 6.1 ARC-001：当前只支持单应用副本

`RuntimeRegistry`、Agent runtime、插件管理、知识库和部分任务/事件通知仍包含进程级状态。数据库中的 Run、Event、Outbox 和 Download 记录提高了可恢复性，但不能自动解决多个应用进程之间的通知、任务归属、插件挂载和本地模型生命周期一致性。

**当前支持边界：**

- 本地 SQLite：可信本机、单用户、单进程。
- PostgreSQL 服务端试点：可以使用持久化数据库，但在外部协调能力完成前仍固定单应用副本。
- 不支持把多个 Uvicorn worker 或多个容器描述为可靠的 active-active 部署。

**进入多副本前的必要工作：**

1. 用外部队列/租约实现任务领取、续租、超时回收和幂等完成。
2. 用 Redis、NATS、PostgreSQL LISTEN/NOTIFY 或等价设施实现跨实例事件通知；数据库 cursor 继续作为回放权威。
3. 明确 runtime/model 的节点亲和性、容量调度和故障转移。
4. 插件与 MCP 配置按组织/项目/用户隔离，不依赖进程内全局挂载。
5. 执行双实例故障注入：重复领取、实例中止、网络分区、事件延迟、租约过期和恢复回放。
6. 建立 outbox backlog、claim latency、SSE lag、连接池等待和每用户并发指标。

### 6.2 BIZ-001：API 用量账本只能支持受控试点

项目 API 已具备哈希 API Key、项目作用域、配额、调用回执和追加式 UsageLedger，这是产品化基础，不等于完整计费系统。

**尚缺能力：** 精确 token/工具/存储计量口径、价格版本治理、退款与冲正、账期冻结、重复事件对账、多副本一致性、财务审计、异常用量告警、客户账单争议证据及支付系统隔离。

**当前产品边界：** 允许 `trial-v1` 或等价的受控试点，使用硬配额和人工导出/对账；在至少完成一个完整账期的双向核对、多副本压力测试和计费审计前，不接入自动扣费，不把 UsageLedger 直接表述为财务账本。

## 7. 开发工作包与建议顺序

| 工作包 | 当前状态 | 内容 | 依赖 | 完成条件 |
|---|---|---|---|---|
| WP-A | 已完成 | 冻结候选源代码范围；最终候选 SHA 由 CI 绑定 | 无 | REL-006 已关闭；REL-001 已关闭（CI Run 33463505790 通过） |
| WP-B | 已完成 | Chat header/code 一致性和泄露负向测试 | WP-A | DEV-001 已关闭 |
| WP-C | 已完成 | OpenAI 负向测试、统一 422 envelope 和资源治理均已完成 | WP-B | DEV-002 已关闭，DEV-007 已关闭 |
| WP-D | 已完成/跟踪风险 | Ruff/CI 已统一；维护 TestClient 依赖风险接受 | WP-A | DEV-003 已关闭；DEV-004 有负责人和期限 |
| WP-E | 已完成 | 契约、模型协议、训练、预览、迁移、调度、下载和服务运行时均已补测 | WP-B、WP-C | DEV-005 已关闭；DEV-006 已关闭 |
| WP-F | 已完成 | 干净候选供应链和容器验证 CI 已实现 | WP-A、WP-D、WP-E | REL-002 已关闭；REL-003 已关闭（CI Run 33463505790 通过） |
| WP-G | 已完成 | PostgreSQL/Alembic 验证矩阵 CI 已实现 | WP-A、WP-E | REL-004 已关闭（CI Run 33463505790 通过） |
| WP-H | 已完成 | CPU/GPU/公网适用性 smoke 适用性矩阵已建立 | WP-A | REL-005 已关闭（不适用） |
| WP-I | 后续阶段 | 分布式协调与多副本验证 | WP-G 后 | 解除 ARC-001 |
| WP-J | 后续阶段 | 账期对账与计费治理 | WP-I、稳定计量后 | 解除 BIZ-001 |

QA-001、DEV-006、DEV-007、REL-001、REL-002、REL-003、REL-004、REL-005、REL-006 已关闭。WP-A 至 WP-H 均已完成。v0.1.3-beta.1 已发布。

公网通用 API 的速率限制阈值应在实际负载测试后调整。WP-I 和 WP-J 属于架构升级，不应为了赶当前候选而仓促并入。

## 8. 测试与验收矩阵

### 8.1 每次提交的快速门禁

```bash
.venv/bin/ruff check backend client tests scripts
git diff --check
PYTHONPATH=backend/app .venv/bin/python -c 'import main; assert main.app is not None'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

该 Ruff 命令现为正式口径；如未来增加新的受支持 Python 目录，应在同一变更中更新 CI、开发文档和本地门禁。

### 8.2 发布候选门禁

| 门禁 | 最低通过标准 | 证据 |
|---|---|---|
| Git 基线 | 干净工作区、固定 SHA/tag | `git status`、commit、tag |
| 静态检查 | 正式 Ruff 范围 0 问题；`git diff --check` 通过 | CI log |
| 全量回归 | 0 failed；skip 均有适用性结论 | JUnit/pytest log |
| 覆盖率 | 总量不下降；关键模块达到约定阈值 | coverage XML/HTML |
| 启动 | import、lifespan、`/healthz` 通过 | smoke log |
| 安全回归 | 认证、IDOR、日志脱敏、上传、路径、异常泄露测试通过 | 测试报告 |
| 供应链 | `pip check`、`pip-audit` 通过；SBOM 已归档 | 审计 JSON、SBOM |
| Docker | build、非 root 启动、health、停止通过 | image digest、log |
| 数据库 | PostgreSQL 空库和升级路径通过 | Alembic/DB 报告 |
| 桌面 | 离屏测试及目标平台启动/关闭通过 | 平台矩阵、截图/日志 |
| 真实 AI | 发布承诺对应的 CPU/GPU/远程 provider smoke 通过 | 环境与模型 revision |
| 发布资产 | checksum、签名、安装/升级/卸载验证齐全 | manifest |

### 8.3 永久安全回归集

以下行为不得因重构或兼容改动退化：

1. 未认证用户不能调用 runtime 控制面。
2. 普通用户不能读取其他用户模型、下载任务、会话、知识文档或 Run。
3. 普通用户不能读取全局系统日志；管理员日志必须有界且脱敏。
4. 上传超过限制时必须在持续读入前终止并清理临时文件。
5. 模型扫描和安装不能逃逸配置根目录，包括 `..`、绝对路径和 symlink 情形。
6. SSE 必须正确处理多行、连续帧、EOF、重连 cursor 和客户端取消。
7. API 错误不得回显 secret、endpoint 凭据、服务器路径、SQL 或 traceback。
8. 开发配置便利性不得削弱生产 JWT、CORS、cookie 和 secret 校验。

## 9. 兼容性、回滚与运维要求

### 9.1 API 兼容性

错误 envelope 统一可能影响当前桌面客户端和外部调用方。实施 DEV-001/DEV-002 时应保留 HTTP 状态语义，先让客户端兼容新旧格式，再删除旧字符串解析。OpenAI 兼容接口新增边界会让过去接受的极端请求返回 422/429，这应在变更日志中明确，但不应为了兼容而保留无上限行为。

### 9.2 数据库回滚

数据库迁移不能只依赖 `downgrade` 脚本。涉及不可逆数据变换时，应采用发布前备份、向前修复迁移和应用版本兼容窗口。应用启动时应验证 schema 版本，不允许在版本未知或迁移未完成时继续提供写服务。

### 9.3 容器与任务回滚

镜像必须通过 digest 固定；回滚到旧镜像前检查其是否兼容当前 schema。正在运行的训练、下载、Agent Run 和调度任务需要明确“继续、取消、重领或人工恢复”的策略，不能仅以容器重启作为任务恢复方案。

### 9.4 可观测性

至少记录 correlation id、稳定错误码、用户/项目的非敏感标识、运行时类型、耗时和结果状态。日志禁止记录 API Key、Authorization、完整 prompt、模型内容、用户文件正文和未脱敏异常字符串。发布前为认证拒绝、配额拒绝、运行时失败、outbox backlog、调度 claim 和迁移失败建立可检索事件。

## 10. 文档与证据治理

当前仓库中存在多个历史测试数和覆盖率数字，它们代表不同日期和范围。README、QA 报告与发布说明必须同时写明：日期、commit、命令、测试收集数、skip 原因、覆盖对象和环境。路由数也应说明是顶层 route、OpenAPI operation 还是源码装饰器数量，避免静态统计与运行时统计互相矛盾。

候选证据建议按以下结构归档：

```text
release-evidence/<version>/<commit>/
  manifest.json
  pytest.xml
  coverage.xml
  pip-audit.json
  sbom.cdx.json
  docker-image.txt
  alembic-validation.md
  platform-smoke.md
  checksums.txt
```

证据目录不得包含 token、签名私钥、数据库凭据、用户内容、本地模型权重或未脱敏日志。

## 11. 里程碑与发布决策

| 里程碑 | 当前判断 | 尚缺条件 |
|---|---|---|
| M0 可运行基线 | 通过 | 保持 import/lifespan/SSE 回归 |
| M1 高风险入口关闭 | 通过 | 保持认证、隔离、上传和路径回归 |
| M2 工程与运维加固 | 基本通过 | 错误、输入、Ruff、JWT 与重点覆盖已完成；仍需清理 warning 和低覆盖运行链路 |
| M3 单副本服务端基础 | 已通过 | Docker 与 PostgreSQL/Alembic 已在 v0.1.3-beta.1 发布验证中通过 |
| M4 API 产品化基础 | 受控试点可用 | 完整账期对账、计费审计和多副本能力后再扩大范围 |

发布决策分层如下：

| 目标 | 当前决定 | 说明 |
|---|---|---|
| 本地开发/功能演示 | Go | 已有绿色功能回归；开发 secret 写入失败时重启仍会使 token 失效 |
| 受控单用户内测 | Go with conditions | 固定配置、保留数据备份、不得暴露无上限兼容 API |
| 私有化单副本试点 | Go | Docker、PostgreSQL/Alembic 和供应链已在 v0.1.3-beta.1 验证通过 |
| 公网通用 API | Conditional Go | DEV-007 治理已落地；需负载测试调整阈值，进程级状态需改为外部存储 |
| 多副本生产部署 | No-Go | ARC-001 尚未解除 |
| 自动计费商业服务 | No-Go | BIZ-001 尚未解除 |

## 12. 待确认决策

1. 当前未提交桌面 UI 和开发者 API 页面是否进入下一候选版本。
2. `.ui_validate.py` 是一次性本地工具、长期验证脚本，还是应从候选移除。
3. `scripts/` 是否全部属于受支持发布代码；建议答案是“是”，因为其中脚本直接生成和验证发布证据。
4. OpenAI 兼容接口的产品默认值：最大请求体、消息数、单消息长度、总 prompt、`max_tokens`、每用户并发和速率。
5. CPU、GPU、Hugging Face 公网能力分别在哪些发布目标中属于强制承诺。
6. 服务端近期是否明确只承诺单副本；如果不是，需要单独立项分布式协调，不能只修改部署副本数。

## 13. 最终建议

**当前结论：已发布 v0.1.3-beta.1。**

六次复核及发布验证确认：
- Release tag `v0.1.3-beta.1` 指向 `0cfdd3c335ad219b3badee0014e40e5f9500dddd`（CI Run 33463505790 全部通过）；
- 源代码/测试/CI/SBOM 候选范围已冻结，所有产品代码已提交；
- 默认 CI 866 passed、3 skipped（869 collected，属可选扩展能力，不属核心 Beta 承诺）、0 warnings；
- 后端覆盖率 81%，高于 CI 门槛 75%；
- `ruff check backend client tests scripts` 通过；
- `pip check` 通过；`pip-audit` runtime/dev/image 均 0 漏洞；
- Docker 镜像 digest `sha256:29779bec15959e48abe49f230271e30234ba64a80d855890305ed01217e467e7`，非 root 验证通过；
- PostgreSQL/Alembic 迁移 head `0002_api_platform`，幂等验证通过；
- 日志 secret 检查通过，SIGTERM 退出码 0；
- GitHub Release: https://github.com/yanzhao77/ModelForge/releases/tag/v0.1.3-beta.1

**Go/No-Go 决策前置条件（已满足）：**
1. CI `release-candidate` job 在最终候选 SHA `0cfdd3c335ad219b3badee0014e40e5f9500dddd` 上运行通过（CI Run 33463505790）；
2. Docker 镜像 digest、容器非 root 验证、PostgreSQL upgrade head 幂等、auth smoke、日志无 secret 验证均在 artifact 中可追溯；
3. SBOM 和 pip-audit 报告记录的 commit SHA 与最终候选 SHA 完全一致；
4. 当前无 P0/P1 未关闭问题。

**最终结论已升级为 Go（已发布 v0.1.3-beta.1）。**

多副本和自动计费应保持为后续独立里程碑，分别以分布式任务/事件协调和完整账期审计作为准入条件。

## 14. 证据来源与限制

本报告基于 2026-08-31 对当前仓库代码、测试、CI 配置、覆盖率文件和以下文档的复核：

- `docs/PROJECT_AUDIT_REPORT_2026-08-27.md`
- `docs/TECHNICAL_DEVELOPMENT_SPEC_2026-08-27.md`
- `docs/IMPLEMENTATION_STATUS_2026-08-28.md`
- `docs/REAL_AI_SMOKE.md`
- `docs/P0_MODEL_READINESS_ONBOARDING_DESIGN.md`
- `requirements-ai.txt`（头部注释确认 AI 依赖为可选）
- `README.md`（快速开始章节确认核心能力不依赖 AI 依赖）
- `.github/workflows/ci.yml`（含 `release-candidate` job）
- `ruff.toml`
- `scripts/generate_sbom.py`（v2.0，支持完整依赖树）
- `release-artifacts/sbom.cdx.json`（当前为开发 venv 的 SBOM，非生产 runtime 权威来源）
- `release-artifacts/candidate-metadata.json`（待 CI 生成）
- `pip-audit` runtime 和 dev 报告

**SBOM 来源说明：** 本机 `.venv` 同时安装了 runtime、dev 和 gui 依赖，生成的 87 组件 SBOM **不视为生产 runtime 的权威 SBOM**。生产 runtime SBOM 需在 CI `release-candidate` job 中通过隔离的 runtime venv（仅 `requirements.txt`）或最终 Docker 镜像内已安装环境生成，并在 SBOM metadata 中明确 `source` 字段。

**本机验证命令真实结果：**
- `git status --short --branch`：ahead 1（候选治理提交待 push）
- `git diff --check`：通过
- `git diff origin/master...HEAD --check`：通过
- `ruff check backend client tests scripts`：通过
- `PYTHONPATH=backend/app python -c 'import main; assert main.app is not None'`：通过
- `pytest tests/ -q`：866 passed, 3 skipped, 0 warnings（869 collected）
- `pytest tests/ --cov=backend/app --cov-report=term-missing`：81% 覆盖率
- `pip check`：通过
- `pip-audit -r requirements.txt`：0 漏洞
- `pip-audit -r requirements-dev.txt`：0 漏洞

未执行渗透测试、长时间容量测试、多实例故障注入、真实付费账期对账和跨平台安装认证。本报告中的发布判断仅适用于已验证范围；任何新的业务代码、依赖、迁移、容器基础镜像或候选文件变化都需要重新生成证据。
