# ModelForge 3.x Composable Agent & Tool Plugin 架构

> 本文描述 `backend/app/runtime/plugins/` 与 3.x 加固的真实实现（与代码核对）。
> 演进依据：[MODELFORGE_3_RUNTIME_ARCHITECTURE_AUDIT.md](MODELFORGE_3_RUNTIME_ARCHITECTURE_AUDIT.md)（结论 B：READY WITH REQUIRED HARDENING）。
> 设计理念参考 Cordis / DeepSeek Harness 的 Plugin Composition / Scope / Lifecycle，**不引入、不复制**其代码。
>
> 核心原则：**Agent = Plugin Composition；ToolPlugin = Capability Package；AgentPlugin = Agent Behavior Extension；SkillPlugin = Knowledge / Skill Package**。
> 现有 Runtime 保持稳定；插件层全部 additive，不修改 2.1 API，不建第二套事件系统/工具注册表/运行时。

---

## 1. 阶段落地总览（audit §22 路线图）

| Phase | 内容 | 提交 | 测试 |
|---|---|---|---|
| 3.x-P0 | 加固：Policy 下沉 ToolExecutor / 2.1 路径策略门 / 内存清理 / 事件失败可见 / 终态 try-finally | f7b8095 | +11 |
| 3.x-P1 | PluginScope + PluginContext（作用域 + per-plugin 运行时句柄） | af46ae6 | +9 |
| 3.x-P2 | PluginManager：manifest / 发现 / 依赖 / 生命周期 / 挂载卸载 + plugin.* 事件 + API | 7d78dc8 | +9 |
| 3.x-P3 | AgentProfile 组合 + AgentPlugin（extend_agent 行为扩展） | 9713dd5 | +5 |
| 3.x-P4 | ContextContributor 协议 + SkillPlugin（技能/知识贡献注入） | 0221e04 | +7 |
| 3.x-P5 | Multi-Agent 护栏：parent_run_id / 深度 / 循环 / 子数 / 取消级联 / 预算传播 | 0c49d4c | +7 |
| 3.x-P6 | Capability Discovery（工具/技能/Agent 扩展能力索引） | 9aab7b9 | +4 |

**当前基线：339 测试全绿（原 287 + 52）· 92 路由 · 14 表 · 无生产 2.1 破坏。**

---

## 2. 目录结构（实测）

```text
backend/app/runtime/plugins/
├── __init__.py      # 导出 PluginScope / PluginContext / PluginManager / PluginManifest
├── manifest.py      # PluginManifest（name/version/type/entry/dependencies/permissions/tools/config）
├── scope.py         # PluginScope（作用域内工具挂载/卸载 + 所有权追踪 + 能力注解）
├── context.py       # PluginContext（per-plugin 句柄：注册工具/发布事件/结构化日志）
├── manager.py       # PluginManager（discover/load/start/stop/mount/unmount/unload + 依赖检查）
└── discovery.py     # CapabilityDiscovery（工具/技能/Agent 扩展能力索引）
```

## 3. 核心概念映射

| 概念 | 实现 |
|---|---|
| Plugin | PluginManifest + 加载后的 state（scope/context/module/extension/contributions/status） |
| PluginManifest | manifest.py，filesystem-first（plugin.yaml/plugin.json 随代码分发） |
| PluginContext | context.py，per-plugin 运行时句柄（scope_id、config、publish、register_tool、log） |
| PluginRegistry | PluginManager._plugins（按名索引） |
| PluginLifecycle | manager.py 的 load/start/stop/mount/unmount/unload，事件复用 EventBus |
| PluginDependency | manifest.dependencies + load 时存在性检查 |
| ToolPlugin | type: tool，entry 暴露 get_tools(ctx) / setup(ctx)，工具经 scope 挂载 |
| AgentPlugin | type: agent，entry 暴露 extend_agent(ctx) → 扩展工具/系统提示/策略/知识源 |
| SkillPlugin | type: skill，entry 暴露 contribute(ctx) → ContextSegment 列表 |
| AgentProfile | AgentConfig.plugins[] + _resolve_agent_profile 合并（tools/system_prompt/knowledge/policy/contributions） |
| Capability Discovery | discovery.py + GET /api/v1/plugins/capabilities |
| Dynamic Mount/Unmount | manager.mount/unmount（作用域内工具增删，卸载只删自己拥有的工具） |

---

## 4. 安全执行边界（P0 加固后）

Policy 现在有**两层强制**：

```text
ExecutionEngine._policy_gate（快速失败 + 人工审批门）
    └─ 通过后 → ToolExecutor.run ──► _enforce_policy（权威兜底，直调同样被拦）──► Tool.execute
```

ToolExecutor 内置 _enforce_policy（executor.py）：任何调用路径（引擎循环或未来直接调用）执行前都检查 ctx.policy.check_tool。
2.1 LangGraph 路径（/agent/{name}/chat）在传入 Policy 时工具被 _policy_guard 包裹（agent_engine.py）。

## 5. 作用域（Scope）

PluginScope 解决 audit §13.3 的全局污染问题：

- 工具挂载进**单一 ToolRegistry**（不建第二注册表），但 scope 记录所有权；unmount() 只移除本 scope 的工具，内置工具不受影响。
- 挂载时给 tool.metadata["scope"] 打标，供能力发现与按 scope 过滤。
- 已知限制（P2）：全局注册表按名唯一，两个 scope 挂同名工具会互相覆盖 —— 需插件命名规范（前缀 plugin./agent.）或未来 registry 视图。

## 6. 生命周期与事件（复用单一 EventBus）

plugin.discovered / plugin.loaded / plugin.started / plugin.stopped / plugin.mounted / plugin.unmounted / plugin.failed / plugin.unloaded
全部经现有 EventBus 发布（run_id = plugin:manager 或 plugin:<scope>，各自独立 sequence），**无第二事件系统**。

## 7. Multi-Agent 护栏（P5）

| 护栏 | 实现 |
|---|---|
| parent_run_id | agent_runs.parent_run_id（含启动时 additive 迁移）+ RunRecord/API 透出 |
| 直接自委托 | context.agent_id == agent_id 拒绝 |
| 间接循环 A→B→A | ancestors 链检查（metadata 传递） |
| 深度限制 | delegation_max_depth（默认 3，可 per-agent 配置） |
| 子 Run 数量 | delegation_max_children（默认 5，runtime 计数） |
| 取消传播 | cancel_run 级联取消全部未终态子 Run |
| 预算传播 | remaining_seconds 沿 ancestors 传递，子 Run timeout 取其与自身配置的较小值 |

## 8. 插件 API（additive，/api/v1/plugins/*）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/plugins/discover | 文件系统 manifest 发现 |
| POST | /api/v1/plugins/load | manifest dict 或 manifest_path 加载 |
| POST | /api/v1/plugins/{name}/start / stop / mount / unmount | 生命周期 |
| DELETE | /api/v1/plugins/{name} | 卸载 |
| GET | /api/v1/plugins/capabilities?scope= | 能力索引 |

## 9. 持久化策略（audit §17）

- **文件系统优先**：manifest + entry 代码随插件包分发，不落库。
- **复用现有 Agent 配置**：Agent 与插件的组合关系存 agents.runtime_config.plugins（JSON），无新表。
- 唯一新增列：agent_runs.parent_run_id（additive ALTER 迁移，core/database._additive_migrations）。
- 数据库插件实例表（plugin_instances 等）**暂不需要**；若未来需要运行时实例状态再加。

## 10. 向后兼容

2.1 Chat / Session / Memory / Knowledge / Training / Model / OpenAI API 全部未动；
3.0 Run / Tool / Event API 语义未变（新增 parent_run_id 等可选字段）；
原 287 测试全绿（未修改任何旧测试）。

## 11. 已知边界（延续审计）

| # | 项 | 说明 |
|---|---|---|
| 1 | 全局注册表同名冲突 | scope 级隔离未到 registry 视图；靠命名规范 + 文档（P2） |
| 2 | 插件热卸载对运行中 Agent | 卸载后引用该工具的 Agent 得到 TOOL_NOT_FOUND（记录为工具失败，run 继续） |
| 3 | 插件入口安全性 | entry 为可执行 Python，按"可信任插件源"使用；后续可加签名/校验 |
| 4 | 依赖仅存在性检查 | 无版本语义化解析（可加） |
| 5 | 调度器/插件实例持久化 | Scheduler 任务仍为内存态；插件实例状态未落库（按 §9 决策） |
| 6 | 2.1 LangGraph 路径的 Executor 统一 | P0 已加 Policy 门；完整 Executor 化需 async 化 2.1 路径（保留为后续项） |