# ModelForge 项目详细审核报告

**审核日期：** 2026-08-27  
**审核基线：** `master`，HEAD `fcc08b74930531156317061c38bcbedbe5c8fa45`  
**工作区：** 非干净；审核观察到未提交的后端、桌面端和文档改动，未修改或回滚任何既有改动。  
**范围：** `backend/app/`、`client/pyside6/`、`tests/`、CI、Docker/发布脚本、README 与相关设计文档。  
**性质：** 代码与工程交付审核，不等同于渗透测试、性能认证或正式发布批准。

## 1. 执行摘要

ModelForge 已形成 FastAPI 后端 + PySide6 桌面客户端 + 本地优先 Agent Runtime 的完整骨架，功能覆盖认证、会话、模型、知识库、训练、Agent Run、事件流、工具策略、MCP、调度和插件。代码按 API、服务、运行时、仓储和客户端分层，数据库也有 WAL、追加式迁移、事件序列和 outbox 设计。

当前基线**不具备可交付状态**。最严重的问题是应用无法导入启动：`runtime_diagnostics.py` 导入了不存在的 `AgentEvent` 类，导致 `main` 导入失败，所有依赖 FastAPI 应用的测试在收集阶段中断。另有独立的客户端 SSE 解析回归。安全方面还存在未认证 runtime 控制面、模型详情跨用户读取、日志/下载任务没有用户隔离，以及上传在限额校验前把完整文件读入内存等问题。

**总体结论：No-Go（阻断发布）。** 先修复 P0/P1 并恢复全量测试，再做性能、真实模型和跨平台发布验证。

## 2. 评分与结论

| 维度 | 评分 | 结论 |
|---|---:|---|
| 架构与模块边界 | 7/10 | 分层方向正确，运行时能力完整，但全局单例和遗留 Agent 链路增加耦合。 |
| 功能完整度 | 7/10 | 功能面广，许多能力依赖本机服务或可选依赖，部分文档是计划/模板而非交付证据。 |
| 安全与租户隔离 | 4/10 | JWT/CSRF/密钥加密基础较好，但存在未认证控制面和多处隔离缺陷。 |
| 测试与质量门禁 | 3/10 | 当前 `main` 无法导入；测试、lint、依赖审计没有形成绿色证据。 |
| 可运维性 | 5/10 | 有迁移、outbox、诊断和审计设计，但诊断实现自身存在类名和状态值错误。 |
| 发布准备度 | 2/10 | CI、Docker、桌面打包脚本存在，但当前基线无法通过启动和测试门禁。 |

## 3. 架构与实现概况

### 3.1 已确认结构

- 后端位于 `backend/app`，`main.py` 负责 FastAPI 路由和 lifespan 接线。
- 运行时主链为 API → `AgentRuntime` → `ExecutionEngine` → Ports/Repositories/Adapters。
- 数据库使用 SQLAlchemy + SQLite，启用 WAL、busy timeout、显式迁移和事务 outbox。
- 桌面端通过 `ModelForgeClient` 调 REST/SSE，网络请求主要通过 Qt Worker 移出 GUI 线程。
- 安全设计包含 JWT、PBKDF2 密码哈希、HttpOnly Cookie/CSRF、Fernet 加密远程 API Key、工具 Policy 和确认门。
- 静态统计：后端 128 个 Python 文件约 15,601 行；桌面端 52 个文件约 7,367 行；测试 55 个文件约 6,922 行；约 397 个测试函数；API 文件静态统计 144 个路由装饰器。

### 3.2 主要优点

1. 运行时执行、事件、工具、策略、MCP、调度均有独立模块，API 大多不直接操作仓储。
2. 会话、记忆、数据集、知识文档、Agent Run 等多数查询带 `user_id` 条件，远程密钥不通过公开 DTO 返回。
3. Agent Run 有状态机、取消令牌、事件序列、SSE 恢复、租约和终态幂等字段；Task Outbox 具备重试和租约字段。
4. 生产环境校验 JWT/CORS，桌面发布脚本生成 checksum，发布决策脚本要求固定 SHA 和门禁证据。
5. `ApiWorker`/`AsyncApiMixin` 对请求生命周期、过期结果和关闭处理有清晰边界。

## 4. 阻断问题（P0）

### P0-1 应用启动导入失败

**证据：** `backend/app/services/runtime_diagnostics.py:7` 导入 `models.records.AgentEvent`，实际模型类名是 `AgentEventRecord`（`backend/app/models/records.py:486`）。该服务被 `backend/app/api/workspaces.py` 导入，最终阻断 `backend/app/main.py`。

**复现：**

```text
$ PYTHONPATH=backend/app .venv/bin/python -c 'import main'
ImportError: cannot import name 'AgentEvent' from 'models.records'
```

**影响：** Uvicorn、FastAPI TestClient、API/桌面集成测试和 Docker healthcheck 均不能证明服务可用。

**整改：** 统一使用 `AgentEventRecord` 或提供有测试覆盖的显式别名；新增最小 `import main`、`/healthz` 和 lifespan smoke gate，并在 CI 最早阶段执行。

### P0-2 `/api/v1/runtime` 控制面无认证

**证据：** `backend/app/api/runtime.py:44-68` 的 `runtime_start`、`runtime_chat`、`runtime_stop`、`runtime_status` 没有 `Depends(get_current_user)`；`main.py:92-109` 将该 router 暴露到 `/api/v1`。Docker 监听 `0.0.0.0:8000`。

**影响：** 端口可达时，未登录调用方即可加载/卸载模型并发起推理，形成高成本资源滥用和模型控制入口。

**整改：** 全部 runtime 路由强制认证，将模型/provider 解析绑定到当前用户，增加高成本操作的权限、速率、并发和审计控制；补充未认证、跨用户和过量请求测试。

## 5. 高风险问题（P1）

### P1-1 模型详情存在跨用户读取（IDOR）

`backend/app/api/models.py:161-169` 调用 `_manager(db).info(model_id)`，而 `backend/app/services/model_manager.py:55-57` 只按主键查询，没有 `user_id` 条件。已登录用户可猜测 ID 读取其他用户的名称、provider、路径、大小和状态。应将 `info(model_id, user_id)` 设计为必传用户上下文，仅允许当前用户或明确的全局模型，并增加双用户回归测试。

### P1-2 系统日志接口返回未脱敏的全局日志

`backend/app/api/system.py:41-50` 对任意已认证用户读取 `logs/modelforge.log`，直接返回最多 5,000 行，没有管理员限制，也未调用 `redact_text`/`redact_data`。日志可能包含异常、文件路径、请求内容、上游错误或凭据形态，并会暴露其他用户操作。应改为管理员专属、分页、脱敏的结构化摘要，并记录日志读取审计。

### P1-3 下载任务为进程级、无用户归属且不持久化

`backend/app/services/downloader.py:34-45,74-78` 使用全局 `_tasks` 字典；`backend/app/api/models.py:92-109` 创建和查询均不记录或校验 `user.id`。用户可用任务 ID读取其他用户的仓库、目标路径和错误；进程重启后任务全部丢失。应增加持久化 DownloadTask、`user_id`、可恢复状态机和稳定错误码。

### P1-4 上传接口在限额校验前读取完整文件

数据集接口 `backend/app/api/datasets.py:15-22` 先 `file.file.read()`，随后才在 `dataset_service.py:97-100` 检查 `max_dataset_size`；知识库接口 `backend/app/api/knowledge.py:57-60` 先 `await file.read()`，无请求体流式上限。认证用户可用超大 multipart 请求制造内存 DoS。应在代理/ASGI 设置 body limit，应用按块读入并超限即中止，同时控制用户磁盘配额。

### P1-5 模型扫描允许任意服务器路径

`backend/app/api/models.py:61-67` 将用户输入的 `req.path` 传给 `ModelManager.scan`；`model_manager.py:27` 对任意路径 `resolve()` 后枚举目录。安装接口也接受任意 `path`（`api/models.py:70-78`）。共享部署中可枚举服务器文件系统并持久化路径信息。应限制到配置的模型根目录/用户子目录，校验 containment、符号链接和 `../`，安装只接受已登记资产。

## 6. 中风险问题（P2）

### P2-1 运行时诊断实现自身不可靠

除 P0 类名错误外，`runtime_diagnostics.py:24` 使用小写 `queued/running/awaiting_approval/cancelling`，而 `AgentRun.status` 与运行时状态使用大写值（如 `PENDING`、`RUNNING`）。因此 `active_count` 很可能始终为 0。应集中复用 `RunStatus` 枚举，并用诊断契约测试固定映射。

### P2-2 客户端 Agent Run SSE 解析依赖空行 flush

`client/pyside6/api_client/client.py:485-505` 只在收到空行时输出事件；`tests/test_agent_client_phase8.py:76-85` 提供连续 `data:` 行而没有空行，结果为空，复现为 4 passed / 1 failed。应支持标准事件边界、EOF flush、多行 data 和断线恢复，并增加真实服务器流测试。

### P2-3 错误信息边界不统一

`backend/app/api/models.py:86-89` 把 Hugging Face 搜索异常直接插入响应；`backend/app/api/chat.py:79-83` 对普通聊天异常返回 `str(exc)`。可能泄露内部路径、URL、上游响应或配置。应统一稳定错误码 + correlation id，详细异常仅写入脱敏日志。

### P2-4 OpenAI/旧 runtime 输入没有统一上限

`backend/app/api/openai_api.py:17-28` 的消息列表和内容没有长度约束，`backend/app/api/runtime.py:9-16` 也没有消息数/内容长度限制。应复用统一消息模型，增加总字节/token 预算、超时和每用户速率限制。

### P2-5 进程级单例限制多租户和水平扩展

`AgentRuntime`、`PluginManager`、`Downloader`、`RuntimeRegistry` 等使用进程级状态。该模式适合本机单用户，但在多用户或多 worker 部署中会产生状态不一致、任务不可恢复和插件作用域互相影响。应明确部署边界，或把可见状态迁移到持久化存储并引入用户/租户 scope。

### P2-6 开发环境重启会使 JWT 全部失效

`backend/app/core/config.py:173-175` 在 development 且 secret 为空/默认值时每次启动随机生成密钥。安全上优于可预测密钥，但会使重启后全部 token 失效。应在开发文档中明确，或使用仅限本地且明确生成/存储的开发密钥；生产校验应保留。

## 7. 测试、CI 与文档证据

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `.venv/bin/python -m pytest -q` | 失败：9 个模块在收集阶段因 `AgentEvent` 导入错误中断。 |
| 目标测试 | `.venv/bin/python -m pytest ...` | 客户端 SSE 测试失败；停止点为 4 passed / 1 failed。 |
| 静态检查 | `.venv/bin/ruff check backend client tests` | 失败；包含 import 排序、未使用变量等错误，涉及 `api/agent.py`、`api/models.py`、`api/tasks.py`、`api/workspaces.py`。 |
| 字节码编译 | `.venv/bin/python -m compileall -q backend client` | 通过；仅说明语法可编译，不能证明导入或运行正确。 |
| 依赖审计 | `.venv/bin/python -m pip_audit -r requirements.txt` | 未形成有效结果；工具在临时环境升级 pip/wheel/setuptools 时失败。 |
| 启动烟雾 | `PYTHONPATH=backend/app .venv/bin/python -c 'import main'` | 失败，复现 P0-1。 |

仓库约有 397 个测试函数，测试投入较大，但当前错误发生在收集阶段，API、Cookie、模型就绪、任务中心、训练/知识库等关键套件都无法执行。CI 串联了 lint、pip-audit、全量测试和 Docker healthcheck，却缺少更早的 import smoke gate，也没有配置明确覆盖率阈值（只上传报告）。

文档存在漂移：README 声称 398 个测试通过、92 条路由；当前基线无法验证“通过”，静态路由装饰器计数为 144，至少需要明确统计口径。`docs/` 中大量文件是计划、模板或历史报告，不能替代当前 commit 的测试、构建、签名和安装证据。

## 8. 整改路线

### 阶段 0：恢复可运行性（当天）

1. 修复 `AgentEvent`/`AgentEventRecord` 类名错误。
2. 增加 `import main`、`/healthz`、lifespan 启停 smoke test。
3. 修复客户端 SSE EOF/事件边界解析，恢复目标测试。
4. 运行 ruff 并处理确定性的 import/未使用变量问题，人工检查行为变更。

### 阶段 1：关闭安全阻断（1-3 天）

1. 给 `/api/v1/runtime/*` 加认证、用户模型授权、速率和并发限制。
2. 修复模型详情 IDOR，审计所有 `get/info/status/log/download` 路径的用户过滤。
3. 日志改为管理员专属、分页、脱敏摘要；下载任务增加 `user_id`、持久化和恢复。
4. 上传、扫描、安装增加 body/路径/磁盘配额和 containment 校验。

### 阶段 2：质量与运维加固（3-7 天）

1. 统一错误码、correlation id 和异常日志脱敏。
2. 统一 RunStatus 枚举与诊断指标，增加诊断契约测试。
3. 为认证、聊天、OpenAI、上传和下载增加速率限制与审计。
4. CI 增加 import smoke、覆盖率阈值和可重复 pip-audit；明确单用户桌面与多用户服务器支持矩阵。

### 阶段 3：发布前验证

在前两阶段完成后，重跑干净环境的 pytest、ruff、pip-audit、Docker、Ollama/远程 provider、CPU/GPU smoke、桌面离屏及三平台安装/卸载；所有 SBOM、checksum、签名和证据绑定同一固定 commit，并更新 README 的测试数、路由数、版本和能力状态。

## 9. 验收标准

- `import main`、健康检查和 lifespan 启停成功。
- 全量 pytest 通过，无关键套件收集错误；ruff 通过；pip-audit 有可追溯结果。
- 未认证请求不能调用 runtime 控制面；跨用户不能读取模型详情、日志、下载任务、Agent Run 或文件路径。
- 超限上传不会把完整请求体读入内存；扫描无法越出允许根目录。
- SSE 覆盖标准空行、EOF、多行 data、断线恢复和 resync 场景。
- Docker、桌面离屏、真实模型和安装验证绑定同一固定 commit，并留存证据。

## 10. 最终审计意见

ModelForge 的技术方向和模块基础值得继续投入，尤其是 Agent Runtime、事件持久化、策略门、审计和桌面异步边界已有较好雏形。但“功能面广”不能抵消“应用无法启动”和“控制面存在未认证入口”这两项基本交付风险。

**最终决定：No-Go。** 修复 P0-1/P0-2 和全部 P1 项、恢复绿色 CI 后，才适合进入下一轮性能和跨平台发布审核。
