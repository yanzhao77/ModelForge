# ModelForge 3.0 整改开发文档

**文档日期：** 2026-09-01  
**适用分支：** `master`  
**文档状态：** 已实施，待最终发布签署  
**整改范围：** 多用户数据隔离、数据库配置生效、远程 Provider 网络边界、默认安全配置、API/发布元数据一致性

## 1. 文档目的

本文件记录对 ModelForge 3.0 代码检查结果的整改方案，作为后续实现、测试、验收和发布决策的共同依据。

整改后的自动化回归为 **917 passed、3 skipped**，Ruff、`pip check`、`pip-audit`（基础/开发/GUI 依赖）和 Python 编译检查均通过，路由统计校验为 current。相对 866 条基线，净增 51 个隔离与安全回归测试。自动化测试通过不等于真实多用户部署、真实 Provider 网络和 GPU 已验证；这些边界仍需在发布记录中明确。

## 2. 当前结论

### 2.1 发布结论

P1 代码整改和自动化回归已经完成，项目当前进入部署验证阶段。完成 Docker/PostgreSQL smoke、本地 SQLite 数据核对和发布资产绑定前，仍不应作正式多用户生产发布：

- 本地可信单用户部署；
- 受控开发环境；
- 不承载互不信任用户数据的单副本服务端试点。

以下场景在部署证据补齐前暂不应宣称生产就绪：

- 多用户共享 PostgreSQL 服务；
- 网络可达的公共或半公共 Agent 服务；
- 允许普通用户配置任意远程 Provider 的服务端部署；
- 依赖 `config.yaml` 中自定义 SQLite 路径的本地部署。

### 2.2 当前质量证据

| 检查项 | 结果 | 说明 |
|---|---|---|
| 全量 pytest | PASS | 917 passed，3 skipped |
| Ruff | PASS | `backend client tests scripts` |
| Python 编译 | PASS | `compileall` 无错误 |
| 依赖一致性 | PASS | `pip check` 无破损依赖 |
| 已安装基础依赖漏洞扫描 | PASS | `pip-audit` 无已知漏洞 |
| 真实网络 Provider | 未完成 | 网络/真实 Provider 场景未纳入默认回归 |
| 真实模型/GPU | 未完成 | 无 Torch、真实模型和 NVIDIA GPU |
| 多用户隔离专项测试 | PASS | R1/R2/R3 专项回归通过 |

## 3. 问题清单与优先级

| ID | 优先级 | 问题 | 影响 |
|---|---|---|---|
| MF-SEC-001 | P1 | Agent 内置 `knowledge_search` 不携带用户身份，可能读取全局知识库中的其他用户文档。 | 机密知识库内容泄露，违反租户隔离。 |
| MF-SEC-002 | P1 | Agent Run 接受任意 `session_id`，且历史 Provider 按会话 ID 无用户范围读取。 | 其他用户的对话历史可能被注入当前 Run。 |
| MF-SEC-003 | P1 | `Settings.database_path` 能从 YAML 读取，但实际 SQLAlchemy 引擎只读环境变量或默认路径。 | 数据写入错误数据库，可能造成数据分裂、误读或数据丢失。 |
| MF-SEC-004 | P1 | 远程 Provider 的解析和实际推理请求必须持续执行网络目标校验，防止旧配置和 DNS 变化绕过 SSRF 策略。 | 服务端可能被利用为 SSRF 出站代理，并向非预期地址发送凭据。 |
| MF-CONFIG-001 | P2 | `config.example.yaml` 将默认文件系统访问设为 `true`，与代码的默认拒绝策略相反。 | 复制示例配置后，Agent 默认获得文件读取能力。 |
| MF-REL-001 | P2 | API 路由数量、应用版本和本地发布资产与当前代码不一致。 | 文档、发布包和运行时身份不可追溯，容易错误发布。 |

## 4. 设计原则

### 4.1 身份必须来自可信运行时上下文

用户 ID、Agent ID、Run ID 和会话 ID 不得由工具参数或模型输出决定。工具只能从 `ToolExecutionContext` 读取调用身份；API 只能从认证用户和数据库所有权关系读取身份。

### 4.2 所有持久化读取都必须带所有权条件

对于用户级资源，查询必须显式包含 `user_id` 条件。仅凭资源 ID、名称或文件名查询不构成授权检查。公共资源必须明确标注为全局只读，修改和删除需要独立的管理员边界。

### 4.3 默认拒绝，显式授权

网络、Shell、文件系统和远程 Provider 出站访问均采用默认拒绝。允许访问时需要有明确的配置、策略、审计记录和测试覆盖。

### 4.4 配置源必须单一且可验证

YAML、环境变量和代码默认值的优先级必须统一。启动时实际使用的数据库 URL、工作目录和网络策略应能通过安全的诊断信息确认，但不能泄露密钥或完整用户路径。

### 4.5 整改必须先补测试，再改变行为

每个 P1 修复至少需要一个失败前能复现问题、修复后能通过的回归测试，并至少包含两个用户的隔离场景。不得只增加单用户 happy path 测试。

## 5. MF-SEC-001：知识库工具租户隔离

### 5.1 当前实现

当前内置工具在 [`backend/app/services/agent_tools.py`](../backend/app/services/agent_tools.py) 中实现：

- `tool_knowledge_search(query, top_k)` 不接受 `context`；
- 通过进程级 `get_global_kb()` 查询；
- 没有传入 `db` 或 `user_id`；
- `KnowledgeBase` 的内存向量索引包含多个用户上传内容。

工具在 [`backend/app/runtime/tools/builtin.py`](../backend/app/runtime/tools/builtin.py) 中以 `READ` 权限注册。由于 `FunctionTool` 只有在函数签名包含 `context` 时才注入工具上下文，当前实现绕过了已有的用户身份链路。

### 5.2 目标行为

Agent Run 的知识库工具必须满足：

1. 没有有效 `context.user_id` 时直接拒绝查询，不返回全局内存结果；
2. 查询必须使用独立的 `SessionLocal` 数据库会话；
3. 查询调用 `KnowledgeBase.query(..., db=db, user_id=context.user_id, knowledge_binding=...)`；
4. 若 Agent 声明了知识库集合，只允许访问当前用户拥有且已绑定的集合；
5. 工具返回结果中不包含其他用户的文档内容、路径或内部数据库信息；
6. 保留现有 `knowledge_binding.mode=disabled` 语义。

### 5.3 推荐改造

#### A. 扩展工具签名

将工具改为接收运行时上下文：

```python
def tool_knowledge_search(
    query: str,
    top_k: int = 3,
    context: Any | None = None,
) -> str:
    ...
```

从 `context.user_id` 获取身份，不接受 `user_id` 工具参数。对 `user_id` 做正整数校验，失败时返回稳定错误码，例如 `KNOWLEDGE_USER_CONTEXT_REQUIRED`。

#### B. 将知识绑定传入 ToolExecutionContext

在 [`backend/app/runtime/run_context.py`](../backend/app/runtime/run_context.py) 增加：

```python
knowledge_binding: dict[str, Any] | None = None
```

在 [`backend/app/runtime/execution.py`](../backend/app/runtime/execution.py) 创建 `ToolExecutionContext` 时复制 `ctx.knowledge_binding`。工具仅使用运行时已经解析、验证过的绑定，不直接信任模型输出。

#### C. 使用用户范围查询

工具内部使用 `SessionLocal`：

```python
with SessionLocal() as db:
    result = kb.query(
        query,
        top_k=bounded_top_k,
        db=db,
        user_id=context.user_id,
        knowledge_binding=context.knowledge_binding,
    )
```

`top_k` 必须限制在合理范围，例如 `1..20`。异常只返回稳定的工具错误，不返回 SQL、路径或堆栈。

#### D. 防止内存索引成为旁路

当前 `KnowledgeBase.query` 在 `db is None` 时使用全局向量索引。对于生产 Agent 工具调用，该分支必须不可达。可以采用以下策略：

- Agent 工具始终传入 DB 和用户 ID；
- `tool_knowledge_search` 无用户上下文时拒绝；
- 后续将内存索引改为按用户/集合分区，或仅将 DB 过滤后的结果建立临时查询向量。

### 5.4 测试要求

新增或补充 `tests/test_knowledge_tool_isolation.py`：

- 用户 1 上传含唯一标识 `ALICE_ONLY_TOKEN` 的文档；
- 用户 2 上传含唯一标识 `BOB_ONLY_TOKEN` 的文档；
- 用户 1 的工具查询只能返回 `ALICE_ONLY_TOKEN`；
- 用户 2 的工具查询只能返回 `BOB_ONLY_TOKEN`；
- `context=None` 和 `context.user_id=None` 均不得返回任何结果；
- 用户 1 绑定用户 2 的集合时返回空结果或稳定的不可用错误；
- 验证结果中不出现另一用户的 filename、document ID 或 chunk 内容。

## 6. MF-SEC-002：Agent Run 会话历史隔离

### 6.1 当前实现

当前 API 在 [`backend/app/api/agent.py`](../backend/app/api/agent.py) 接受 `session_id`，只验证 Agent 属于当前用户，没有验证会话所有权。运行时在 [`backend/app/runtime/runtime.py`](../backend/app/runtime/runtime.py) 保存该会话 ID，ContextBuilder 再调用 [`backend/app/runtime/kb_provider.py`](../backend/app/runtime/kb_provider.py) 的 `SessionHistoryProvider`。

`SessionHistoryProvider.load(session_id)` 最终通过 `SessionService.get_session_messages` 按 `Message.session_id` 查询，没有 `Session.user_id` 条件。

### 6.2 目标行为

创建 Agent Run 时：

- `session_id` 为空时保持现有无会话行为；
- `session_id` 不为空时，必须确认该会话属于当前认证用户且处于可用状态；
- 所有运行时历史读取都必须携带 `user_id`；
- 越权资源统一返回 `SESSION_NOT_FOUND` 或 `SESSION_UNAVAILABLE`，不得区分“资源不存在”和“属于其他用户”；
- 调度器和 Multi-Agent 子 Run 也必须继承并验证父 Run 的用户身份。

### 6.3 推荐改造

#### A. API 创建 Run 前做所有权校验

在 `create_run` 中增加：

```python
if req.session_id is not None:
    session = db.query(Session).filter(
        Session.id == req.session_id,
        Session.user_id == user.id,
        Session.is_active.is_(True),
    ).first()
    if session is None:
        raise problem(404, "SESSION_NOT_FOUND", "Session was not found.", correlation=corr)
```

建议将查询封装为 `SessionService.get_session_by_id(db, session_id, user.id)`，并额外检查 `is_active`，避免已软删除会话继续被新 Run 使用。

#### B. 扩展 HistoryProvider 接口

将协议和实现从：

```python
load(session_id, limit=20)
```

改为：

```python
load(session_id, user_id, limit=20)
```

`ContextBuilder` 从 `ctx.user_id` 传入用户身份。`SessionHistoryProvider` 通过带用户条件的 Session 查询确认所有权，再读取消息。不要只给 `messages` 表增加 `user_id` 后依赖冗余列作为唯一保护，Session 归属关系仍应是权威来源。

#### C. 保护非 API 入口

以下入口同样必须验证会话归属：

- `AgentRuntime._scheduler_trigger`；
- `DelegateTool` 创建的子 Run；
- 项目 API 创建的 Run；
- 恢复持久化调度任务；
- 任何内部调用 `runtime.create_run` 的服务。

推荐在 Runtime 增加统一的 `_validate_run_bindings(agent_id, user_id, session_id, parent_run_id)`，API 和调度器都调用同一套校验逻辑，避免仅修 API 入口。

### 6.4 测试要求

新增 `tests/test_agent_session_isolation.py`：

- 创建 Alice、Bob 两个用户和各自会话；
- 在 Bob 会话写入唯一内容 `BOB_PRIVATE_MESSAGE`；
- Alice 携带 Bob 的 `session_id` 创建 Run，接口必须拒绝；
- 通过直接 Runtime、调度器和 Delegate 子 Run 入口尝试复用 Bob 会话，也必须拒绝或不返回 Bob 历史；
- 合法用户绑定自己的会话，历史仍能正常注入；
- 已软删除会话不能绑定新 Run；
- 错误响应不得泄露会话是否存在或归属其他用户。

## 7. MF-SEC-003：数据库配置真正生效

### 7.1 当前实现

`core.config.load_config()` 会读取 YAML 中的 `database_path`，但 `core.database` 在模块导入时自行读取：

1. `DATABASE_URL` 环境变量；
2. `DATABASE_PATH` 环境变量；
3. 项目默认 `data/modelforge.db`。

因此，用户修改 `config.yaml` 的 `database_path` 后，`Settings` 显示的是新路径，但 SQLAlchemy Engine 仍连接默认路径。

### 7.2 配置优先级

统一定义如下：

1. `DATABASE_URL`：服务端 PostgreSQL 或其他完整 SQLAlchemy URL，优先级最高；
2. `DATABASE_PATH`：本地 SQLite 路径，优先级次之；
3. `config.yaml.database_path`：本地 SQLite 路径；
4. 内置默认路径：项目根目录下 `data/modelforge.db`。

服务端模式仍必须要求显式 `DATABASE_URL`，不得通过 YAML 的 SQLite 路径降级。

### 7.3 推荐改造

将数据库 URL 构造集中到配置模块或一个无副作用的配置函数中，避免 `core.database` 与 `core.config` 分别解析配置。

推荐流程：

```python
def database_url_from_settings(settings: Settings) -> str:
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if configured_url:
        return configured_url

    path = os.getenv("DATABASE_PATH") or settings.database_path
    return f"sqlite:///{path}"
```

实际实现需要注意模块导入循环：`core.config` 不应导入 `core.database`。可以让 `core.database` 导入已构造的 `settings`，或将 URL 解析函数放在独立的 `core/database_config.py`。

同时统一 `DATABASE_URL`、`SQLALCHEMY_DATABASE_URL` 和迁移预检使用的值，确保：

- 应用 Engine；
- SQLite 迁移；
- migration preflight；
- Alembic 服务端迁移；

不会指向不同数据库。

### 7.4 启动诊断与兼容

启动日志或管理员诊断可以提供非敏感摘要：

- `database_backend=sqlite|postgresql`；
- `database_config_source=DATABASE_URL|DATABASE_PATH|config.yaml|default`；
- 数据库路径只显示脱敏后的 basename 或稳定哈希，不显示完整主机凭据和用户目录。

历史用户如果曾修改 YAML 但实际数据一直写入默认数据库，修复不能自动搬迁数据。应在启动诊断中提示检测到多个候选数据库，并提供人工备份、核对和迁移步骤。

### 7.5 测试要求

补充 `tests/test_database_config_resolution.py`：

- 无环境变量时使用 YAML `database_path`；
- `DATABASE_PATH` 覆盖 YAML；
- `DATABASE_URL` 覆盖 SQLite 配置；
- 生产环境没有 `DATABASE_URL` 时按现有服务端策略拒绝或明确走受支持模式；
- Engine 实际 URL 与解析函数结果一致；
- migration preflight 与 Engine 指向同一数据库；
- 相对路径相对于约定的项目根目录解析，而不是随当前工作目录漂移。

## 8. MF-SEC-004：远程 Provider SSRF 防护

### 8.1 整改后实现

[`backend/app/core/network_security.py`](../backend/app/core/network_security.py) 提供统一的 Provider 目标策略：

- `local` 模式允许显式 loopback Provider；`server` 模式默认只允许公网目标；allowlist 是显式例外；
- 字面量 IP 和 DNS 解析得到的每一个 A/AAAA 地址都必须是公网地址；loopback 变体、RFC1918、link-local、metadata 和未指定地址均拒绝；
- Provider `save()`、`verify()`、`resolve()`、`resolve_verified()` 均使用该策略；
- `OpenAIRuntime` 和 `OpenAICompatibleProvider` 在每次非流式/流式 HTTP 请求创建前再次校验；
- 所有 HTTP 客户端均关闭自动重定向；验证失败不创建 HTTP 客户端，不发送 Authorization header；
- 稳定错误码为 `TARGET_NOT_ALLOWED`，不返回 URL、解析地址或 API Key。

此前存在的旁路是旧数据库 Provider 可直接进入 `resolve()`/`resolve_verified()`，以及运行时适配器可在未再次校验时直接发起请求；本次已补齐这些入口的校验。

### 8.2 目标网络策略

将 Provider 目标按部署模式区分：

| 模式 | 允许目标 |
|---|---|
| 本地单用户 | 显式 loopback；其他局域网地址必须通过 allowlist；仍禁止凭据嵌入 URL |
| 受控服务端 | 管理员配置的域名/地址 allowlist；默认禁止私有网段 |
| 公共多租户 | 仅允许 HTTPS 公网目标，经 DNS/IP 解析后再次校验；禁止用户自行放宽网络边界 |

禁止访问至少包括：

- `127.0.0.0/8`、`::1` 以外的 loopback 变体；
- RFC1918 私有网段；
- `169.254.0.0/16` 和 IPv6 link-local；
- `0.0.0.0/8`、保留网段、未指定地址；
- 云厂商 metadata 常用地址；
- 解析后落入上述网段的域名。

由于本地 Ollama 需要 loopback，不能简单删除 localhost 支持。应通过显式 `provider_network_mode=local|server` 或部署级 allowlist 区分，而不是以 hostname 字符串作为唯一信任依据。

### 8.3 推荐改造

#### A. URL 解析与 DNS 校验

新增 `core/network_security.py`，提供：

- `validate_provider_target(url, mode, allowlist)`；
- `resolve_and_validate_host(host, port)`；
- `is_public_ip(address)`；
- `is_allowed_provider_origin(url)`。

请求前解析 hostname 的所有 A/AAAA 记录，对每个 IP 做 CIDR 分类。每次实际请求前重新解析并校验 hostname，避免只依赖保存/验证时的结果。当前实现将校验窗口压缩到请求创建前；若部署需要抵抗极窄的解析竞态，应进一步采用 IP 固定连接并保留正确的 Host/SNI，列为部署加固项。

#### B. 禁止自动跟随重定向

现有验证请求已经设置 `follow_redirects=False`，运行时 Provider 请求也必须保持该策略，或者对每次重定向重新执行完整 URL/IP 校验。不得让公网地址通过 30x 跳转到内网。

#### C. 凭据最小暴露

只有通过目标校验的请求才允许带 `Authorization` header。错误信息不能回显完整 URL、解析地址或 API Key。验证失败状态仅保存稳定错误码。

#### D. 出站限额

增加连接、读取、响应大小和请求频率上限，避免 Provider 校验成为内部端口扫描或资源消耗入口。日志只记录 provider ID、稳定错误码和相关性 ID。

### 8.4 测试要求

新增 `tests/test_provider_network_policy.py`：

- 拒绝 `http://` 公网地址；
- 本地模式允许 `http://127.0.0.1`；
- 服务端模式拒绝 `127.0.0.1`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.169.254` 和 IPv6 link-local；
- 域名解析到私有 IP 时拒绝；
- 公网域名解析到多个地址，只要有一个地址不合规就拒绝；
- 重定向到私有地址时拒绝；
- 验证和推理请求都使用同一网络策略；
- 错误响应和日志不包含 API Key。

## 9. MF-CONFIG-001：示例配置安全默认值

### 9.1 问题

代码在 [`backend/app/core/config.py`](../backend/app/core/config.py) 和 [`backend/app/runtime/policy/engine.py`](../backend/app/runtime/policy/engine.py) 中将文件系统访问默认为 `false`，但 `config.example.yaml` 设置为：

```yaml
policy:
  default_filesystem_access: true
```

复制示例配置后，所有未显式覆盖策略的 Agent 都会获得文件读取能力。虽然读取路径仍受每用户 workspace containment 保护，但这与文档和代码定义的默认拒绝原则不一致。

### 9.2 处理方案

- 将 `config.example.yaml` 改为 `false`；
- 在示例文件中明确说明如何为受信 Agent 显式开启；
- 为配置示例增加自动一致性测试，比较 YAML 默认值与 `Settings()`/`Policy.from_settings()`；
- README、部署文档和 Agent Runtime 文档统一使用“默认拒绝文件系统读取”的表述。

## 10. MF-REL-001：版本、路由和发布资产一致性

### 10.1 当前不一致

当前检查得到：

- README 和徽章标注 `92` 条路由；
- 当前 OpenAPI 实际为 `135` 个路径、`159` 个操作；
- FastAPI 应用元数据版本为 `3.0`；
- 根接口为兼容性返回 `version=2.1`、`edition=3.0`；
- 桌面唯一版本源为 `0.1.3-beta.1`；
- 被忽略的本地发布资产仍包含 `0.1.1-beta.1` 包、852 测试记录和旧候选 SHA。

### 10.2 处理方案

#### A. 路由数量自动生成

不要手工维护 README 中的数字。新增脚本从 `app.openapi()` 计算：

- OpenAPI path 数；
- HTTP operation 数；
- 是否包含框架文档端点。

CI 在文档或 API 路由变更时执行校验。README 只保留“以当前 OpenAPI 为准”，或由发布脚本更新徽章。

#### B. 版本语义

保留根接口 `version=2.1` 只能作为已确认的兼容契约。文档必须明确：

- `app.version=3.0`：平台 API/运行时版本；
- `root.version=2.1`：历史客户端兼容字段；
- `root.edition=3.0`：平台能力代际；
- `APP_VERSION=0.1.3-beta.1`：桌面发行版本。

建议增加机器可读字段，例如 `runtime_version`、`api_compatibility_version` 和 `desktop_version`，避免单一 `version` 被不同消费者误解。

#### C. 发布资产绑定

发布前必须验证：

- 当前 HEAD SHA；
- `APP_VERSION`；
- release manifest；
- SBOM 和 pip-audit 报告；
- checksum；
- Release Notes；

逐项绑定到同一个候选 SHA 和版本。旧 `release-artifacts/` 只能作为历史证据，不能被直接上传。由于该目录被 `.gitignore` 忽略，CI 必须在干净工作区重新生成并校验资产。

## 11. 实施顺序

| 阶段 | 内容 | 进入条件 | 退出条件 |
|---|---|---|---|
| R0 | 建立专项测试夹具和问题复现测试。 | 当前基线测试全绿。 | 已完成；4 个 P1 均有回归测试。 |
| R1 | 修复知识库和会话历史隔离。 | 身份传播路径明确。 | 已完成；多用户隔离测试通过，工具旁路关闭。 |
| R2 | 修复数据库配置解析。 | 确认现有环境变量兼容性。 | 已完成；YAML、环境变量、Engine、迁移预检一致。 |
| R3 | 实施 Provider SSRF 防护。 | 明确本地/服务端网络模式。 | 已完成；解析、验证、resolve 和推理请求入口均有策略校验。 |
| R4 | 对齐示例配置、路由统计和版本文档。 | P1 代码整改合并。 | 已完成；示例默认拒绝、路由统计和版本语义已对齐。 |
| R5 | 完整回归与发布评估。 | R1-R4 完成。 | 已完成代码门禁；Docker/PostgreSQL、真实 Provider、GPU 和跨平台证据仍属发布环境验证项。 |

## 12. 验收标准

### 12.1 P1 验收结果

- [x] 任意 Agent 工具没有用户上下文时不能查询知识库；
- [x] 用户 A 不能通过知识库工具检索用户 B 的文档；
- [x] 用户 A 不能将用户 B 的会话绑定到自己的 Run；
- [x] 调度、子 Agent、项目 API 和恢复流程不能绕过会话归属检查；
- [x] YAML 数据库路径能够改变实际 Engine 连接目标；
- [x] `DATABASE_URL`/`DATABASE_PATH`/YAML 优先级有测试证明；
- [x] 服务端 Provider 不能访问私有 IP、metadata 地址或解析到内网的域名；
- [x] Provider 保存、验证、解析和推理请求入口都会执行网络策略；自动重定向关闭；
- [x] Provider 错误、日志和审计数据不包含 API Key。

### 12.2 P2 必须满足

- [x] 示例配置默认文件系统访问为 `false`；
- [x] README 路由数量由 OpenAPI 实际结果校验；
- [x] 版本字段语义写入 API 参考文档；
- [ ] 发布资产全部绑定当前候选 SHA 和版本；
- [x] 旧的 0.1.1 资产不会被误识别为当前候选发布包。

### 12.3 质量门禁

```bash
./.venv/bin/pytest tests/ -q
./.venv/bin/ruff check backend client tests scripts
./.venv/bin/python -m compileall -q backend/app client/pyside6 scripts
./.venv/bin/python -m pip check
./.venv/bin/pip-audit -r requirements.txt -r requirements-dev.txt -r requirements-gui.txt
```

P1 专项测试必须单独输出结果，不能只依赖总测试数量：

```bash
./.venv/bin/pytest \
  tests/test_knowledge_tool_isolation.py \
  tests/test_agent_session_isolation.py \
  tests/test_database_config_resolution.py \
  tests/test_provider_network_policy.py -q
```

## 13. 回滚与数据安全

### 13.1 代码回滚

P1 修复按独立提交合并，建议每个问题一个提交或一个可回滚变更单元。回滚不得恢复以下行为：

- 无用户身份的知识库查询；
- 无用户范围的会话历史读取；
- 生产模式下任意私有网络 Provider；
- 依赖未生效的数据库配置。

### 13.2 数据库路径切换

数据库配置修复可能使应用首次连接到过去被忽略的 YAML 数据库。上线前必须：

1. 停止应用；
2. 备份当前实际使用的数据库；
3. 记录旧 Engine URL 和新 Engine URL 的非敏感摘要；
4. 检查两个 SQLite 文件的 schema 版本、用户数量和关键表计数；
5. 由管理员决定保留、合并或迁移；
6. 完成后再启动服务。

禁止在启动时自动合并两个数据库，避免重复用户、消息和 Run 记录。

### 13.3 Provider 配置兼容

现有合法的公网 HTTPS Provider 应继续可用。被新策略拒绝的 Provider 需要显示稳定错误码和迁移指引；不得自动删除配置或清空加密凭据。

## 14. 观测与审计要求

新增指标建议包括：

- `security.knowledge_scope_denied_total`；
- `security.session_scope_denied_total`；
- `security.provider_target_denied_total`，按稳定原因分类；
- `database.config_source`；
- `database.url_mismatch_detected`。

所有指标和审计记录不得包含：用户输入正文、文档正文、会话消息、完整 URL（如包含敏感路径）、API Key、JWT、数据库密码或完整本地路径。

## 15. 最终发布评估

代码整改和自动化质量门禁已经完成。最终发布记录还必须区分以下已完成证据与尚待部署环境补充的证据：

1. 已完成：4 个 P1 均有代码修复和专项回归测试；
2. 已完成：全量回归为 `917 passed, 3 skipped`，Ruff、compileall、pip check、pip-audit 和路由核对通过；
3. 待发布环境：Docker/PostgreSQL 单副本 smoke；
4. 待发布环境：本地 SQLite 配置切换的备份和数据核对；
5. 已完成：示例配置、README、API 版本语义和整改文档一致；
6. 待发布签署：发布资产与当前候选 SHA/版本、SBOM、checksum、Release Notes 的绑定；
7. 已完成：发布决策不使用旧的 0.1.1 或 852 测试资产；
8. 必须保留：没有真实模型、Provider 网络、GPU 或跨平台证据时，在发布说明中明确标记验证边界。

因此，代码层面整改结论为 **Ready for deployment verification**；在第 3、4、6 项发布证据补齐前，正式多用户生产发布仍保持 **No-Go**。

## 16. 发布前审查与候选提交记录

本节为发布前（pre-release）审查的实测记录，所有数字以工作区实测为准（不使用历史推断值）。

### 16.1 文件分类结果

审查 `git status` / `git diff` / 未跟踪文件（10 个未跟踪文件全部为源代码、测试或正式文档，无临时文件、日志、缓存、SQLite 数据库、本地密钥、模型文件或发布临时产物；未删除或回滚任何既有修改）。

- 新增核心安全模块（2）：`backend/app/core/network_security.py`（SSRF 策略）、`backend/app/core/database_config.py`（数据库配置单一来源）。
- 修改生产源码（15）：`api/agent.py`、`api/chat.py`、`api/providers.py`、`core/database.py`、`runtime/context/builder.py`、`runtime/errors.py`、`runtime/execution.py`、`runtime/kb_provider.py`、`runtime/models/openai_compatible.py`、`runtime/ports.py`、`runtime/run_context.py`、`runtime/runtime.py`、`services/agent_tools.py`、`services/remote_provider_service.py`、`services/runtimes/openai_api_runtime.py`。
- 配置（1）：`config.example.yaml`（`default_filesystem_access: true -> false`）。
- 正式文档（2）：`README.md`（路由统计/版本语义）、本文件。
- 发布工具脚本（1）：`scripts/api_route_stats.py`。
- 新增测试（6）：`tests/test_agent_session_isolation.py`、`tests/test_agent_session_isolation_api.py`、`tests/test_config_example_consistency.py`、`tests/test_database_config_resolution.py`、`tests/test_knowledge_tool_isolation.py`、`tests/test_provider_network_policy.py`。
- 修改测试（5）：`tests/test_context_engine_phase5.py`、`tests/test_openai_api_runtime.py`、`tests/test_openai_compatible_provider.py`、`tests/test_remote_provider_protocol.py`、`tests/test_remote_provider_verification.py`。
- 说明：`api/chat.py`、`api/providers.py`、`openai_compatible.py`、`openai_api_runtime.py` 及对应测试为 SSRF 整改向聊天/推理/OpenAI 兼容路径的扩展（属于 MF-SEC-004 覆盖要求），均已纳入审查。

### 16.2 安全审查结论

**knowledge_binding 来源边界（通过）**：绑定只来源于持久化的 `agent.knowledge_config`（`runtime.py:_resolve_agent_profile` → `RunContext.knowledge_binding` → `execution.py` 注入 `ToolExecutionContext.knowledge_binding`）。`knowledge.search` 工具 schema 仅声明 `query`/`top_k`；`FunctionTool.execute` 以 `{**arguments, "context": context}` 注入受信上下文，同名键会被覆盖，模型输出与工具参数均无法伪造 `user_id`/`knowledge_binding`；API `create_run` 不接受任何绑定输入字段。

**Session/Run 归属（通过）**：API 层（`agent.py` POST /runs 内 `Session.id == req.session_id and Session.user_id == user.id and is_active`，否则 404 `SESSION_NOT_FOUND`）与运行时单一创建阻塞点 `_validate_run_bindings` 双重校验；后者覆盖 API、scheduler（`runtime.py:740`）、delegate 子 Run（`delegate.py:74` → `create_run`）、持久化 schedule 恢复；`get_run`/`cancel_run` 既有 user 范围；`SessionHistoryProvider.load(session_id, user_id)` 非本人/无 user 返回空。

**Provider SSRF（通过，含一处记录在案的残余风险）**：目标校验发生在任何 HTTP 请求之前 —— `save`、`verify`（先校验后解密 API Key）、`resolve`（先校验后解密）、`resolve_verified`、`OpenAICompatibleProvider.chat`、`OpenAIRuntime` 的 chat/stream 协议。校验失败不打开发送 API Key 的路径。覆盖：IPv4/IPv6/IPv4-mapped IPv6（`_normalized_ip` 归一化）、IPv6 zone 剥离、loopback（含变体 127.0.0.2 默认拒绝）、RFC1918、link-local、云元数据（169.254.169.254）、保留/组播/0.0.0.0（`is_global` 判定）；DNS 多地址解析要求全部为公网地址（混合解析默认拒绝）；全部 3 处 httpx 客户端 `follow_redirects=False`。**残余风险（记录在案）**：校验时解析 DNS 与 httpx 实际建连之间存在的 TOCTOU 窗口未完全关闭（未做 IP 固定），计划将 DNS-rebinding 活体测试列为待部署环境验证项。

**数据库配置优先级（通过）**：`resolve_database_url` 单一函数实现 `DATABASE_URL > DATABASE_PATH > settings.database_path > data/modelforge.db`，Engine（`core/database.py`）、迁移预检（`IS_SQLITE`）、启动诊断共用同一来源；8 个单元测试覆盖各级优先级与兜底。

### 16.3 测试隔离验证方式

未新增全局 conftest.py。污染来源分析结果：两个历史污染点（全局 `KnowledgeBase` 单例嵌入器跨测试拟合、模块级 engine 全局篡改）已分别在 `test_knowledge_tool_isolation.py`（`monkeypatch.setattr("services.knowledge_base.get_global_kb", ...)`）与 `test_agent_session_isolation.py`（模块级临时 `DATABASE_PATH` + `create_all`/`drop_all`，不再篡改模块全局）中消除。4 个安全专项文件以 3 种不同顺序运行：

- 顺序 A（字母序）`knowledge → session → db_config → network_policy`：**40 passed**
- 顺序 B（逆序）`network_policy → db_config → session → knowledge`：**40 passed**
- 顺序 C（轮转）`session → network_policy → knowledge → db_config`：**40 passed**
- 单文件：6 + 6 + 8 + 20 = 40 passed
- 与全量 `pytest tests/` 运行结果一致，无顺序相关污染。

### 16.4 质量门禁实测结果（发布前复核）

- `pytest tests/ -q`：**917 passed, 3 skipped**（基线 866 passed / 3 skipped，净增 51 个测试）。
- `ruff check backend client tests scripts`：All checks passed!
- `python3 -m compileall -q backend/app client/pyside6 scripts`：rc=0。
- `pip check`：No broken requirements found.
- `pip-audit -r requirements.txt -r requirements-dev.txt -r requirements-gui.txt`：No known vulnerabilities found.
- `python scripts/api_route_stats.py --check`：paths=135 operations=159，README route stats are current。

### 16.5 提交信息

- 审查基线 commit：`535f3f527df14057ca2a571de852a412b4861c2a`（master，与 origin/master 一致）。
- 候选提交（当前 HEAD）：`323ee01b96d2f326283cf8757ae07b51cfe19443`（`docs: record candidate commit SHA in remediation report`，本地提交，未推送）；其下的安全功能提交为 `b07121a4114bace8042887c67f67b1101e2468bc`（`feat(security): complete R0-R5 isolation and network hardening`）。

### 16.6 尚未完成的发布验证项

1. Docker/PostgreSQL 单副本 smoke（服务端数据库真实建连、schema 迁移、`_verify_server_schema` 路径）；
2. 本地 SQLite 数据核对（配置切换前的备份、schema 版本与关键表计数比对）；
3. 发布资产绑定（`generate_release_manifest.py`/SBOM/checksum/Release Notes 与候选 SHA/版本绑定及签署）；
4. DNS-rebinding 活体测试（第 16.2 节记录的 TOCTOU 残余风险的实测缓解验证）。

**最终结论：R0–R5 实现完成，候选发布待干净环境和 CI 验证。**

### 16.7 候选发布复核记录（2026-09-02，HEAD=323ee01）

- 复核基线：`master` 分支，HEAD=`323ee01b96d2f326283cf8757ae07b51cfe19443`（本地，未推送）；工作区仅本报告一条修改。
- 质量门禁重跑（当前工作区实测）：`pytest tests/ -q` → **917 passed, 3 skipped**；`ruff check backend client tests scripts` → All checks passed；`python3 -m compileall -q` → rc=0；`pip check` → No broken requirements；`pip-audit`（基础/开发/GUI 三份需求）→ No known vulnerabilities；`scripts/api_route_stats.py --check` → paths=135 operations=159，current。
- 隔离验证重跑：4 个安全专项文件 3 种顺序各 **40 passed**，与全量结果一致，无顺序相关单例污染。
- PostgreSQL 单副本 smoke（postgres:16-alpine，临时容器，端口 55433）：**16/16 PASS** —— alembic 迁移 0001→0002 成功执行；注册/登录；Agent 创建（含 knowledge_config）；Run 创建与查询；跨用户驳回（`SESSION_NOT_FOUND`/`AGENT_NOT_FOUND`/`AGENT_RUN_NOT_FOUND`）；Provider 元数据地址（169.254.169.254）拒绝 `TARGET_NOT_ALLOWED`、公网地址接受；knowledge query 端点可用。
- SQLite 只读核对：Engine URL=`sqlite:///./data/modelforge.db`；已备份至临时目录（sha256 `273f71e10fb079f932bae6dd6ad45d9f46d29b1454029d068bc89b328cbfdbd3`，与源文件一致）；库内仅 `schema_migrations`（0001/0002/0003 三条记录），无业务表 —— 为 2.1 遗留空壳，无需合并，未做任何修改。
- 发布资产：`release-artifacts/`（已被 .gitignore 排除）**尚未绑定候选 SHA 323ee01** —— `checksums.txt` 与 `TEST_RELEASE_NOTES.md` 仍为 v0.1.1-beta.1 内容，SBOM 生成时间为 2026-08-31，早于安全整改；无独立 pip-audit 报告文件。`generate_release_manifest.py` 的绑定逻辑正确（git rev-parse HEAD + APP_VERSION + 工件 sha256），生成执行仍属 16.6 未完成项。
- 未推送远程仓库。

### 16.8 发布资产生成记录（2026-09-02，最终候选代码 HEAD=53e9aa0）

- **最终候选（代码冻结）SHA：`53e9aa0f0880afdaa01f607d0a3c6258dfef4610`**，版本 `0.1.3-beta.1`（`client/pyside6/version.py`）。本小节为收尾文档提交（docs-only），位于候选代码提交之上，不改变候选代码/依赖/测试；发布资产一律绑定候选代码 SHA，不随文档提交漂移。
- **旧资产隔离**：`release-artifacts/legacy-v0.1.1-beta.1/` 收纳全部旧 v0.1.1-beta.1 资产（zip、checksums、TEST_RELEASE_NOTES、旧 SBOM、旧 pip-audit 报告、旧 candidate-metadata.json）仅作历史证据；顶层目录清空后重新生成。
- **再生资产清单**（`release-artifacts/`，gitignore 排除，不进入提交）：
  - `release-manifest.json` —— `git_commit=53e9aa0…`、`version=0.1.3-beta.1`、`platform=macos-arm64`、`artifact=null`（本候选未构建桌面 zip）、`git_tag=null`、`signing=unsigned`、`sbom=sbom.cdx.json`；
  - `sbom.cdx.json` —— CycloneDX 1.5，installed 模式，**92 组件**，含 fastapi/sqlalchemy/httpx/pydantic/uvicorn/psycopg 等关键依赖；source 标注为当前 Python 环境（三份 requirements 全量安装树）；
  - `pip-audit-report.json` / `pip-audit-report.txt` —— 独立审计报告，92 依赖 **0 漏洞**，文本报告记录 “No known vulnerabilities found”；
  - `checksums.txt` —— 上述 5 个文件的 SHA-256 自校验全部 OK；
  - `RELEASE_NOTES_v0.1.3-beta.1.md` —— 候选发布说明（含下载校验指引与已知限制）。
- **资产验证**：manifest SHA 精确等于 53e9aa0；扫描全部新资产无 `0.1.1` 版本声明（Release Notes 中仅以历史基线上下文提及）、无 `852`、无旧 SHA（d90a0d2/323ee01 均未出现）；checksums 重算一致；SBOM 覆盖当前 requirements 依赖。
- **质量门禁最终重跑（全绿）**：`pytest tests/ -q` → **917 passed, 3 skipped in 31.85s**；ruff All checks passed；compileall rc=0；pip check No broken requirements；pip-audit No known vulnerabilities；`api_route_stats.py --check` → 135 paths / 159 operations current。
- **残余风险**：DNS rebinding TOCTOU（16.2 记录）仍未通过 IP 固定完全闭合，活体测试列入部署环境验证项。
- **正式发布状态**：**Go/No-Go 待 CI 结果及最终授权**；本地提交未推送远程。
- 16.6 未完成项状态更新：PG 单副本 smoke（16/16）、SQLite 只读核对、发布资产绑定三项已完成；仅余 DNS-rebinding 活体测试（部署环境项）。
