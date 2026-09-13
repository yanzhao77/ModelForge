# 行为变更说明：V1.1 → V2.0 平台化

> 范围：Agent、Runtime、Models、Knowledge、Workflow、Developer API、Observability、
> Recovery。只记录**使用者/集成方可感知**的变化。

## 1. Agent 与模型绑定

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| 模型引用 | Agent 保存模型**名称**，运行时按名称找后端 | AgentDefinition 新增 `model_id`（Model Registry 主键）；名称若命中注册表会自动提升为 `model_id` |
| 执行入口 | `Agent → Ollama/远程 provider` | `Agent → RuntimeBackedProvider → ModelRuntimeManager → RuntimeAdapter`；本地 GGUF/HF 走统一运行时 |
| 本地工具调用 | 依赖后端原生 tool calling | 本地模型通过 JSON 信封协议（注入 + 解析），同一解析器也被 Workflow LLM 节点复用 |
| Trace | 只有事件流 | 新增 `GET /api/v1/agents/runs/{id}/trace`（run/model/tool/memory span + 原始事件） |
| 定义版本 | 仅创建时写版本 | 每次更新都生成新版本快照 |

**安全修复**：Agent 定义查找现在按用户作用域（`user_id = 调用者 OR 全局`）。
此前同名的跨账号定义可能被另一个账号的 Run 命中。

## 2. 运行时

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| 并发模型 | 同一时刻仅一个已加载模型（加载 B 自动卸载 A） | 多实例并存（默认上限 2，`runtime_max_loaded_models` 可调） |
| 容量不足 | 直接失败 | 先按 LRU 驱逐**空闲**实例；全部忙则进入优先级队列（HIGH/NORMAL/LOW），超时返回 `409 RUNTIME_BUSY` |
| 加载所选引擎 | 由内部硬编码 | 由 Runtime Resolver 决定；`load`/`chat` 可传 `runtime` 覆盖（`llama_cpp` / `transformers`） |
| 不支持组合 | 可能静默尝试 | 显式 `MODEL_FORMAT_UNSUPPORTED`（如 transformers 读 GGUF） |
| 远程模型 | 独立于模型列表 | 出现在同一份 `/api/v1/models`（`source=remote`、`preferred_runtime=remote_openai`），凭据仍不外泄 |

## 3. 对话与外部 API

* `POST /api/v1/chat`、`/chat/stream`、`POST /api/v1/models/{id}/load` 支持 `runtime`；
* 新增 `POST /v1/embeddings`、`GET /v1/agents`、`POST /v1/agents/{id}/runs`、
  `POST /v1/knowledge/search`、`POST /v1/workflows/{id}/runs`、
  `GET /v1/platform/capabilities`；
* `GET /v1/models` 仍然列出注册表模型（含 `model_id`/`capabilities`/`ready`）。

## 4. 训练

* 训练产物注册带能力与元数据（LoRA → `["LORA"]` + `requires_base_model`，全参 →
  `["CHAT","INFERENCE"]`）；产物可直接 Load/Chat/Agent/API。

## 5. 知识库

* 新增 DOCX/CSV 解析；`/knowledge/query`、`/knowledge/answer` 支持
  `retrieval_mode`（`semantic|keyword|hybrid|rerank`，非法值 422）；
* 新增知识库（collection）CRUD 与文档挂载，`GET /knowledge/embedding` 说明当前
  embedding provider 及回退原因；`POST /knowledge/embed` 可独立调用；
* 上传会在任务中心生成 `knowledge_index` 任务（可见分块数与状态）。

## 6. 工作流（新增）

* 新增 `/api/v1/workflows*` 与桌面「工作流」页面；
* 支持顺序/并行/条件/循环/重试/超时/人工审批/多 Agent；
* 控制流表达式为 AST 白名单，禁止 `__import__`、属性逃逸与任意函数调用；
  模板变量仅能读取 `input`/`variables`/`nodes` 数据。

## 7. 包与开发者

* 新增 `/api/v1/packages` 导入/导出（model/agent/tool/workflow）；
* 模型包不含权重与绝对路径，工具包不含实现（只登记权限与 schema）；
  导入会报告缺失依赖。
* 新增 Python SDK `sdk/python/modelforge`。

## 8. 可观测与安全

* 新增 `/api/v1/traces*`、`/api/v1/metrics/overview`、`/api/v1/metrics/resources`、
  `/api/v1/evaluations*`、`/api/v1/security/secrets`；
* TTFT 未采集，接口返回 `ttft_ms: null` 并附带原因（不伪造）；
* Agent Run 的推理租约改为**进入终态即释放**：客户端看到 `COMPLETED` 后立刻
  发起下一次运行不会再遇到 `RUNTIME_BUSY`。

## 9. 启动与恢复

* 启动时统一执行一次幂等恢复（模型扫描/失效标记、下载/训练/Agent Run/工作流
  Run/API 调用结算、运行时资源清理），报告可通过
  `POST /api/v1/system/recovery` 重跑；
* `GET /api/v1/system/hardening` 汇总缓存、运行时、停滞工作流、包与迁移预检。

## 10. 未包含（仍按计划留待后续）

1. Base + LoRA Adapter 运行时挂载；2. Qdrant 等外部向量库；3. Workflow 可视化
节点编辑器；4. 在线 Package Marketplace；5. MLX/vLLM 适配器；
6. 多进程/多节点部署与跨进程租约。

## 11. 验证

| 命令 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q -m "not desktop and not network and not gpu and not real_model"` | 见 `docs/V1_1_TO_V2_0_TEST_REPORT.md` |
| `.venv-gui\Scripts\python.exe -m pytest -q -m desktop` | 见同一报告 |
| `.venv\Scripts\python.exe scripts\api_route_stats.py --check` | 203 paths / 245 operations |
| `.venv\Scripts\python.exe scripts\benchmark_platform.py` | 基线见 V1.9 文档 |
