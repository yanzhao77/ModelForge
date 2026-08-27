# ModelForge 技术开发规格与整改执行方案

**文档版本：** v1.0

**制定日期：** 2026-08-27

**适用基线：** `master` @ `fcc08b74930531156317061c38bcbedbe5c8fa45`

**文档性质：** 发布整改、平台演进与 API 产品化的实施规格

**当前发布结论：** **No-Go**。在本文定义的 P0 与 P1 验收条件满足前，不得发布为稳定版，也不得将其用于面向外部客户的付费 Agent API。

> 本文将项目审核中发现的可用性、安全、租户隔离、测试门禁和产品化缺口转换为可拆分、可编码、可验证、可回滚的开发工作包。它不是功能愿望清单；每项工作都必须关联代码变更、测试证据与发布门禁。

## 1. 背景、目标与边界

ModelForge 已具备 FastAPI 后端、PySide6 桌面客户端和本地优先 Agent Runtime 的完整骨架。核心运行时具有 Agent Run、事件序列、工具注册、策略门、人工审批、MCP、调度、插件和多 Agent 护栏；持久化层已有 SQLite WAL、租约、状态版本和事务外箱等机制。[1] [2] 这些能力是后续技术投资的核心资产。

当前问题不在于功能数量不足，而在于**发布级可靠性与权限边界未闭环**：应用入口存在导入错误；传统 runtime 控制面可匿名调用；默认文件读取无受限根目录；模型、日志、下载和路径扫描存在跨用户或主机资源暴露风险；测试和静态检查未形成绿色证据。[1] [3] 因此，开发顺序必须从“继续增加页面或新能力”调整为“先恢复可验证性，再关闭权限与隔离漏洞，最后把运行时收敛为可运营 API”。

| 本期目标 | 成功定义 | 明确不在本期范围 |
|---|---|---|
| 恢复稳定启动与回归验证 | `main` 能导入、生命周期可启停、全量测试可收集并通过 | 新增模型类型或新的桌面工作区 |
| 建立纵深安全边界 | 未认证、跨用户、路径逃逸、敏感文件读取、超限上传均被拒绝且有测试 | 把本地单机版直接改造成多区域公有云服务 |
| 形成可发布工程门禁 | lint、依赖审计、测试、覆盖率、镜像与桌面验证均绑定固定提交 | 仅以 README 徽章代替发布证据 |
| 为 API 产品化铺路 | 明确 API Key、计量、配额、审计与租户模型的目标设计 | 在计量和配额不存在时接入支付 |

## 2. 实施原则与架构约束

### 2.1 基线原则

所有修复必须遵循**最小权限、显式租户上下文、默认拒绝、可观测失败、契约先行**五项原则。任何 API、服务、仓储或工具只要读取、写入、执行、下载或返回用户数据，都必须携带明确的 `user_id` 或后续的 `tenant_id/project_id` 上下文；不能再依赖全局单例、可猜测 ID 或隐式当前用户。

对于 Agent Runtime，策略必须是实际执行路径的权威门，而不是 UI 提示或工具元数据。每项工具调用均必须在执行前获得策略判定，且访问范围应由运行上下文传递。工具声明的权限仅是输入，服务端仍须验证路径、网络目标、参数上限和用户授权。

### 2.2 部署支持矩阵

在本轮整改完成前，项目需要明确区分两种部署档位，避免单机实现被误用为多租户服务。

| 部署档位 | 定义 | 允许能力 | 禁止或必须改造的能力 |
|---|---|---|---|
| 本地单用户档 | 一个可信操作者，在一台设备上使用本地 SQLite 与本地模型 | 模型管理、桌面端、单进程 Agent、文件工具（限用户工作目录） | 多用户共享、外网裸露端口、进程级任务跨账户可见 |
| 私有化/服务端档 | 多用户或网络可达环境，独立持久化与身份边界 | 认证 API、审计、远程 Provider、持久化任务 | SQLite 主库、匿名 runtime、任意主机路径、无配额的高成本请求 |

### 2.3 目标控制链路

短期内继续保留现有 REST、SSE 和桌面端，但新增能力必须围绕下述控制链路设计。桌面端是本地配置、调试与运维界面；对外价值中心应逐步迁移到受认证、可度量的 API。

```mermaid
flowchart LR
    A[客户端或 SDK] --> B[身份认证 / API Key]
    B --> C[租户、项目、作用域校验]
    C --> D[配额、并发与幂等检查]
    D --> E[Agent Run 创建]
    E --> F[策略门与审批]
    F --> G[工具 / 模型 / MCP 执行]
    G --> H[事件、结果与 SSE]
    H --> I[用量账本与审计]
    I --> J[监控、账单与支持]
```

## 3. 工作分解结构与优先级

### 3.1 里程碑总览

| 里程碑 | 目标周期 | 核心产出 | 发布决策 |
|---|---:|---|---|
| M0：恢复可验证基线 | 第 0—2 天 | 可导入服务、已修复 SSE、绿色收集与静态检查 | 仅允许继续内测 |
| M1：关闭高风险入口 | 第 3—7 天 | runtime 认证、受限文件系统、模型/日志/下载隔离、流式上传限制 | 可进行受控私有内测 |
| M2：工程与运维加固 | 第 2—3 周 | 统一错误契约、诊断可信化、CI 门禁、可观测性与发布证据 | 候选 beta 评审 |
| M3：服务端基础设施分离 | 第 4—5 周 | PostgreSQL/Alembic 路径、可替换调度/事件后端、部署矩阵 | 私有化部署评审 |
| M4：API 产品化控制面 | 第 6—8 周 | API Key、项目作用域、计量账本、配额与运营审计 | 付费 API 试点评审 |

### 3.2 问题到工作包映射

| 工作包 | 优先级 | 对应风险 | 完成标志 |
|---|---|---|---|
| WP-00：启动与契约修复 | P0 | `AgentEvent` 导入错误、状态枚举漂移、SSE EOF 丢事件 | 应用能导入；诊断统计正确；SSE 单元/集成测试通过 |
| WP-01：runtime 与工具最小权限 | P0 | 匿名 runtime、任意文件读取、路径逃逸 | 控制面认证；文件工具默认拒绝且根目录受限 |
| WP-02：资源归属与租户隔离 | P1 | 模型 IDOR、全局日志、下载任务无归属 | 每个资源按用户过滤；管理员操作可审计 |
| WP-03：输入、上传与错误边界 | P1 | 内存 DoS、任意路径扫描、异常泄露、无上限输入 | 流式限额、路径 containment、稳定错误码 |
| WP-04：质量门禁与发布证据 | P1 | 测试/lint 失绿、无覆盖率门槛、不可复现依赖 | CI 全绿、阈值生效、发布资产可追溯 |
| WP-05：服务端可扩展性 | P2 | SQLite/进程单例的多实例限制 | 可选择 PostgreSQL 与外部任务/事件后端 |
| WP-06：API 商业控制面 | P3 | 无客户 API Key、配额、账本与计费闭环 | 认证—调用—计量—配额—账单链路可用 |

## 4. WP-00：启动、状态与流式协议修复

### 4.1 目标与范围

本工作包修复一切会导致应用不能启动、测试不能收集或状态诊断不可信的问题。不得将“字节码编译通过”作为运行可用的替代证据；只有真实导入、FastAPI 生命周期、受认证最小请求和 SSE 流可以证明应用入口可用。

### 4.2 实施任务

| 编号 | 修改位置 | 技术要求 | 必须新增的测试 |
|---|---|---|---|
| T00-01 | `services/runtime_diagnostics.py` | 将不存在的 `AgentEvent` ORM 引用改为 `AgentEventRecord`；不引入静默别名掩盖模型命名错误。 | `import main` 冒烟测试；`/workspaces/runtime-diagnostics` 管理员测试。 |
| T00-02 | `runtime_diagnostics.py`、`runtime/types.py` | 诊断逻辑必须复用 `RunStatus` 或单一状态映射；禁止手写小写 `queued/running/awaiting_approval`。 | 每个 Run 状态对应的 active/terminal 计数契约测试。 |
| T00-03 | `client/pyside6/api_client/client.py` | SSE 解析器必须在空行、EOF、连续 data 行、多行 data、注释心跳、断线恢复时正确 flush。 | 标准流、无空行 EOF、多行 payload、after_sequence 重连的测试矩阵。 |
| T00-04 | `tests/`、`.github/workflows/ci.yml` | 在 Ruff 与完整 pytest 之前执行 `PYTHONPATH=backend/app python -c 'import main'`；随后以 TestClient 触发生命周期与 `/healthz`。 | 导入、lifespan 启停、`/healthz`、路由注册 smoke。 |
| T00-05 | `tests/test_scheduler_phase9.py` 与 Scheduler 实现 | 明确 one-shot 任务成功后的终态是 `completed`；测试不能继续期待 `scheduled`。 | `scheduled → running → completed/failed/cancelled` 状态机测试。 |

### 4.3 关键实现约束

运行时状态只能由统一枚举或常量模块定义。诊断、SSE、API DTO、数据库查询和桌面展示都应从同一映射派生；如果为了兼容存量数据需要接受历史字符串，也必须在一处执行规范化并记录迁移指标。新模块不得直接猜测 ORM 类名或状态值。

SSE 客户端解析应使用有限状态机：收到字段行时累积事件；收到空行时提交；流 EOF 时若缓冲区有完整/可解析事件则提交；同一事件的多个 `data:` 行按协议以换行拼接。重连时应持久化最后已消费的 sequence，且重复事件必须由 sequence 去重。

### 4.4 验收条件

| 检查 | 命令或场景 | 通过条件 |
|---|---|---|
| 导入 | `PYTHONPATH=backend/app python -c 'import main'` | 退出码为 0。 |
| 生命周期 | FastAPI TestClient 或 lifespan test | 启动/关闭无未处理异常与未回收任务。 |
| 健康检查 | `GET /healthz` | 返回 200 和 `{"status":"ok"}`。 |
| SSE | 服务端和桌面客户端端到端流 | 空行、EOF、多行与重连场景全部通过。 |
| 静态检查 | `ruff check backend/app client/pyside6 tests` | 0 项错误。 |

## 5. WP-01：runtime、文件与工具的最小权限闭环

### 5.1 认证 runtime 控制面

现有 `/api/v1/runtime/*` 路由不能继续作为匿名控制面。所有启动、停止、推理、状态查询接口必须依赖当前用户，并将模型、Provider 与会话解析绑定到该用户。涉及进程级资源或共享 runtime 状态的接口还必须要求显式运行时管理员角色，而不能只凭普通登录态访问。[1]

| API 类型 | 最低认证要求 | 额外控制 | 审计事件 |
|---|---|---|---|
| 普通 Agent Run | 当前用户或项目 API Key | 用户级并发、输入预算、幂等键 | run.create、run.cancel、run.approve、run.reject |
| 模型加载/停止 | 当前用户且资源归属匹配 | 模型配额与速率限制 | runtime.model.start/stop |
| 进程级 runtime 状态 | 显式 runtime admin | 只读优先；变更需要确认 | runtime.admin.read/mutate |
| Provider/MCP 配置 | 当前用户且对象归属匹配 | 密钥不回显；高风险配置可要求重新认证 | provider/mcp.create/update/delete |

实施时应在 `api/runtime.py` 的 router 或每个端点显式注入 `Depends(get_current_user)`，再将 `user.id` 传递到服务层。禁止只在前端隐藏入口或只在 API 外层依赖可选用户。所有服务方法应将 `user_id` 设为必传参数，避免再出现“省略参数即读取全局资源”的调用路径。

### 5.2 文件系统工具与模型路径 containment

`filesystem.read` 及代码搜索、模型扫描、模型安装、数据上传落盘等能力必须统一采用受限路径策略。策略层的 `filesystem_access` 当前必须被实际执行；文件读取默认为关闭，并与 `READ` 权限一起进入 Policy 决策。[2] [3]

建议新增 `core/resource_access.py` 或等价的集中模块，提供以下纯函数和服务级接口：

```text
validate_path(user_id, candidate_path, operation, allowed_roots) -> ResolvedAccess
resolve_user_root(user_id, resource_type) -> Path
is_sensitive_path(resolved_path) -> bool
redact_file_content(text, classification) -> str
```

| 防护点 | 实施规则 | 拒绝示例 |
|---|---|---|
| 默认能力 | `Policy.filesystem_access=False`；读取与写入均显式放行 | 未配置文件能力的 Agent 调用 `filesystem.read`。 |
| 允许根目录 | 每个用户、项目或 Run 仅可访问显式 `allowed_roots` | `/etc/passwd`、仓库外路径、其他用户工作区。 |
| 真实路径验证 | `resolve(strict=True)` 后用 `is_relative_to(allowed_root)` 校验 | `../`、软链接逃逸、挂载点逃逸。 |
| 文件类型与大小 | 只允许受支持的常规文件；拒绝设备、管道、套接字；限制大小和读取字节数 | `/proc/*`、FIFO、超大日志、二进制核心文件。 |
| 敏感内容 | 默认拒绝 `.env`、密钥、SSH、凭据目录；结果再经脱敏 | `.remote_provider_fernet.key`、私钥、Token 文件。 |
| 人工确认 | 跨目录、高敏路径、宽范围搜索必须进入 `WAITING_HUMAN` | 用户未确认的目录扫描或批量读取。 |

文件工具本身不得用“错误字符串”替代授权失败。应抛出或返回稳定的领域错误，例如 `RESOURCE_OUTSIDE_ALLOWED_ROOT`、`SENSITIVE_RESOURCE_DENIED`、`FILE_TOO_LARGE`；API 层再转换为统一 Problem Details 响应并写入审计。

### 5.3 安全测试矩阵

| 测试类别 | 核心断言 |
|---|---|
| 未授权 | 无 Token 调用全部 runtime 变更端点返回 401；普通用户调用管理员端点返回 403。 |
| 路径遍历 | `../`、绝对路径、URL 编码路径、软链接、大小写变体均不能逃出根目录。 |
| 敏感文件 | `.env`、Fernet Key、SSH Key、`/proc` 与其他用户目录均不能读取。 |
| 提示注入 | 模拟模型请求读取系统密钥时，Policy/containment 应先拒绝且事件不得泄露内容。 |
| 审批 | 高风险访问应产生 `WAITING_HUMAN` 与审计事件；拒绝后不执行工具。 |
| 回归 | 已授权工作目录内的普通文本读取、受限代码搜索仍可正常工作。 |

## 6. WP-02：资源归属、租户隔离与运营数据治理

### 6.1 仓储与服务层约束

模型详情、日志、下载任务、Agent Run、会话、知识库、训练任务、调度任务和插件配置都必须适用同一条规则：**用户可见资源的查询、更新、删除和流订阅均按当前用户过滤；共享资源必须带明确的 `scope=global` 或 `owner_type` 语义。** 不允许以主键查询后再由调用方“自行判断”。[1]

| 资源 | 当前缺口 | 目标设计 | 关键测试 |
|---|---|---|---|
| 模型详情 | `info(model_id)` 未强制 `user_id` | `info(model_id, user_id)` 必传；全局模型需显式标记 | 双用户猜测 ID 返回 404。 |
| 系统日志 | 普通认证用户可读全局原始日志 | 管理员专属、分页、结构化脱敏摘要 | 普通用户 403；日志正文不含密钥/其他用户数据。 |
| 下载任务 | 进程级字典，无 `user_id` 和持久化 | `DownloadTask` 表、归属/状态/错误码/取消标记 | 重启恢复、跨用户隔离、任务 ID 猜测失败。 |
| 模型扫描/安装 | 可传任意服务器路径 | 只接受允许根目录内已登记资产 | 任意绝对路径与软链接路径被拒绝。 |
| 运行与任务流 | 部分状态依赖进程内单例 | 持久化权威状态 + 用户范围 SSE | 跨用户 run/event/stream 均返回 404。 |

### 6.2 数据迁移与兼容策略

本地单用户档可以继续采用 SQLite，但每次 schema 演进必须新增带版本号的迁移单元、幂等升级测试和旧库样本升级测试。对于新的 `DownloadTask` 等资源，建议最少包含：`id`、`user_id`、`resource_type`、`status`、`state_version`、`idempotency_key`、`created_at`、`updated_at`、`completed_at` 与脱敏 `error_code/error_detail`。

服务端档不得继续依赖仅追加列的手写迁移。M3 必须引入 Alembic 和 PostgreSQL 迁移路径，形成“生成—审查—升级—回滚演练”的流程。本地 SQLite 迁移与服务端 Alembic 迁移可以共存，但必须明确每个发布目标使用的迁移工具和支持边界。

### 6.3 日志与审计规范

日志不应被视为可自由返回的调试文本。应用日志应改为结构化事件，至少包含时间、级别、correlation ID、用户/项目匿名标识、动作、资源类型、稳定错误码和安全分类；禁止记录密码、JWT、Bearer Token、Provider API Key、完整用户提示、未脱敏文件内容与完整上游响应。读取日志、下载导出、管理员变更和敏感工具调用都必须产生 `OperationAudit` 记录。

## 7. WP-03：输入边界、上传防护与统一错误模型

### 7.1 上传与请求体限制

数据集和知识库上传不能先把完整文件读入内存再检查业务大小。反向代理、ASGI 层与应用层需要三道防线：代理层限制 Content-Length；应用层按块读取并在超过限额时立即中止；持久化层执行用户磁盘配额和文件类型校验。每个请求还应有超时、并发和临时文件清理保障。[1]

| 输入类型 | 需执行的上限 | 服务端处理 |
|---|---|---|
| Multipart 文件 | 单文件字节数、总请求体、用户总存储空间 | 分块读写；超限即删除临时文件并返回 413。 |
| OpenAI/聊天消息 | 消息条数、单条字符数、总字节数、推测 token 数 | Pydantic 模型校验后再调用 Provider。 |
| Agent Run | 输入长度、工具调用预算、运行超时、并发数 | 创建前预算检查，运行中强制取消/终止。 |
| 搜索与路径 | 查询长度、结果上限、目录深度、扫描文件数 | 参数白名单、分段执行与资源计量。 |

### 7.2 错误响应契约

所有 API 错误统一使用稳定错误码、HTTP 状态、用户安全消息和 correlation ID。客户端可以基于错误码做本地化与恢复提示，服务器详细异常只应写入脱敏日志。目标响应形态如下：

```json
{
  "type": "https://docs.modelforge.local/errors/resource-outside-allowed-root",
  "title": "Resource access denied",
  "status": 403,
  "code": "RESOURCE_OUTSIDE_ALLOWED_ROOT",
  "detail": "The requested resource is outside the permitted workspace.",
  "correlation_id": "..."
}
```

禁止将 Hugging Face、文件系统、Provider、数据库或 Python 原始异常直接拼接进对外 `detail`。对可重试故障应提供 `retryable=true` 或明确的 `Retry-After`，但不得暴露上游地址、绝对路径和敏感配置。

### 7.3 认证加强要求

新注册密码最低长度应提升到基于风险的基线，并阻断常见/已泄露密码；密码哈希升级采用 Argon2id，若因合规要求保留 PBKDF2-HMAC-SHA256，则将工作因子提升到至少 600,000，并把算法、参数与 salt 存入可升级的 hash 格式。[4] [5] 比较操作改用 `hmac.compare_digest`。登录应增加账号与 IP 双维度节流、风险事件后的会话失效以及可选 MFA 路径。

## 8. WP-04：测试、CI、依赖与发布治理

### 8.1 测试金字塔

测试投入应从“测试数量”转向“发布风险覆盖”。当前已有运行时、API、桌面端与硬化测试基础，后续按以下层级补齐。

| 测试层 | 目的 | 最小门槛 |
|---|---|---|
| 单元测试 | 状态机、路径校验、错误映射、策略合并、SSE parser | 所有安全纯函数与状态转换穷尽主要分支。 |
| 仓储测试 | `user_id` 过滤、租约、CAS、迁移 | 至少双用户与竞争写入场景。 |
| API 集成测试 | 认证、鉴权、上传、错误体、SSE | 401/403/404 与成功路径均有覆盖。 |
| 端到端冒烟 | 应用导入、lifespan、Agent Run、Docker、桌面离屏 | 每次 PR 与发布候选必须执行。 |
| 安全回归 | 路径逃逸、IDOR、无认证控制面、日志泄露、DoS 上限 | P0/P1 修复不得缺失负向测试。 |

### 8.2 CI 强制顺序

CI 应按“最快发现最根本错误”的顺序运行，而不是先运行昂贵测试再在后段失败。

1. 依赖安装与锁文件校验；
2. `ruff check`、格式检查和 `git diff --check`；
3. `import main`、应用路由注册、lifespan 与 `/healthz` 冒烟；
4. 单元与仓储测试；
5. API、SSE、桌面离屏集成测试；
6. 覆盖率阈值检查；
7. `pip-audit` 与 SBOM 生成；
8. Docker 构建、非 root 容器启动、liveness/readiness；
9. 发布候选才运行真实 Provider、Ollama、CPU/GPU 和安装包矩阵。

建议先为后端与客户端分别设置保守但不可回退的覆盖率基线，并只允许经代码所有者批准后调整阈值。覆盖率 XML 必须被解析为质量门禁，而非仅上传为 artifact。

### 8.3 可复现依赖与镜像

项目应新增锁文件或等价的 hash-pinned requirements，以保证 CI、开发机和镜像解析同一组直接与传递依赖。Dockerfile 应创建非 root 用户，预创建并限制可写目录，运行时仅授予模型、数据和日志所需权限。健康检查拆为：

- **liveness**：进程与 HTTP 服务仍可响应；
- **readiness**：数据库迁移完成、事件外箱可用、关键后台组件启动；
- **dependency status**：Ollama/远程 Provider 等外部依赖单独报告，不让可选模型使基础服务误判为崩溃。

发布证据必须与固定 Git commit 绑定：测试结果、coverage、SBOM、pip-audit、镜像 digest、桌面包 checksum、签名和安装验证记录缺一不可。

## 9. WP-05：服务端可扩展性与可靠运行

M2 完成后，项目需要把“本机单进程实现”与“服务端多实例实现”拆开。AgentRuntime、PluginManager、Downloader、Scheduler 和 EventBus 中的进程级状态在本地体验中可以保留，但服务端档需要持久化或外部化权威状态。Run 的领取继续使用 `state_version` 与 lease，但 lease 的续租、失效接管、幂等终态和外箱投递必须在多 worker 下验证。[2]

| 组件 | 本地实现 | 服务端目标接口 |
|---|---|---|
| 关系数据 | SQLite + WAL | PostgreSQL + Alembic。 |
| 调度 | asyncio 进程内 scheduler | 可替换持久化调度器；occurrence claim 去重。 |
| 事件通知 | 内存 EventBus + 数据库回放 | 外部 pub/sub 或数据库通知；SSE 仍以持久化 cursor 为准。 |
| 后台任务 | `asyncio.Task` 与进程内监控 | 可持久化任务队列/worker，具备 lease、重试和死信观察。 |
| 下载 | 全局字典 | 用户归属的持久化 Task，重启后可恢复或明确失败。 |
| 插件 | 进程级加载状态 | 具备 tenant/project scope、签名/来源与隔离策略。 |

本阶段不要求一次性引入复杂的分布式系统，但必须先定义端口（ports）和适配器（adapters），使现有 SQLite/asyncio 实现可以替换。新业务代码不得直接依赖具体进程内实现。

## 10. WP-06：面向付费 Agent API 的控制面设计

### 10.1 产品能力序列

在 M4 之前，不应接入支付。商业 API 的最低闭环是：**客户身份可确定、一次调用可幂等、资源消耗可计量、额度可以强制、账务可追溯**。项目已有 Run token usage、模型指标桶和预算偏好基础，但它们尚不能替代不可变用量账本。[2]

| 阶段 | 交付能力 | 不可跳过的约束 |
|---|---|---|
| 身份 | Organization、Project、Environment、API Key | API Key 仅展示一次；哈希存储；可撤销、可轮换、有作用域。 |
| 调用 | 版本化 Agent Run API、Idempotency-Key、Webhook/SSE | 所有调用绑定 project；重复请求不得重复扣费或执行。 |
| 计量 | 不可变 UsageLedger、价格版本、Run 关联 | Token、工具、存储、运行时长等计量规则可审计。 |
| 配额 | 并发、日/月额度、单 Run 预算与超额策略 | 在昂贵执行前作预检，执行后原子记账。 |
| 账务 | 对账视图、用量导出、账期冻结 | 先支持账单草稿/人工对账，再接入支付。 |
| 运营 | Usage dashboard、告警、支持查询、SLO | 不向普通用户暴露其他租户的日志或运行数据。 |

### 10.2 数据模型建议

新增表必须拥有不可变主键、所属关系、创建时间、状态和审计字段。`ApiKey` 只保存 `prefix`、`secret_hash`、`scope_json`、`project_id`、`last_used_at`、`expires_at`、`revoked_at`。`UsageLedger` 采用追加式设计，包含 `id`、`project_id`、`run_id`、`idempotency_key`、`metric_type`、`quantity`、`unit_price_version`、`occurred_at` 与 `metadata_redacted`；金额汇总由账期聚合生成，不能允许直接更新历史用量。

## 11. API、数据库与兼容性变更清单

| 变更 | 类型 | 兼容策略 | 版本要求 |
|---|---|---|---|
| `/api/v1/runtime/*` 强制认证 | 行为破坏 | 短期返回明确 401；桌面端同时升级 Token 注入 | 在同一 PR 修改客户端与 API 测试。 |
| 模型 `info/status` 增加用户范围 | 服务签名变更 | 仅由 API 层传递用户；禁止保留不带用户的 public 方法 | 先补双用户测试，再改签名。 |
| 文件工具增加 allowed roots | Tool 参数/上下文变更 | 旧 Agent 未声明 root 时默认拒绝，并在 UI 提供迁移提示 | 先发布只读诊断，再强制执行。 |
| 统一错误响应 | DTO 改进 | 保留 `detail` 的安全子集；客户端改按 `code` 处理 | 在 API 文档加入错误码表。 |
| 下载任务持久化 | 数据库迁移 | 旧内存任务在重启时标记不可恢复，不伪造完成 | 新表、索引、迁移和回滚说明同时提交。 |
| API Key/组织模型 | 新 API | 不改变本地 Cookie/JWT 使用方式 | 单独 `/api/v2` 或正式版本化策略。 |

## 12. 分支、提交、审查与回滚策略

每个工作包至少使用一个独立的短生命周期分支和 Pull Request。PR 禁止混合“安全修复”“大规模格式化”“功能新增”“文案更新”四类无关改动；这样可以让安全审查、回滚和 cherry-pick 保持可靠。建议提交粒度如下：

| PR 顺序 | 建议标题 | 合并前强制证据 |
|---:|---|---|
| 1 | `fix(runtime): restore app import and status contracts` | import/lifespan/diagnostics/SSE 单测。 |
| 2 | `fix(security): enforce runtime authentication and file containment` | 认证、路径逃逸、敏感文件、安全负测。 |
| 3 | `fix(tenancy): scope models logs and downloads by user` | 双用户 IDOR 回归、迁移测试。 |
| 4 | `fix(api): bound uploads and normalize error responses` | 超限上传、异常脱敏、兼容测试。 |
| 5 | `build(ci): enforce quality gates and reproducible releases` | CI dry-run、覆盖率、镜像非 root 冒烟。 |
| 6 | `feat(platform): add server deployment ports and migrations` | PostgreSQL/SQLite 双矩阵与接管测试。 |
| 7 | `feat(api): add project keys usage ledger and quotas` | 幂等、配额、账本一致性与审计测试。 |

数据库变更合并前必须提供正向升级、重复执行幂等、失败回滚/恢复和旧数据可读性说明。安全修复若需紧急发布，应采用最小补丁分支，禁止夹带桌面端重构；发布后再回填完整设计重构。

## 13. 质量门禁、验收与发布决策

### 13.1 M1 发布准入门槛

| 类别 | 必须满足的条件 |
|---|---|
| 启动 | `import main`、`/healthz`、lifespan 启停均成功。 |
| 代码质量 | Ruff 0 错误；`git diff --check` 通过；没有未解释的 `except Exception: pass` 出现在关键控制路径。 |
| 测试 | 全量 pytest 无 collection error；P0/P1 安全负向测试全部通过。 |
| 认证与隔离 | 未认证 runtime 请求为 401；越权资源请求为 404/403；管理员接口不可由普通用户访问。 |
| 输入边界 | 超限文件、消息和路径请求被拒绝且不耗尽内存或暴露主机路径。 |
| 流式与异步 | SSE 支持空行、EOF、多行、重连；调度状态契约稳定；关闭时后台任务可回收。 |
| 发布证据 | 依赖审计、SBOM、Docker 冒烟和桌面离屏结果绑定同一 commit。 |

### 13.2 M4 API 试点准入门槛

M1—M3 全部通过后，只有在 API Key 可撤销、请求幂等、Run 用量可追溯、配额强制生效、客户数据按项目隔离、审计与告警可用时，才允许选择有限客户进入 API 试点。支付接入不构成试点前提，反而应在账本和配额连续稳定运行一个账期后再评估。

## 14. 风险登记与决策责任

| 风险 | 级别 | 责任角色 | 触发信号 | 处置方式 |
|---|---|---|---|---|
| 应用入口重新失效 | P0 | 后端负责人 | import/health smoke 失败 | 阻断合并与发布，优先回滚入口相关 PR。 |
| 主机文件或密钥外泄 | P0 | 安全负责人 | 路径测试失败、异常内容泄露 | 立即关闭文件工具，轮换密钥，保留审计证据。 |
| 匿名高成本推理 | P0 | API 负责人 | 无 Token 调用成功或并发异常 | 关闭端点/网关规则，修复认证与速率限制。 |
| 跨用户数据读取 | P1 | 数据层负责人 | 双用户测试返回资源 | 修复仓储签名并检查同类资源。 |
| 上传导致资源耗尽 | P1 | 平台负责人 | 高水位内存、413 前完整读入 | 启用网关限制并改流式处理。 |
| 多实例重复执行 | P2 | Runtime 负责人 | 同一 occurrence/run 多次消费 | 提升 lease/CAS，停用多 worker 直到验证通过。 |
| 用量账务错误 | P3 | 产品/API 负责人 | 幂等重复扣减或账本不一致 | 冻结试点，按追加式冲正记录修复。 |

## 15. 文档维护要求

本文与 `PROJECT_AUDIT_REPORT_2026-08-27.md` 一起构成当前整改基线。每个工作包结束后必须更新：已完成任务、实际提交号、测试命令与结果、风险状态、已知偏差和下一阶段 Go/No-Go 决策。README 中的测试数、路由数、版本和发布状态只能在同一固定提交的 CI 证据产生后更新，禁止手工乐观声明。[1]

## 参考资料

[1]: ./PROJECT_AUDIT_REPORT_2026-08-27.md "ModelForge 项目审核报告（2026-08-27）"
[2]: ./MODELFORGE_3_RUNTIME_ARCHITECTURE_AUDIT.md "ModelForge 3.x Runtime 架构审计"
[3]: ./TECHNICAL_DEVELOPMENT_PLAN.md "既有技术开发计划"
[4]: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html "OWASP Password Storage Cheat Sheet"
[5]: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html "OWASP Authentication Cheat Sheet"
