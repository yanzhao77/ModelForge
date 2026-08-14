# ModelForge 3.0 Runtime Architecture Audit

> 审计范围：`backend/app/`（runtime/services/api/repositories/models/core）、`client/pyside6/`、`tests/`。
> 审计方式：只读代码 + 依赖/调用/生命周期/事件流分析 + 全量测试运行。**未修改任何生产代码 / 数据库 / API。**
> 基线：`master @ 5801377`（工作区干净）。
> 测试：**287 passed / 0 failed / 0 skipped / 6.01s**（`pytest tests/`，27 个测试文件）。
>
> 文档核对：`TECHNICAL_REPORT.md` / `AGENT_RUNTIME.md` / `API_REFERENCE.md` / `DEVELOPMENT_PLAN.md` 与代码核对结果见 §2.5（DOCUMENTATION DRIFT）。

---

## 1. Executive Summary

ModelForge 3.0 的 Agent Runtime 是一个**结构清晰、职责分离良好、测试覆盖扎实**的本地优先执行平台：
API → AgentRuntime → ExecutionEngine → Ports/Adapters 分层正确，无 FastAPI/SQLAlchemy 反向依赖，
Run 状态全量持久化，Event 单一总线 + 单一 ToolRegistry + 单一 Runtime 符合规范约束，无第二套事件系统/工具注册表/运行时。

**但审计发现 5 个 P1 级问题**，集中在三处：

1. **安全执行边界不在唯一位置**：Policy 只在 ExecutionEngine 内生效，ToolExecutor 本身无 Policy 钩子（`runtime/tools/executor.py` 无任何 policy 引用）；任何直接调用 `ToolExecutor.run()` 的路径都会绕过策略。
2. **存在第二条工具执行路径**：2.1 LangGraph Agent（`services/agent_engine.py` → `AGENT_TOOLS` → `langchain_tool(func)` → ToolNode）绕过 ToolRegistry / ToolExecutor / Policy。`POST /api/v1/agent/{name}/chat` 暴露该路径，`command_execute`（shell）等危险工具在该路径下无策略门。
3. **全局单例状态使插件作用域（Scope）无法落地**：AgentRuntime / EventBus / ToolRegistry / MCPRegistry / PolicyEngine 全部以进程级单例存在；`register_tool` 修改全局注册表会瞬时影响所有 Agent；Plugin 化的 per-plugin context/scope 需要先引入作用域机制。
4. **Multi-Agent 缺乏安全护栏**：`agent.delegate` 不记录 parent_run_id、无委托深度限制、无 A→B→A 间接循环检测、无 child run 数量限制、无 budget/取消传播（取消父 Run 不会取消子 Run）、300s 硬编码等待。
5. **两个 2.1 遗留行为**：`AgentEngine.agents` 内存字典为跨用户共享可变状态（同一 Agent 的对话历史被所有用户共享）；`services/memory.py`、`runtime/tools/legacy.py` 为死代码。

**结论：B. READY WITH REQUIRED HARDENING**（详见 §25）。

架构评分：**B**（地基良好，需定向加固后进入 3.x Plugin 化）。
风险计数：**P0: 0 · P1: 5 · P2: 10 · P3: 8**（详见 §20 风险清单）。

---

## 2. Current Architecture

### 2.1 分层（实测依赖，非推断）

```text
FastAPI 路由层        api/agent.py（20 条 agent 路由）
                          │ 调用（不直接访问 repository / runtime 内部）
服务/单例接线         services/agent_runtime_service.py（build + init singleton）
                          │ 构造 + 注入
运行时门面            runtime/runtime.py  AgentRuntime
                          │ 组合（构造 ExecutionEngine，持有 store/provider 工厂）
执行引擎              runtime/execution.py  ExecutionEngine
                          │ 依赖 Port 协议 + 鸭子类型 runner/builder
Ports                 runtime/ports.py（RunStore/EventStore/AgentStore/Memory/Knowledge/History）
                          │
Adapters              repositories/*（SQLAlchemy）、runtime/tools/*、runtime/models/*、
                      runtime/kb_provider.py、runtime/memory/providers.py
```

### 2.2 关键事实（从 import/调用关系实测）

| 模块 | 依赖 | 反向依赖 | 循环? |
|---|---|---|---|
| `runtime/runtime.py` | run_context/errors/events/execution/metrics/models/state/types；懒加载 tools/mcp/policy/scheduler/ollama | `api/agent.py`、`services/agent_runtime_service.py`、`runtime/tools/delegate.py`(持有 runtime 引用) | **有**：DelegateTool 持有 AgentRuntime 引用（构造期注册，§12） |
| `runtime/execution.py` | run_context/errors/logging/models.base/state | `runtime/runtime.py`（构造 engine） | 无 |
| `runtime/events/bus.py` | types | runtime/execution/agent 服务 | 无 |
| `runtime/tools/registry.py` | base | executor/builtin/mcp/legacy/delegate | 无 |
| `runtime/tools/executor.py` | errors/base/registry | runtime/execution | 无 |
| `runtime/mcp/*` | tools.base、httpx | runtime（懒加载注册） | 无 |
| `runtime/policy/engine.py` | tools.base(PermissionLevel) | runtime/execution | 无 |
| `runtime/scheduler.py` | 无（纯 asyncio） | runtime（trigger 注入） | 无 |
| `services/agent_engine.py`（2.1） | agent_tools(AGENT_TOOLS)、langgraph | api/agent、services/agent_store | 无（但与 3.0 执行链完全平行） |
| `repositories/*` | models.records、core.database | runtime（经 Port） | 无 |

### 2.3 对象生命周期

- **AgentRuntime**：进程级单例，`main.py` lifespan 内 `build_agent_runtime()` → `init_agent_runtime()` → `start()`；进程退出 `shutdown()`。持有：run_store / agent_store / event_bus(+store) / tool_registry / tool_runner / provider_factory / context_builder / policy_engine / metrics / scheduler / engine + 5 个 per-run 字典 + _mcp_registry。
- **Run**：`create_run`（同步持久化 PENDING + spawn 执行任务）→ `execute_run`（幂等守卫 → RUNNING → engine.execute → 终态落库 + 事件 + metrics + flush）。取消经 `cancel_run` 置 token + CANCELLED。
- **Tool**：`register_builtin_tools` 在 runtime 构造时注册 5 个内置工具 + `DelegateTool`；MCP 工具经 `register_mcp_server` 动态注册；生命周期 = 进程生命周期（无动态卸载除 unregister_tool）。
- **EventBus**：随 runtime 单例；writer 任务懒启动；shutdown 时排空。

### 2.4 执行链（实测）

```text
POST /api/v1/agent/runs
  → AgentRuntime.create_run            （DB PENDING + spawn）
  → AgentRuntime.execute_run           （幂等守卫 → RUNNING + run.started）
  → _make_provider → provider_factory  （OllamaProvider / Mock）
  → _build_context → RunContext        （agent 配置 + 运行时限制 + policy + approval_waiter + CancellationToken）
  → ExecutionEngine.execute            （循环：_check → ContextBuilder.build → provider.chat → 事件）
      └─ 有 tool_calls → _policy_gate（Policy.check_tool + 人工门）
           └─ ToolExecutor.run（timeout/retry）→ Tool.execute
  → 终态落库 + run.completed/failed/cancelled + metrics + event_bus.flush
```

### 2.5 DOCUMENTATION DRIFT（文档 vs 代码）

| 文档声明 | 代码实测 | 结论 |
|---|---|---|
| TECHNICAL_REPORT：287 测试 / 84 路由 / 14 表 | 287 passed；84 routes；14 tables | ✅ 一致 |
| TECHNICAL_REPORT：23 类事件 | `EventType.ALL` 长度 23 | ✅ 一致 |
| AGENT_RUNTIME：15 个错误码 | `ERROR_CODES` 长度 15 | ✅ 一致 |
| API_REFERENCE 端点清单 | 全部存在；另存在未列出的 `/knowledge/stats`、`/models/{id}` GET、`/memories/{id}` PATCH、`/plugins/{name}/install`、`/plugins/install-all` | ⚠️ 轻微遗漏（P3） |
| AGENT_RUNTIME：所有 Tool 统一 Executor | 2.1 LangGraph 路径（`/agent/{name}/chat`）直接执行 AGENT_TOOLS，绕过 Executor | ⚠️ **DRIFT（P1，§7.3）** |
| spec 24「取消必须终止当前 Tool」 | 取消仅在循环边界检查；进行中的 Tool（to_thread）不会被中断 | ⚠️ DRIFT（P2，§5.4） |
| spec 41「Child Run 记录 parent_run_id」 | RunRecord 无 parent_run_id 字段 | ⚠️ DRIFT（P1，§12） |

以代码为准。

---

## 3. Runtime Dependency Graph

```text
api/agent.py ──► services/agent_runtime_service ──► runtime/runtime.py ──► runtime/execution.py
     │                     │                            │  │  │  │            │  │  │
     │                     │                            │  │  │  │            │  │  └──► runtime/run_context.py
     │                     │                            │  │  │  └────────────┤  └──► runtime/models/base.py
     │                     │                            │  │  │               └────► runtime/events/bus.py
     │                     │                            │  │  └─────────────────────► runtime/metrics.py
     │                     │                            │  └────────────────────────► runtime/policy/engine.py
     │                     │                            └───────────────────────────► runtime/scheduler.py（trigger=该 runtime）
     │                     │
     │                     └──► repositories/{run,event}_repository ──► models/records ──► core/database
     │                     └──► services/agent_store ──► models/records（agents 表）+ services/agent_engine（内存回退）
     │
     runtime/tools/{registry,executor,builtin,legacy,delegate} ──► services/agent_tools（AGENT_TOOLS）
     runtime/mcp/{client,registry,adapter} ──► runtime/tools/base
     runtime/context/builder ──► runtime/memory/providers、runtime/kb_provider
     services/agent_engine（2.1）──► services/agent_tools（绕过 3.0 链）【见 §7.3】
```

循环依赖（构造期）：`AgentRuntime → ToolRegistry → DelegateTool → AgentRuntime`（显式回指，用于创建子 Run；风险见 §12）。---

## 4. AgentRuntime / ExecutionEngine Audit

### A. 谁依赖谁
`AgentRuntime` 组合并构造 `ExecutionEngine`，注入 event_bus/tool_runner/context_builder/metrics/logger；`ExecutionEngine` 不反向 import runtime，通过 RunContext 鸭子类型字段（`ctx.policy`、`ctx.approval_waiter`）解耦。依赖方向正确。

### B/C. 反向依赖 / 循环依赖
- 无模块级循环（`runtime.py` ↔ `execution.py` 单向）。
- 唯一构造期循环：`DelegateTool(self)` 注册进 ToolRegistry（runtime.py:83）——Tool 持有 Runtime 引用。这是**显式依赖而非架构循环**，但意味着 DelegateTool 无法独立于 Runtime 测试/复用。

### D. 隐式全局状态
见 §13。核心：AgentRuntime 单例、EventBus 单例、ToolRegistry 单例、Metrics 单例、`_created_events` 无限增长。

### E. 跨层直接访问
- `api/agent.py` 只调用 runtime 公开方法，**无** repository/SessionLocal 直接访问 ✅。
- `ExecutionEngine._policy_gate` 通过 `runner.registry`（鸭子类型）反向取 Tool —— 依赖 runner 恰好暴露 registry 属性；自定义 runner（如 LegacyToolRunner）无 registry 时权限信息缺失（P2，§7.2）。

### F. 职责泄漏
- `AgentRuntime` 承担了过多职责：Run 生命周期 + Agent 定义 + 工具注册 + MCP + 调度 + 审批 + 指标。它是"门面"，但已接近 300 行单类，Plugin 化时需要拆出 Scope/Context 容器（P2，§16）。
- `ExecutionEngine` 同时承担策略门（_policy_gate）与执行（tool_runner.run）——策略本应属于 ToolExecutor 或独立 Enforcement 层（P1，§7）。

### G/H. 作为未来 Plugin Extension Point
- **是**：`AgentRuntime` 是自然的 `PluginHost`/`RuntimeContext` 注入点；`ExecutionEngine` 的 `_policy_gate`/`_wait_for_approval` 是拦截器缝隙，可演进为 plugin hook。
- **否**：`ExecutionEngine._tool_schemas`/`_policy_gate` 硬编码单一 policy 对象；Plugin 无法挂多个策略/拦截器，需先引入链式/组合拦截器。

---

## 5. RunContext / Lifecycle Audit

### 5.1 RunContext 是否承担 Run Scope
**基本是**：RunContext 携带 run_id/agent_id/user_id/session_id/input/model/system_prompt/tools/policy/approval_waiter/cancellation/所有限制/记忆与知识配置/metadata —— 数据载体完整。
**不足**：
1. RunContext 不含 ToolRegistry / Provider / 存储引用（由 engine/runtime 持有）——作为"运行作用域"是半成品：Plugin 上下文无法从 ctx 拿到当前注册表/能力集合（P2，§16.4）。
2. `variables` 字典存在但引擎仅写入 `last_tool_output`，无状态恢复机制（P3）。

### 5.2 Cancellation 传播
- 传播路径正确：`cancel_run` → token.cancel() → 引擎循环 `_check` → RunCancelledError → CANCELLED 终态 + 事件。
- **进行中的 Tool 不被中断**：`ToolExecutor.run` 内 `asyncio.wait_for` 只覆盖超时；cancel 到达时已进入 `to_thread` 的函数会执行完才返回（P2，§18）。
- LLM 调用被 `asyncio.wait_for` 包裹，取消/超时会取消内部 coroutine（httpx 可中断）✅。

### 5.3 Tool 失败时 Context 清理
工具失败（ToolDenied/ToolTimeout/ToolNotFound/异常）都在引擎内被捕获并转为 tool 消息 + `tool.call.failed` 事件，状态机继续。ToolExecutionContext 为值对象，无资源需要清理 ✅。

### 5.4 Agent Cancel 时 Tool 是否停止
不停止进行中的 tool（见 5.2）；取消后不会发起新的 tool 调用 ✅。

### 5.5 Nested Run 生命周期
- Child Run 由 `DelegateTool` 经 `runtime.create_run(execute=True)` 创建（独立任务），Parent 通过 0.05s 轮询等待（delegate.py:56-66）。
- **无 parent_run_id 记录**（P1）；**取消不传播到 Child**（P1）；**budget/timeout 不传播**（Child 使用自己 Agent 的 runtime_config，默认 600s）（P1）。详见 §12。

### 5.6 Child Run 泄漏
- Child 有独立任务与 DB 行，Parent 取消/失败后 Child 继续运行直到自己的终态 —— 不会悬挂在内存里，但会**继续消耗资源并产生事件**（P1/P2，§12）。

### 5.7 Run 完成后资源释放
- `_cancellations`/`_running`/`_approvals`/`_approval_grants` 在终态路径清理 ✅。
- **`_created_events` 集合永不清理**（每个 run 一个条目）——长进程内存累积（P2）。
- **`EventBus._sequences` 字典永不清理**（每个 run 一个条目）（P2）。
- **Metrics durations 列表无限增长**（P2）。
- 若 `engine.execute` 之后的 `run_store.update`/事件发布抛异常，`_running`/`_cancellations` 清理代码不执行（无 try/finally 包裹）——低概率泄漏（P2）。

---

## 6. Tool Registry / Executor Audit

### 6.1 执行链（3.0 路径）

```text
Agent（ctx.tools 名字列表）
  → ExecutionEngine._tool_schemas（经 runner.schema 生成 OpenAI schema）
  → LLM 返回 tool_calls
  → ExecutionEngine._policy_gate（Policy.check_tool + 人工门）
  → ExecutionEngine 调 tool_runner.run（ToolExecutor）
      → ToolExecutor：registry.get → wait_for(tool.execute, timeout) → retry 策略
      → Tool.execute（FunctionTool 经 to_thread 调用 AGENT_TOOLS 函数 / MCPToolAdapter 经 MCPClient）
```

### 6.2 关键发现

| # | 发现 | 等级 |
|---|---|---|
| 1 | 3.0 全部 Tool（builtin/MCP）**最终都经 ToolExecutor**，无旁路 ✅ | — |
| 2 | **Policy 不在 Executor 内**：executor.py 无任何 policy 引用；直接调用 `ToolExecutor.run()` 绕过策略 | P1 |
| 3 | **Built-in Tool 不绕过 Registry**：经 registry.schema/registry.get ✅；底层函数仍指向 AGENT_TOOLS（兼容层），改名不影响 | — |
| 4 | **Legacy Tool（2.1 LangGraph 路径）绕过 Registry/Executor/Policy**：`agent_engine._make_langchain_tools` 直接 `AGENT_TOOLS.get(name)` → langchain_tool → ToolNode 同步执行 | P1 |
| 5 | 工具级超时/重试由 Tool 元数据声明，Executor 统一执行 ✅ | — |
| 6 | 工具 schema 来自 `LEGACY_TOOL_SCHEMAS`/FunctionTool 显式声明；无 schema 推导/校验（LLM 参数错误经 TypeError 兜底为 Error 文本） | P3 |

### 6.3 Tool 权限模型
权限级别：READ/WRITE/EXECUTE/NETWORK/SYSTEM/ADMIN（`tools/base.py`）。内置工具声明：filesystem.read=READ，code.search=READ，shell.execute=EXECUTE，web.search=NETWORK，knowledge.search=READ；MCP 工具一律 NETWORK；agent.delegate 无权限声明（默认放行）。

---

## 7. Policy Boundary Audit

### 7.1 真实安全执行边界在哪里

**唯一强制点：`ExecutionEngine._policy_gate`（execution.py:221-236）**，位于"LLM 请求工具 → 执行"之间。
Policy 检查发生在引擎层，而非 ToolExecutor 或 Tool 实现。

```text
Agent ──► ExecutionEngine ──► [Policy.check_tool] ──► ToolExecutor ──► Tool ──► OS/网络
                              ▲ 唯一强制点
```

### 7.2 风险

| # | 风险 | 等级 |
|---|---|---|
| 1 | **绕过路径**：任何直接调用 ToolExecutor.run 的代码（未来 Plugin、工具编排、其他服务）都不经过 Policy | P1 |
| 2 | **Policy 依赖鸭子类型取 Tool**：`_policy_gate` 用 `runner.registry.get(tool_name)` 取权限；若 runner 无 registry 属性（LegacyToolRunner），tool=None → 权限类规则（network/shell/filesystem-write）被跳过，只剩名称级规则 | P2 |
| 3 | **2.1 路径完全无 Policy**：`/agent/{name}/chat`（LangGraph）执行 shell.execute/web_search 等不经任何策略（P1，同 §6.2#4） | P1 |
| 4 | Policy 的 `human_approval_required` 门在引擎内等待，等待超时使用 run 的完整 timeout（双倍预算） | P3 |
| 5 | ToolExecutionContext.permissions 恒为空：`getattr(ctx.policy, "permissions", [])` 而 Policy 无该字段 —— 工具收到的权限列表无意义 | P3 |

### 7.3 覆盖矩阵（network/shell/filesystem/MCP/subprocess/外部 API）

| 能力 | 3.0 Run 路径 | 2.1 Chat 路径（/agent/{name}/chat） |
|---|---|---|
| shell（command_execute） | ✅ 默认拒绝，需 policy.shell_access | ❌ 无策略直接执行 |
| network（web_search） | ✅ 默认拒绝 | ❌ 无策略直接执行 |
| filesystem read（file_read） | ✅ 放行（READ 默认允许） | ❌ 无策略 |
| MCP 工具 | ✅ 经 Policy（NETWORK 默认拒绝） | N/A（不进 LangGraph） |
| subprocess | 仅 command_execute 封装内使用（经 Executor） | 直接 subprocess.run（agent_tools.py） |
| 外部 API | 无直接调用（工具内） | 同左 |

**理想边界**：Policy 应下沉到 ToolExecutor（每个 execute 前强制 check_tool），并让 2.1 路径接入同一 Registry+Executor。当前不满足（P1）。

---

## 8. MCP Architecture Audit

### 8.1 真实关系

```text
MCP Server ──► MCPClient（httpx JSON-RPC）──► MCPToolAdapter（Tool 协议）
                                                 │
                                    AgentRuntime.register_mcp_server（懒建 _mcp_registry）
                                                 │ sync_tools
                                    ToolRegistry.register（source="mcp"，permissions=[NETWORK]）
                                                 │
                                    ToolExecutor（经 ExecutionEngine._policy_gate 后）
```

**结论：MCP 是纯 Tool Provider**，不构成独立执行路径。注册、schema、超时、策略全部复用统一链 ✅。

### 8.2 问题

| # | 问题 | 等级 |
|---|---|---|
| 1 | MCP 注册为**全进程全局**（写进共享 ToolRegistry），无 per-agent/per-run 作用域；卸载需按工具名逐个 unregister，若工具名冲突会误删同名内置工具（unregister 按 canonical 名） | P2 |
| 2 | MCP 工具一律标记 NETWORK —— 未来 MCP server 若提供本地文件/DB 能力，权限模型粒度不足（需 per-tool 权限映射） | P2 |
| 3 | MCPClient 无连接池/复用（每次 RPC 新建 AsyncClient）；无重连/健康检查；server_info 仅初始化时获取 | P3 |
| 4 | MCPRegistry 实例挂在 AgentRuntime 内部（_mcp_registry），无独立生命周期/审计 | P3 |

### 8.3 建议方向
注册 MCP 时保留 server→tools 映射 + 显式权限映射；引入 per-scope（agent/plugin）的注册视图；复用现有 EventBus 发布 `mcp.server.connected` 等事件（不新建事件系统）。---

## 9. Context Engine Audit

### 9.1 现状
`ContextBuilder.build(ctx, working_messages, iteration)` 固定流水线：
`system_prompt → [memory 检索] → [knowledge 检索] → [history 注入] → working_messages → 预算裁剪`。
记忆/知识/历史通过三个 Port（MemoryProvider/KnowledgeProvider/HistoryProvider）注入，Agent 侧仅声明 `memory_config` / `knowledge_config.sources`。

### 9.2 对 Plugin 贡献（Prompt/Knowledge/Tool/Instruction Contribution）的现状判断
| 期望的 Plugin 贡献 | 当前能否安全实现 | 原因 |
|---|---|---|
| PromptContribution | ⚠️ 只能拼进 system_prompt 字符串 | system prompt 组装是单字符串拼接；多插件叠加需约定格式，且无优先级/去重 |
| KnowledgeContribution | ✅ 经 KnowledgeProvider Port 可替换/组合 | 但 Port 是单实例，多插件需组合 Provider |
| ToolContribution | ✅ 经 ToolRegistry.register 可加工具 | 全局注册表（见 §13） |
| InstructionContribution | ❌ 无此概念 | 需在 RunContext/AgentConfig 增加 instructions 槽位 |

### 9.3 Recommended Extension Point（不改代码，仅建议）
在 `ContextBuilder` 增加 `contributors: List[ContextContributor]`（协议：`contribute(ctx) -> list[ContextSegment]`），默认实现 = 现有 memory/knowledge/history 三个内置 contributor。
`ContextSegment = {priority, section, content}`，builder 按 priority 排序合并进 system 块，再走预算裁剪。
这样 AgentPlugin 可以只加 contributor，不改 builder 核心（P2，§16）。

---

## 10. Event System Audit

### 10.1 事实
- **sequence 是 Run 内唯一**（`EventBus._sequences[run_id]` 递增），符合 spec 6（同一 Run 内严格递增）；非全局唯一。
- 事件顺序：`publish` 同步分配 sequence → 分发订阅者 + 入队持久化（FIFO）→ writer 顺序落库；`flush` 排空。存储顺序 = 发布顺序 = sequence 顺序，**不会乱序** ✅。
- SSE：`stream_events` **先订阅后回放**，按 sequence 去重；run 终态 + 队列空 → 结束；10s 心跳。
- resume：`after_sequence` 从 store 回放 `> N` 的事件。

### 10.2 断线可靠性（duplicate / missing / out-of-order）
| 场景 | 行为 | 结论 |
|---|---|---|
| 断线重连（after_sequence=N） | store 回放 >N；重连窗口内已发布未落库的事件会在后续落库，下次回放可补 | ✅ 不丢失（最终一致） |
| 回放 + 实时重复 | 订阅先于回放，回放事件也进队列，循环按 sequence 去重 | ✅ 不重复 |
| 顺序 | 单进程单队列 FIFO | ✅ 不乱序 |
| **持久化失败** | `_writer` 捕获所有异常并静默丢弃（bus.py:53-55）——DB 故障时事件静默丢失，无告警/补偿 | ⚠️ **P2** |

### 10.3 Plugin 生命周期复用现有 EventBus
**可以**：EventType 是开放字符串集合（23 个常量），`publish` 接受任意 event_type —— `plugin.discovered/loaded/started/stopped/mounted/unmounted/failed` 可直接发布，无需第二套事件系统 ✅。
注意：plugin.* 事件需决定 run_id 归属（可用 `correlation_id` 或独立 run_id 如 `plugin:<name>`）；当前 `publish` 的 sequence 按 run_id 分组，插件事件按 plugin 名分组即可。

---

## 11. Scheduler Audit

### 11.1 事实
`Scheduler`（纯 asyncio）持有 `trigger` 回调；runtime 注入 `_scheduler_trigger` → `create_run(execute=True)`。
`Scheduler 不直接执行 Agent` ✅（spec 72 满足）；API：POST/GET/DELETE `/api/v1/agent/schedules`。

### 11.2 耦合度
- 低耦合：Scheduler 只依赖一个可调用 trigger（由 runtime 注入）；runtime.start/shutdown 管理 scheduler 生命周期。
- 但调度任务状态（_jobs/_tasks）**仅内存**，进程重启丢失；无持久化、无 cron、无跨进程（P2，与已知边界文档一致）。
- `schedule_interval` 的循环依赖 `self._started` 标志，stop 后不再触发 ✅。

### 11.3 对 Plugin 化影响
Plugin 可以复用 Scheduler 作为自己的定时入口（schedule_once/interval 接受任意 run_spec），无需改动（P3 建议：调度任务持久化 + job 级幂等）。

---

## 12. Multi-Agent Audit（Multi-Agent Safety Assessment）

### 12.1 事实
`agent.delegate`（runtime/tools/delegate.py）：
- 参数 `{agent_id, task}`；经 `runtime.create_run(execute=True)` 创建 Child Run；以 0.05s 轮询 `get_run` 等待终态（上限 300s）；返回 `[delegated {agent} -> {status}] {output}` 文本。
- 禁止**直接**自委托（`context.agent_id == agent_id` 拒绝）。

### 12.2 安全检查结果

| # | 检查项 | 结果 | 等级 |
|---|---|---|---|
| 1 | 禁止直接自委托 | ✅ 有 | — |
| 2 | 禁止间接循环（A→B→A） | ❌ 无检测；运行期会无限嵌套直到各自 max_iterations 触发 | P1 |
| 3 | delegation depth limit | ❌ 无 | P1 |
| 4 | child run 数量限制 | ❌ 无（单个 delegate 每轮可创建任意多个，且无并发上限） | P1 |
| 5 | timeout 传播 | ❌ Child 用自身 runtime_config（默认 600s），不继承 Parent 剩余预算 | P1 |
| 6 | cancellation 传播 | ❌ 取消 Parent 不会取消 Child（Child 任务独立，token 独立） | P1 |
| 7 | budget 传播 | ❌ 无（token/成本不传播） | P1 |
| 8 | 无限 Agent Chain 风险 | ⚠️ 存在：无深度/数量/总预算限制，链式委托可耗尽资源；间接循环依赖 max_iterations 兜底 | P1 |
| 9 | Child Run 记录 parent_run_id | ❌ RunRecord 无此字段，无血缘可追踪 | P1 |
| 10 | Parent 正确等待 Child | ✅ 轮询等待直至终态（但非结构化等待，0.05s 轮询开销小） | — |
| 11 | 委托等待的 300s 硬编码 | 与 run timeout 无关；Child 超过 300s 时 delegate 提前返回"unknown"状态但 Child 继续运行 | P2 |
| 12 | 轮询 vs 结构化等待 | 建议改为持有 Child task handle 或按 parent_run_id 订阅 Child 终态事件（复用 EventBus） | P3 |

**结论**：Multi-Agent 是"可用但无护栏"的最小实现（符合 spec 73 第一阶段），但**不能直接作为 3.x 插件组合的基础** —— 至少需加 depth/数量/总预算限制、parent_run_id、取消传播（P1）。

---

## 13. Global State Audit

### 13.1 进程级单例清单（实测）

| 位置 | 单例 | 状态 | 影响 |
|---|---|---|---|
| services/agent_runtime_service.py | `_runtime`（AgentRuntime） | 模块级 | 全局运行时；所有 Run/Tool/MCP/Scheduler 状态集中 |
| runtime/runtime.py（实例字段） | `_cancellations/_running/_approvals/_approval_grants/_created_events` | per-run 键控 | ✅ 无跨 Run 串扰；但 `_created_events` 无限增长 |
| runtime/events/bus.py（实例字段） | `_sequences/_subscribers/_queue` | per-run 键控 sequence | ✅ 无串扰；`_sequences` 无限增长 |
| runtime/tools/registry.py（实例字段） | `_tools/_aliases` | 全局注册表 | **注册/卸载即时影响所有 Agent/Run** |
| runtime/metrics.py | counters/durations | 全局 | durations 无限增长 |
| runtime/mcp/registry.py | `_servers`（挂在 runtime._mcp_registry） | 全局 | 同上 |
| services/agent_engine.py | `_engine`（AgentEngine） | 模块级 | **agents[name][messages] 跨用户共享**（2.1 路径） |
| api/agent.py / api/runtime.py / api/knowledge.py / api/plugin.py | `_runtime/_agent_engine/_knowledge_base/_plugin_manager` | 模块级注入点 | 测试友好但进程全局 |
| services/knowledge_base.py | `_kb` | 模块级 | RAG 全局单例 |
| services/runtime_registry.py | `registry` | 模块级 | 模型运行时注册表 |
| services/downloader.py | `downloader` | 模块级 | 下载任务（内存态） |
| core/config.py / core/database.py | `settings` / `engine` | 模块级 | 配置/DB 引擎（合理） |

### 13.2 状态串扰结论

| 问题 | 是否存在 | 说明 |
|---|---|---|
| Run A 状态影响 Run B | ✅ 隔离（per-run 字典 + DB 行） | 唯一例外：全局 metrics 计数共享（合理） |
| Agent A 状态影响 Agent B | ⚠️ 2.1 路径存在 | AgentEngine.agents 内存字典跨用户/跨会话共享；3.0 路径无（AgentConfig 为不可变数据） |
| Plugin A 状态影响 Plugin B | ❌（尚未有 Plugin） | **未来风险**：无 per-plugin 作用域，任何全局注册都会互相可见 |

### 13.3 对 Plugin 化的关键结论
现有架构无法直接支撑 per-plugin scope：Plugin 需要"挂到某个 Agent/作用域"而不污染全局。
必须引入 **Scope 概念**（最小：`scope_id` → 子注册表/子上下文），或以 **AgentProfile 携带工具/插件列表**（复用现有 `AgentConfig.tools` 列表语义）实现组合隔离（P1，§16）。---

## 14. Database Boundary Audit

### 14.1 现状（14 表）
`users/sessions/messages/memories/models/agents/api_keys/datasets/train_tasks/knowledge_documents/knowledge_chunks`（11 张 2.1 表）
+ `agent_runs/agent_events/tools`（3 张 3.0 表）。

| 表 | 归属 | 关键列/索引 | 状态 |
|---|---|---|---|
| agent_runs | 3.0 | run_id(uniq)/agent_id/user_id/session_id/status/input/output/error/token_usage/tool_call_count/iteration_count/meta；(user_id,created_at) 联合索引 | ✅ |
| agent_events | 3.0 | (run_id,sequence) 联合索引 | ✅ |
| tools | 3.0 | name(uniq) | ⚠️ **只有 builtin 注册进内存注册表，表本身无写入**（预留） |
| agents | 2.1 扩展 | policy/runtime_config/knowledge_config/description/status | ⚠️ 无独立迁移（create_all）；旧库需重建或手工 ALTER |

### 14.2 未来 Plugin 数据需求判断
**第一选择：Filesystem / Manifest / Code Metadata**（推荐）：
- PluginManifest（plugin.yaml/json）：name/version/dependencies/permissions/entry —— 应放在文件系统，随包分发。
- Plugin 代码即元数据：capabilities 可从 Tool/contributor 类静态推导。

**第二选择：复用现有 Agent 配置**：
- Agent 已可声明 `tools`、`policy`、`runtime_config` —— **组合**（哪个 Agent 挂哪些 Plugin）可复用 `agents.policy/tools` JSON 列，无需新表。

**最后才 Database**：
- 仅当需要**运行时实例状态**（plugin_instances：已挂载/启用状态、依赖版本解析结果、权限授予记录）才建表。
- 结论：**3.x 第一阶段不需要新表**；`tools` 表可作为 tool 元数据持久化目标（可选）。

### 14.3 必须/不应持久化
| 必须持久化 | 不应持久化 |
|---|---|
| Agent ↔ Plugin 组合关系（可存 agents 配置 JSON） | Plugin 内部运行状态（内存 scope 即可） |
| 权限授予（可存 policy JSON） | 一次性执行上下文（RunContext） |
| 插件版本/依赖锁定（manifest 文件） | 临时订阅者/拦截器 |
| 事件审计（已有 agent_events） | 实时 SSE 游标（可用 after_sequence 恢复） |

---

## 15. API Boundary Audit

### 15.1 事实
- 84 路由：2.1（auth/sessions/memories/models/runtime/chat/knowledge/datasets/train/plugins/system/openai）+ 3.0（agent/* 20 条）。
- `api/agent.py` 与 runtime 之间为纯方法调用（无 repository 直连）✅；所有权校验在 runtime.get_run 内（user_id 隔离）✅。
- OpenAI 兼容端点（/v1/*）不触碰 Agent Runtime ✅。

### 15.2 Plugin 化对 API 的影响
| API | 兼容性 | 3.x 建议 |
|---|---|---|
| /agent/runs*（Run API） | 保持 | 可增补 parent_run_id、delegate 相关字段（additive） |
| /agent/tools | 保持 | 可扩展为按 scope/plugin 过滤（additive） |
| /agent/create | 保持 | 可增加 plugins 字段（additive） |
| Chat/Session/Memory/Knowledge/Training/Model/OpenAI | 保持 | 不动 |

**结论：无需 API Rewrite；3.x 全部走 additive 扩展** ✅（P1 项为行为加固，非 API 变更）。---

## 16. Extension Point Analysis（未来插件扩展点）

> 以下均为**建议**（本阶段不改代码）。Current Location = 现有代码中的最佳接缝。

| # | Extension Point | Current Location | Current API | Recommended Extension Point | Required Refactor | Risk | Priority |
|---|---|---|---|---|---|---|---|
| 1 | ToolPlugin | `runtime/tools/registry.py` | `ToolRegistry.register(tool, aliases)` | 增加 `ToolPlugin` 包装（manifest + 元数据 + 卸载回调）；注册时带 `scope` | 注册表加 scope 维度（或按 Agent 过滤视图） | M | P1 |
| 2 | AgentPlugin | `runtime/types.py` AgentConfig；`services/agent_store.py` | `AgentConfig.{tools,policy,runtime_config}` | AgentConfig 增加 `plugins: list[PluginRef]`；AgentPlugin = 行为扩展（拦截器/贡献器/工具集合） | 无破坏性变更（additive 字段） | L | P1 |
| 3 | SkillPlugin | `runtime/context/builder.py`（knowledge provider 槽） | `knowledge_config.sources` | SkillPlugin = KnowledgeContribution + 指令片段；走 §9.3 contributor 协议 | ContextBuilder 加 contributors | M | P2 |
| 4 | PluginContext | `runtime/run_context.py` | RunContext（纯数据） | 新增 `PluginContext`（per-run/per-scope 容器：注册表视图 + 资源句柄 + 取消）+ 注入 RunContext | runtime 构造时创建 scope | M | P1 |
| 5 | PluginLifecycle | 无（仅 runtime.start/shutdown） | — | 新增 `PluginManager`（load/unload/start/stop），事件复用 EventBus（plugin.* 类型） | 新模块（服务层），不侵入 runtime 核心 | M | P1 |
| 6 | PluginDependency | 无 | — | manifest 声明依赖；解析在 PluginManager.load 阶段 | 新模块 | M | P2 |
| 7 | PluginPermission | `runtime/policy/engine.py` Policy | `Policy.check_tool(ctx, name, tool)` | 权限模型从 tool-name 扩展为 capability 级（plugin 声明所需能力，按 plugin 授予）；Policy 下沉到 Executor | Policy 迁移（P1） | H | P1 |
| 8 | AgentComposition | `AgentConfig.tools`（名字列表） | — | AgentProfile = {model, tools, plugins, policy, knowledge, memory}；组合即合并 profile | 新增 profile 解析层（additive） | M | P1 |
| 9 | Capability Discovery | `list_tools()` / `ToolRegistry` | — | `discover_capabilities(scope)`：扫描已加载插件贡献的工具/技能/贡献器，生成能力索引 | 新模块（只读聚合） | L | P2 |
| 10 | Plugin Mount / Unmount | `register_tool` / `unregister_tool` / `register_mcp_server` | — | `mount(plugin, scope)` / `unmount(plugin, scope)`：注册+事件+清理；以 scope 隔离避免全局污染 | 需 scope 机制（P1） | H | P1 |

---

## 17. Plugin Architecture Readiness（核心结论）

| 维度 | 现状 | 3.x 就绪度 |
|---|---|---|
| Tool 注册缝 | ToolRegistry.register（无 scope、无卸载语义） | ✅ 基本可扩展，需 scope |
| 模型 Provider | ModelProvider 协议（Ollama/Mock） | ✅ 可插拔 |
| 上下文贡献 | ContextBuilder 三 Port | ⚠️ 需 contributor 协议 |
| 事件 | 单一 EventBus，开放 event_type | ✅ 可直接承载 plugin.* |
| 策略 | Policy 按 Agent 合并 | ⚠️ 需下沉到 Executor + capability 化 |
| 生命周期 | runtime.start/shutdown | ❌ 无插件生命周期管理 |
| 依赖 | 无 | ❌ 需 manifest 解析 |
| 作用域 | 全进程单例 | ❌ 最大缺口（§13.3） |
| 发现 | list_tools 静态 | ⚠️ 需动态能力索引 |
| 多 Agent | delegate 无护栏 | ❌ 需深度/预算/取消传播 |
| 组合 | AgentConfig.tools 列表 | ✅ 可扩展为 profile |

**结论**：ToolRegistry、ModelProvider、EventBus、AgentConfig 提供了 4 个可靠接缝；但 **Scope、PluginLifecycle、Policy 下沉、Multi-Agent 护栏** 4 项为硬缺口。
因此整体判为 **B（需定向加固）** 而非 A。---

## 18. Technical Debt

| # | 债务 | 等级 | 位置 |
|---|---|---|---|
| 1 | 进行中的 Tool 无法被取消（to_thread 执行完才返回） | P2 | execution.py:150 / tools/executor.py |
| 2 | `_created_events` / `EventBus._sequences` / metrics durations 无限增长 | P2 | runtime.py / bus.py / metrics.py |
| 3 | 事件持久化写失败被静默吞掉（无告警/重试/补偿） | P2 | bus.py:53-55 |
| 4 | execute_run 终态段无 try/finally，update/发布异常时 map 泄漏 | P2 | runtime.py:201-217 |
| 5 | `services/memory.py` 死代码（无任何引用） | P3 | services/memory.py |
| 6 | `runtime/tools/legacy.py` 死代码（保留兼容） | P3 | runtime/tools/legacy.py |
| 7 | `_spawn` 在无事件循环时静默吞掉 RuntimeError，Run 卡 PENDING | P3 | runtime.py:537-543 |
| 8 | scheduler.trigger 双重注入（runtime __init__ + build_agent_runtime） | P3 | runtime.py:95 / agent_runtime_service.py |
| 9 | ToolExecutionContext.permissions 恒为空（Policy 无 permissions 字段） | P3 | execution.py:136 / policy/engine.py |
| 10 | 审批等待用满 run timeout（双倍预算） | P3 | runtime.py:301 |
| 11 | agents 表无迁移；旧库升级需重建 | P2 | models/records.py |
| 12 | Scheduler 任务仅内存，重启丢失 | P2 | runtime/scheduler.py |
| 13 | 事件无自动清理任务（delete_older_than 未接线） | P2 | repositories/event_repository.py |
| 14 | AgentEngine.agents 内存字典跨用户共享（2.1 路径） | P2 | services/agent_engine.py:66 |

---

## 19. Architecture Risks

| # | 风险 | 影响 | 等级 |
|---|---|---|---|
| R1 | Policy 仅在引擎层强制；Executor 直调绕过 | 未来任何不经过 ExecutionEngine 的工具调用无安全门 | P1 |
| R2 | 2.1 LangGraph 路径无 Policy/Executor/Registry | 已暴露的 `/agent/{name}/chat` 可执行 shell/网络工具（若 Agent 配置了这些工具） | P1 |
| R3 | 全局单例 + 无 Scope | Plugin 无法隔离；挂载/卸载会瞬时影响所有 Agent | P1 |
| R4 | Multi-Agent 无深度/数量/预算/取消护栏 | 链式委托、间接循环、资源耗尽 | P1 |
| R5 | 事件写失败静默 | 审计数据丢失无感知 | P2 |
| R6 | 内存态字典增长 | 长进程内存缓慢增长 | P2 |
| R7 | Run 取消不终止进行中的工具 | 取消后工具副作用仍发生（如 shell 命令继续执行） | P2 |
| R8 | Child Run 无 parent_run_id | 无法审计/治理委托链 | P1 |

---

## 20. Recommended Refactoring（按优先级，供 3.x 参考，本阶段不实施）

### 20.1 P1 级（3.x 前置）
1. **Policy 下沉到 ToolExecutor**：`ToolExecutor.run` 内强制 `policy.check_tool`（将 ctx.policy 传入 executor）；ExecutionEngine 只保留人工门。消除直调绕过路径。
2. **统一工具执行路径**：2.1 `agent_engine._make_langchain_tools` 改为从 ToolRegistry 取工具（langchain 适配层包住 `Tool.execute`），或让 2.1 chat 也走 3.0 runner。
3. **引入 Scope 机制**：最小方案 = `AgentRuntime` 增加 `scope_id → (子 ToolRegistry 视图 / 子 Context)`；或复用 `AgentConfig.tools` + `policy.allowed_tools` 实现组合隔离（先文档后代码）。
4. **Multi-Agent 护栏**：RunRecord 增 `parent_run_id`；DelegateTool 注入 `max_depth`/`max_children`/预算；取消传播（Parent token 取消时级联 Child）；间接循环检测（祖先链检查）。
5. **PluginManager（新模块）**：manifest 解析 + load/unload + 生命周期事件（复用 EventBus）+ 依赖解析。

### 20.2 P2 级（加固）
6. 内存字典清理：`_created_events`/`_sequences` 随 run 终态清理；metrics 提供 reset/上限。
7. 事件持久化失败重试 + 告警日志；bus 暴露 failed 计数。
8. execute_run 终态段包 try/finally。
9. 取消进行中工具：Tool 执行改为可取消协程（`asyncio.shield` + token 检查点）或文档明确"工具不可中断"。
10. agents 表迁移策略（Alembic 基线 或 启动时 ALTER）。
11. Scheduler 任务持久化 + job 幂等。
12. 事件自动清理定时任务（复用 Scheduler）。

### 20.3 P3 级（清理）
13. 删死代码（services/memory.py；legacy.py 标注 deprecated）。
14. `_spawn` 无 loop 时告警。
15. 移除 scheduler.trigger 双重注入。
16. ToolExecutionContext.permissions 接通 Policy；或删字段。

---

## 21. ModelForge 3.x Plugin Migration Strategy

原则（与审计结论一致）：**增量、additive、不重写、不引入 Cordis 本体，只吸收理念**。

```text
3.0（现状）                 3.x 目标
─────────────────          ─────────────────
ToolRegistry（全局）   →    ToolRegistry + Scope 视图（per-agent/plugin）
AgentConfig（数据）    →    AgentConfig + plugins[] + AgentProfile 组合
ContextBuilder（3 Port）→   ContextBuilder + ContextContributor 协议（默认=现有 3 Port）
EventBus（开放类型）   →    直接承载 plugin.* 事件（不新建）
Policy（引擎内）       →    Policy 下沉 Executor + capability 级权限
Runtime 单例           →    Runtime 门面保留；PluginManager 作为旁路服务持有生命周期
DelegateTool（无护栏） →    带 parent_run_id / depth / budget / 取消传播
```

**迁移顺序**：先加固（§20.1 P1），再叠加 PluginManager（纯新增模块 + 新 API 前缀 `/api/v1/plugins` 或复用现有 plugin 路由），最后按 Plugin 类型（Tool → Agent → Skill）逐步开放。---

## 22. Recommended Phase Plan（供审核，不实施）

| Phase | 内容 | 产出 | 依赖 |
|---|---|---|---|
| 3.x-P0 | 加固：Policy 下沉 Executor + 2.1 路径统一 + 内存清理 + 事件失败可见 | 安全边界唯一化 | 无 |
| 3.x-P1 | Scope 机制 + PluginContext | per-scope 注册/上下文 | P0 |
| 3.x-P2 | PluginManager：manifest/生命周期/依赖/挂载卸载（复用 EventBus 事件） | 首个 ToolPlugin | P1 |
| 3.x-P3 | AgentProfile 组合 + AgentPlugin | 组合式 Agent | P1-P2 |
| 3.x-P4 | ContextContributor + SkillPlugin | 技能/知识包 | P2 |
| 3.x-P5 | Multi-Agent 护栏（parent_run_id/深度/预算/取消传播） | 安全委托链 | P0-P2 并行 |
| 3.x-P6 | Capability Discovery + 插件商店（文件系统 manifest） | 动态能力索引 | P2-P5 |

每个 Phase 保持：旧测试全绿 + 新增测试 + 文档同步（沿用 3.0 的 DoD）。

---

## 23. Backward Compatibility Strategy

| 面 | 3.x 策略 | 保证 |
|---|---|---|
| Tool API | `Tool` 协议不变；新增 `ToolPlugin` 包装层 | 现有 5 工具 + 测试不动 |
| Agent API | `/agent/create` 增字段（additive）；`/agent/list` 返回兼容 | 2.1 LangGraph chat 保留 |
| Run API | `/agent/runs*` 语义不变；增 parent_run_id 等可选字段 | 客户端兼容 |
| Chat / Session / Memory / Knowledge / Training / Model / OpenAI | 完全不动 | 原 152 测试全绿 |
| 配置 | config.yaml 增 plugin 段（additive） | 默认行为不变 |
| 数据库 | 第一阶段不加表；如需实例状态再加 | 现有 14 表不动 |
| 事件 | plugin.* 为新增 event_type | 现有 23 类不变 |

**明确不做**：大规模 API Rewrite、删除旧端点、改 Run 状态机、改事件序列语义。

---

## 24. Final Architecture Recommendation

1. **保留**当前分层（API → Service → Runtime → ExecutionEngine → Ports/Adapters）与单一 EventBus / 单一 ToolRegistry / 单一 Runtime。
2. **优先修复** R1（Policy 下沉）与 R2（2.1 路径统一）—— 这是安全边界问题，应作为 3.x 开发的第一批工作。
3. **引入 Scope 而非复制**：以最小侵入（AgentConfig 组合 + 注册表视图）实现插件隔离，不引入 Cordis。
4. **插件生命周期走新模块**（PluginManager），不把插件逻辑塞进 AgentRuntime。
5. **事件全部复用 EventBus**（plugin.discovered/loaded/started/stopped/mounted/unmounted/failed），不建第二事件系统。
6. **持久化以文件系统 manifest 优先**，数据库仅在有实例状态需求时追加。---

## 25. Audit Conclusion

### 25.1 结论

**B. READY WITH REQUIRED HARDENING**

原因：

1. **地基正确**：分层、职责、测试（287 全绿）、单一运行时/注册表/事件总线、Run 隔离、用户隔离 —— 这是可靠的 3.x 起点。
2. **4 个可靠接缝**已存在：ToolRegistry.register、ModelProvider、EventBus（开放 event_type）、AgentConfig（组合式字段）。
3. **但 4 项硬缺口**阻碍直接进入 3.x Plugin 开发：
   - 安全执行边界不唯一（Policy 在引擎层，Executor 可绕过；2.1 路径完全无策略）→ P1
   - 无 Scope/插件作用域（全局单例状态）→ P1
   - 无 Plugin 生命周期/依赖/发现抽象 → P1（需新增模块，属正常开发，但需先定义 Scope）
   - Multi-Agent 无护栏（parent_run_id/深度/预算/取消传播缺失）→ P1
4. 结论不是 A 的原因：**安全边界与作用域是架构性问题**，不是"再加几个类"能补的；3.x 应先在 P0 加固上投入，再叠加插件层。

### 25.2 测试结果（审计未修改任何生产代码）

```text
pytest tests/                 → 287 passed / 0 failed / 0 skipped / 6.01s（27 个文件）
测试文件数量                  → 27
路由总数                      → 84（agent 20）
数据库表                      → 14
事件类型                      → 23，错误码 15
生产代码变更                  → NONE（本审计只读）
```

### 25.3 风险统计

| 等级 | 数量 | 关键项 |
|---|---|---|
| P0 | **0** | P0: NONE |
| P1 | **5** | Policy 位置 / 2.1 绕过 / Scope 缺失 / Multi-Agent 护栏 / parent_run_id |
| P2 | **10** | 内存增长 / 事件写失败静默 / 取消不终止工具 / agents 迁移 / 调度持久化 / 事件清理 / 2.1 共享消息 / 终态无 try/finally / MCP 全局注册 / tools 表未用 |
| P3 | **8** | 死代码 / 双 trigger 注入 / permissions 空字段 / 审批双倍预算 / API_REFERENCE 遗漏 / schema 无校验 / MCPClient 无连接池 / 轮询等待 |

### 25.4 最终指标

```text
AUDIT COMPLETE
- Test Result      : 287 passed / 0 failed / 0 skipped (6.01s)
- Architecture Grade: B
- P0 Count         : 0
- P1 Count         : 5
- P2 Count         : 10
- P3 Count         : 8
- Plugin Readiness : B（需先完成 P0 加固：Policy 下沉 / 统一执行路径 / Scope / Multi-Agent 护栏）
- Final Recommendation: B. READY WITH REQUIRED HARDENING
```