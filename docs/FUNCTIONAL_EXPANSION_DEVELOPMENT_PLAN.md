# ModelForge 功能扩展技术开发计划

**状态：** 设计稿，尚未进入实现或测试。  
**目标版本：** `v0.1.2+`，按独立功能切片逐步交付。  
**适用端：** FastAPI 后端、SQLite/SQLAlchemy 持久层、PySide6 桌面客户端。  
**核心原则：** 复用已有 Runtime、Agent Run、EventBus、Tool Registry、Scheduler、Memory、Knowledge、Plugin/MCP 和 Models 能力；新增界面及 API 只暴露用户显式授权的控制项，绝不因打开页面、保存草稿或导入模板而自动创建 Agent Run、下载模型或启动训练。

> 当前系统已经具备 Agent Run、事件流、工具注册、人工审批、MCP、调度、跨会话记忆、知识库、训练、模型就绪和远程模型服务等后端基础。下一阶段的关键不在重复造运行时，而在把这些基础能力组织为**可理解、可配置、可追溯且默认安全的桌面工作流**。

## 1. 范围、优先级与交付策略

| 优先级 | 功能切片 | 用户价值 | 现有可复用基础 | 本轮不做内容 |
|---|---|---|---|---|
| P0 | 调度与自动化中心 | 将已有 Scheduler 变成用户可见、可控、可追溯的计划任务体验 | `schedule_once`、`schedule_interval`、Agent Run、事件流 | 不自动启用计划，不接入云端 cron 服务 |
| P0 | Agent 工作台 | 使模板、模型路由、工具权限、人工审批和运行前预览可审阅 | Agent 定义、模型目标、Tool Registry、Policy、Run 回放 | 不以模板导入触发 Run |
| P1 | 记忆与上下文控制中心 | 让用户掌控跨会话记忆和上下文预算 | Memory CRUD/Search、Session/Chat | 不记录或展示 Token、API Key、原始认证头 |
| P1 | 运行产物中心 | 将 Run、训练和知识问答输出形成可管理资产 | AgentEvent、TaskEvent、训练任务、RAG 引用 | 不生成公开分享链接或外传数据 |
| P1 | 知识库集合与范围绑定 | 把文档管理从“全库检索”升级为集合、范围和来源治理 | KnowledgeDocument、Chunk、Query/Answer API | 不引入多租户共享知识库 |
| P2 | 插件与 MCP 管理中心 | 让可插拔能力、作用域、权限和健康状态可见可控 | PluginManager、MCPRegistry、Capability Discovery | 不在页面打开时自动安装/启动插件 |
| P2 | 模型运行洞察 | 基于脱敏聚合指标理解模型可靠性与成本 | Models Readiness、Provider 摘要、Runtime/Chat 错误 | 不保存消息正文或 API Key |

每个切片都采用“**数据与 API → 桌面工作区 → 用户显式操作 → 审计/导出**”的顺序。构建、跨平台签名与真实硬件验证属于独立发行轨道，不阻塞这些功能的架构设计。

## 2. 统一架构约束

### 2.1 领域对象与边界

新增功能必须复用既有的 `user_id` 隔离模型。所有列表、详情、导出、操作、事件流和关联对象均须在服务层按当前用户过滤，不能仅依赖客户端隐藏按钮。任何涉及运行的动作遵循以下层级：

| 动作 | 是否可自动执行 | 需要确认 | 审计事件 |
|---|---:|---|---|
| 查看、搜索、预览、编辑草稿 | 是 | 不需要 | 可选的本地 UI 审计 |
| 保存定义、模板、集合、计划草稿 | 否 | 用户点击保存 | `*.created` / `*.updated` |
| 启用计划 | 否 | 用户明确启用并确认时区/并发策略 | `schedule.enabled` |
| 创建 Agent Run | 否 | 用户点击运行或计划触发 | `agent.run.created` |
| 网络、Shell、文件写、委派等工具动作 | 否 | Policy / Human Gate | `human.approval.*` / `tool.*` |
| 导出资产 | 否 | 用户明确导出 | `artifact.exported` |

### 2.2 通用 API 与 UI 约定

后端 API 使用 `/api/v1`、Pydantic schema、统一错误码和 `user_id` 过滤。长时间操作通过现有 Worker 和 SSE 事件机制展示；页面初始加载、过滤、预览和搜索必须走后台 Worker，禁止阻塞 Qt 主线程。桌面端将新增页面接入主窗口左侧导航，并使用当前 `ui_localizer.py` 的简体中文、英文、日文翻译键；禁止在新增工作区硬编码混合语言文案。

所有可破坏动作使用确认对话框。针对“暂停、删除、撤销、清除、导出、启用计划”等操作，UI 需要显示目标名称、影响范围与能否恢复。页面默认展示空状态、权限/服务错误状态、加载状态和可恢复建议。

### 2.3 数据保留与敏感信息

模型调用正文、API Key、JWT、密码、Cookie、原始 Authorization Header 不能进入新增表、导出包、指标、错误摘要或桌面日志。导出使用统一 `RedactionService`（新建）清理已知密钥格式、环境变量名和值、认证头和 PII 字段。所有时间统一存储 UTC ISO 8601；界面按用户本地时区展示。默认保留策略为：运行元数据和导出记录保留 90 天，聚合指标保留 180 天，用户可随时删除自己拥有的资产；实际清理任务仅在用户明确启用维护计划后执行。

## 3. P0：调度与自动化中心

### 3.1 现状与目标

运行时已有 `schedule_once` 与 `schedule_interval`，并能触发 Agent Run。但当前 Scheduler 是进程内对象，计划状态主要保存在内存，缺少桌面页面、持久化、暂停/恢复、时区、并发策略和运行历史。本切片将其升级为“计划定义 + 调度执行 + Run 关联”的可审阅系统。

### 3.2 数据模型

新增表如下。SQLite 迁移采用现有增量迁移约定，初始字段均有安全默认值。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `scheduled_job` | `id`、`user_id`、`name`、`enabled`、`schedule_kind`、`run_spec_json`、`timezone`、`next_run_at`、`last_run_at`、`concurrency_policy`、`max_failures`、`created_at` | 计划的权威持久化定义 |
| `schedule_execution` | `id`、`job_id`、`agent_run_id`、`triggered_at`、`finished_at`、`outcome`、`error_code`、`attempt` | 每次触发与对应 Agent Run 的审计关联 |
| `schedule_template` | `id`、`user_id`、`name`、`description`、`definition_json`、`version` | 用户可复用计划模板，不含密钥 |

`run_spec_json` 保存 Agent 名称、非敏感模型目标引用、输入模板和 Policy 覆盖；不保存用户消息正文、API Key 或完整聊天历史。`concurrency_policy` 仅允许 `skip`、`queue_one`、`allow_parallel` 三个值，默认 `skip`。第一期只支持一次性、固定间隔和每日/每周简易规则；cron 表达式在专门的第二切片中加入，并需要显示下五次触发时间。

### 3.3 后端服务与 API

新增 `ScheduleService`，负责校验 `run_spec`、计算下次触发时间、同步内存 Scheduler、幂等地记录执行和处理应用重启恢复。应用启动时只恢复 `enabled=true` 的用户计划；恢复行为本身不立即执行过期计划，必须遵守 `misfire_policy`（默认 `skip`）。

| 方法 | 路由 | 行为 |
|---|---|---|
| 创建计划 | `POST /api/v1/agent/schedules` | 创建为 `enabled=false` 草稿；需单独启用 |
| 查询计划 | `GET /api/v1/agent/schedules` | 支持状态、Agent、时区、分页过滤 |
| 更新计划 | `PATCH /api/v1/agent/schedules/{id}` | 更新草稿/禁用计划；变更后重算 next run |
| 启用/暂停 | `POST /{id}/enable`、`POST /{id}/pause` | 显式改变状态并同步内存 Scheduler |
| 运行历史 | `GET /{id}/executions` | 返回执行记录及 `agent_run_id` 链接 |
| 手动触发 | `POST /{id}/run-now` | 必须确认；创建普通 Agent Run 并标记 `manual` |
| 删除 | `DELETE /{id}` | 仅删除计划；保留关联执行审计记录 |

`run-now` 不能绕过模型就绪、Policy、预算或人工审批。计划触发失败时只生成一条失败执行记录，不无限重试；达到 `max_failures` 后自动暂停，并发送现有任务中心可见事件。

### 3.4 桌面交互

新增 `SchedulesPage`，导航名称为“自动化”。顶部提供“新建计划”但默认打开草稿向导。向导步骤为：选择现有 Agent 定义 → 选择已验证模型目标（默认继承 Agent）→ 配置输入 → 选择频率/时区 → 设置并发与失败策略 → 审阅 → 保存草稿。启用为独立按钮，显示下次五次执行时间、潜在并发行为和工具权限摘要。

主列表按“启用、已暂停、失败、即将执行”分组。详情抽屉显示定义版本、运行历史、最近失败解释、关联 Run 回放入口、暂停/恢复/克隆/导出。删除、启用和手动执行均采用确认对话框。任何计划都不会因用户只是切换到自动化页面而运行。

### 3.5 验收标准

功能完成的定义包括：草稿不触发 Run；启用后持久化并在重启后恢复；暂停后不再触发；同一计划的并发策略可解释且可见；失败会写入执行记录而不会暴露敏感输入；用户能从执行记录进入已有 Agent Run 回放；中英日界面完整。

## 4. P0：Agent 工作台

### 4.1 目标

Agent 工作台在当前 Agent 页面基础上引入“定义优先”模型：用户可以管理模板、模型目标、工具权限、人工审批策略、输入变量和定义版本，再显式选择创建 Run。它既服务普通用户快速开始，也服务高级用户审阅执行边界。

### 4.2 数据与配置

现有 Agent `runtime_config` 继续保存 `model_target`、Policy 与工具配置；新增不破坏性字段 `definition_version`、`template_id`、`input_schema_json`、`tool_policy_snapshot_json` 和 `change_note`。如果升级需要版本历史，则新增 `agent_definition_version` 表：每次保存生成不可变快照，当前定义保留指向最新版本的引用。模板采用用户级 `agent_template` 表，允许“官方内置只读 + 用户私有可编辑”两类来源。

模板导入/导出格式为 JSON：`schema_version`、名称、描述、系统提示、输入变量、工具选择、Policy、模型目标偏好和版本信息。导入时永远忽略 API Key、Token、绝对文件路径、计划状态与 Run ID；任何无法识别的高风险工具默认禁用并提示用户审阅。

### 4.3 API 与桌面工作流

新增模板 CRUD、模板克隆、定义版本查询/恢复、输入 schema 预览和策略预览 API。创建 Run 的 `POST /agent/runs` 保持现有语义，但接收可选 `definition_version_id`，运行记录将固定保存定义快照的 ID，保证未来回放的可解释性。

桌面端 `AgentWorkbenchPage` 分为“定义”“模板”“运行历史”三栏。定义编辑器提供模型目标卡片、工具权限矩阵、人工审批规则、输入变量、系统提示和变更说明。右侧审阅面板以自然语言展示“此定义可能访问哪些能力”“哪些行为将等待人工批准”“使用哪个模型目标”“预计的上下文/预算边界”。底部只有“保存草稿”“保存版本”“显式运行”三个不同语义按钮。

### 4.4 验收标准

模板克隆不产生 Run；版本恢复创建新版本而不改写历史 Run；运行回放始终展示原定义版本；禁用高风险工具后不能通过导入绕过；模型目标为用户可用/已验证目标；所有导出默认脱敏。

## 5. P1：记忆与上下文控制中心

### 5.1 目标与数据模型

现有 `Memory` 已支持用户级 CRUD、搜索、重要性和上下文注入。新增的桌面中心不改变默认注入逻辑，而让用户理解和控制它。可选扩展字段包括 `scope`（`global` / `session` / `agent`）、`scope_ref`、`pinned`、`expires_at`、`source_kind` 与 `last_used_at`。如不立即迁移字段，可将扩展元数据安全地保存在 `metadata_json`。

新增 `context_policy` 用户偏好：全局记忆开关、每会话最大记忆条数、最大字符预算、自动提取开关和敏感词排除列表。会话/Agent 可覆盖全局策略，但覆盖必须显示在上下文预览中。

### 5.2 API 与 UI

新增批量更新、批量删除、固定/取消固定、按 scope 过滤、上下文预览和“本次对话将注入哪些记忆”的只读 API。`MemoryCenterPage` 展示按重要性、最近使用、固定状态与来源分类的卡片；详情支持编辑、查看来源、固定、设过期、转移 scope 和删除。上下文预览只显示脱敏后的候选摘要与预算占用，用户点击后才显示完整自有记忆。

### 5.3 隐私与验收

不从 API Key、Token、密码、身份证明或认证头自动提取记忆。清除操作支持“仅当前会话”“仅当前 Agent”“全部我的记忆”三种范围，均要求确认。完成标准是用户可准确判断哪些记忆会影响某会话/Agent，并可在不删除会话的情况下禁用或移除它们。

## 6. P1：运行产物中心

### 6.1 目标

Agent Run、训练任务、任务中心和 RAG 问答目前各自保留事件与日志，但用户无法以统一方式查找“上次产出了什么”。运行产物中心提供对**结果、引用、导出和审计**的统一入口，而不是复制现有 Run 页面。

### 6.2 数据模型与 API

新增 `run_artifact` 表：`id`、`user_id`、`source_kind`、`source_id`、`artifact_type`、`title`、`content_json`、`content_text`、`redacted`、`size_bytes`、`created_at`、`retention_until`。初始类型为 `run_summary`、`final_answer`、`citation_bundle`、`training_summary`、`log_export`、`definition_export`。大文件后续迁移到对象存储；第一期限制单个 JSON/TXT 导出为 10 MB。

API 包括按来源/类型/日期搜索、详情、生成脱敏导出、删除、关联 Run/Task 跳转和批量清理。导出是异步任务，生成后写入产物记录；下载地址使用短期授权，不公开猜测式 URL。

### 6.3 桌面交互

`ArtifactsPage` 使用时间线与列表双视图。筛选项包括来源、类型、模型、Agent、状态和日期。详情展示概览、关联对象、引用来源、脱敏说明和导出选项。用户导出前选择 JSON/TXT，看到将被移除的敏感字段说明；导出不会取消、重试或重新运行原任务。

### 6.4 验收标准

用户可从 Agent Run/训练/知识问答跳入同一产物详情；删除产物不删除原 Run；导出不含密钥、Token 和认证头；产物权限与源对象所有权一致；过期清理有审计事件。

## 7. P1：知识库集合与范围绑定

### 7.1 数据模型

现有 `KnowledgeDocument` 与 `KnowledgeChunk` 面向用户全局知识库。新增 `knowledge_collection`（名称、描述、标签、用户、默认检索策略）与 `knowledge_collection_document`（集合、文档、加入时间、标签）实现多集合归档。文档可加入多个集合；删除文档需要明确处理其全部集合关联。第一期不提供跨用户共享或公开集合。

在 Chat/Agent 的 runtime config 中增加 `knowledge_binding`：`all`、`collections`、`disabled`。当选择 `collections` 时，检索 API 必须按集合成员过滤；RAG 回答返回集合、文档、chunk 和得分来源，方便用户追溯引用。

### 7.2 API 与桌面端

新增集合 CRUD、文档归类、集合统计、集合级 query/answer、Chat/Agent 绑定预览 API。`KnowledgePage` 左侧为集合树，中间为文档与标签，右侧为 chunks、来源和检索预览。Chat 与 Agent 定义中均新增“知识范围”卡片，明确“此配置会检索哪些集合”而不是隐式全库访问。

### 7.3 验收标准

文档可在多个集合中安全引用；集合删除不删除文档本体；绑定集合后 RAG 只从该范围返回来源；用户可追溯每个回答引用的文档/chunk；默认范围仍保持现有全库行为以兼容旧会话。

## 8. P2：插件与 MCP 管理中心

### 8.1 目标

现有 Plugin API 和 MCP server 路由已经支持发现、安装、加载、启停、挂载和工具列举。新增 UI 的使命是使“能力是什么、作用域在哪里、会请求什么权限、是否健康”变得可读，而不是在背景中自动执行安装或启动。

### 8.2 扩展模型与 API

新增非敏感 `plugin_profile`：一组启用的插件/MCP、允许的作用域、工具 allowlist、Policy 覆盖摘要和描述。MCP server 配置只存服务地址、名称、能力摘要和认证方式类型；实际密钥复用既有后端加密存储，不回传客户端。新增 `/plugins/{name}/health`、`/mcp/servers/{name}/health` 和 profile CRUD；health 检查必须由用户点击触发并限流。

### 8.3 桌面端

`ExtensionsPage` 含“已安装”“可发现”“MCP 服务器”“配置档”四个标签。每个插件卡片展示来源、版本、作用域、工具列表、风险权限、最近健康检查和显式的安装/加载/启动状态。所有危险操作显示权限差异；卸载受正在使用的 Agent 定义引用保护，先展示影响范围再允许继续。

## 9. P2：模型运行洞察

### 9.1 数据与采集原则

新增 `model_metric_bucket` 聚合表：`user_id`、`model_target_id`、`bucket_start`、`request_count`、`success_count`、`error_4xx_count`、`error_429_count`、`error_5xx_count`、`timeout_count`、`latency_sum_ms`、`input_tokens_estimate`、`output_tokens_estimate`、`cost_estimate`。该表不存消息正文、提示词、响应文本、API Key 或完整 URL query。采集只发生在已有模型调用完成时，写入失败不能阻塞主调用。

成本估算采用用户可编辑的模型价格表或“未知”状态；对于本地模型显示 `N/A`，不虚构成本。推荐逻辑第一期仅基于用户自己的成功率、P50 延迟、验证状态和预算偏好，输出解释性建议而不是自动切换默认模型。

### 9.2 API 与 UI

新增按模型、日期和错误类型聚合查询 API，以及模型价格/预算偏好 API。`ModelInsightsPage` 展示已验证目标、健康摘要、延迟趋势、错误类型、可用性、token/成本估算和“为什么推荐此模型”。用户可以设置日/周成本提醒阈值，但超阈值默认只提示，不停止调用或修改默认模型。

## 10. 实施顺序与依赖

| 阶段 | 目标 | 关键依赖 | 产出 |
|---|---|---|---|
| A | 调度中心数据/API | Scheduler、Agent Run、EventBus、迁移 | 计划草稿、启用/暂停、执行历史 |
| B | 调度中心桌面工作区 | A、i18n、后台 Worker | 自动化页面与 Run 回放链接 |
| C | Agent 工作台 | 模型就绪、Policy、Tool Registry、Agent 版本快照 | 模板/版本/权限审阅/显式运行 |
| D | 记忆与产物中心 | Memory、AgentEvent、TaskEvent、导出脱敏 | 用户控制记忆、统一产物归档 |
| E | 知识库集合 | KnowledgeDocument/Chunk、Chat/Agent binding | 集合范围与引用追溯 |
| F | 插件/MCP 管理中心 | PluginManager、MCPRegistry、Policy | 扩展清单、健康检查、配置档 |
| G | 模型洞察 | Provider/Runtime/Chat 完成事件 | 脱敏聚合指标与解释性建议 |

每个阶段优先提交数据模型、服务、API schema 和桌面静态界面，再实现操作动作。功能之间不要求引入真实模型、外部硬件、跨平台签名或对外 Release；这些仍由独立发行计划管理。

## 11. 功能验收与禁止行为

| 分类 | 必须满足 | 明确禁止 |
|---|---|---|
| 权限 | 后端按用户隔离；前端只展示允许操作；破坏操作确认 | 仅依赖客户端隐藏权限；越权导出 |
| 运行 | Run、计划启用、手动触发均需显式用户操作 | 打开页面、保存草稿、导入模板时自动运行 |
| 隐私 | API Key/Token/认证头/敏感正文不入新表和导出；聚合指标脱敏 | 记录明文密钥、完整提示词或远程响应正文作为遥测 |
| 可解释性 | 显示模型目标、工具权限、知识范围、上下文预算、计划并发策略 | 隐式切换模型、隐式全库检索、隐式提升工具权限 |
| 多语言 | 新增字符串使用 zh_CN/en_US/ja_JP 翻译键 | 硬编码或中英日混合文案 |
| 兼容性 | 旧 Agent/Chat/Knowledge 默认行为继续可用 | 强制迁移旧定义、修改历史 Run 快照 |

## 12. 当前需要的产品决策

开始实施前需要确认：调度中心是否第一期只支持“单次/固定间隔/每日每周”而不支持 cron；Agent 模板是否允许团队共享还是仅用户私有；运行产物是否默认 90 天保留；知识库集合是否允许一个文档加入多个集合；模型洞察是否仅限本机单用户；以及插件/MCP 的高风险工具是否默认保持禁用。若没有额外决策，本计划采用本文列出的保守默认值。

## 13. 本轮实现记录（未执行测试）

本轮已加入持久化调度草稿、显式启用/暂停、执行审计与桌面自动化工作区；Agent 模板和定义版本快照；控制中心中的记忆、运行产物、知识集合、插件/MCP 配置档和模型洞察入口。新增模型指标接口只读取脱敏聚合桶，尚不采集消息正文或密钥；知识集合以多对多归档基础实现，现有 Agent `knowledge_config` 保持兼容以便下一切片完成范围绑定。

按用户要求，本轮没有执行测试、构建、打包、发布或真实模型调用。代码在进入任何对外版本前仍需完成迁移启动、API/桌面离屏、权限隔离、调度重启恢复和导出脱敏验证。
