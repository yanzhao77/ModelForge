# 行为变更说明：统一模型运行时（V1.0 Unified Model Runtime）

> 范围：模型注册中心、运行时管理器、Chat / Training / OpenAI 兼容 API
> 与桌面端模型中心、对话、运行时、训练页面。
> 本文只记录**使用者可感知**的语义变化与验证方式，技术细节见
> `docs/MODEL_RUNTIME_ARCHITECTURE.md`。

## 1. 模型状态与可用性

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| 状态词表 | 只有 `available` | `discovered / installed / ready / loading / loaded / unloading / load_failed / invalid`，`available` 仍被接受并等价于 `ready` |
| 文件缺失 | 记录仍为 `available`，被当作可用 | 读取详情或刷新时标记为 `invalid`，且不再出现在 readiness `targets`、默认模型候选、Agent `model_target` 候选中 |
| 刚登记但文件尚未落盘 | 状态 `available` | 状态 `installed`，`ready=false`，不会被当作可用目标 |

影响：显式登记一个"尚不存在的路径"不再被当成已就绪模型。
用例已调整为"先落盘再登记"，并新增反向用例
`test_missing_model_file_is_not_ready` 固化新规则。

## 2. 模型能力（capability）

* 新增能力字段：`CHAT / INFERENCE / TRAINING / LORA / VISION / EMBEDDING / AUDIO / IMAGE`；
* 能力由格式与来源推导，GGUF 只得到 `CHAT` + `INFERENCE`；
* LoRA 产物只得到 `LORA`，并标记 `requires_base_model`（运行时尚未支持
  Base + Adapter 挂载，不会假装可以直接聊天）；
* 模型 API 新增 `capability` 过滤参数。

## 3. 下载完成后自动注册

下载任务进入 `COMPLETED` 后会调用模型注册中心，把落盘的 GGUF / 训练目录
登记为模型（`provider = "download"`，能力自动推导）。重复下载同一仓库只更新
既有记录。注册失败不会把已完成的下载变成失败：文件仍在磁盘，可再次扫描。

## 4. 加载 / 卸载

* 新增模型级接口：`POST /api/v1/models/{model_id}/load|unload`、
  `GET /api/v1/models/{model_id}/runtime`、`GET /api/v1/runtime`；
* 同一时刻只允许一个本地模型处于 `loaded`；加载第二个模型会先卸载第一个；
* 加载中的重复请求返回 `409 MODEL_ALREADY_LOADING`，请求进行中的卸载返回
  `409 RUNTIME_BUSY`；
* 已加载的模型不能直接删除（`409 MODEL_ALREADY_LOADED`）；
* **权限变化**：模型级加载/卸载接口面向已登录用户，不再要求
  `runtime_admin_usernames`。跨账号互斥仍由进程级推理租约保证
  （`RUNTIME_BUSY`），与 `/api/v1/chat` 的既有语义一致。

## 5. 对话

* `POST /api/v1/chat`、`/api/v1/chat/stream` 新增可选 `model_id`；
* 传 `model_id` 时由运行时管理器解析路径并**自动加载**，切换模型不会复用旧实例；
* 只传 `model`（未注册名称，例如 Ollama 标签）时保持原有后端行为。

## 6. 训练

* `POST /api/v1/train/start` 新增 `base_model_id`（优先），`base_model` 变为可选文本；
* 后端强制校验 `TRAINING` 能力：纯 GGUF 推理模型会被拒绝
  （`TRAINING_START_REJECTED`），不再只依赖界面过滤；
* 子进程使用注册表解析出的**路径**，任务记录保存**显示名**；
* 训练产物注册后带能力与元数据：`lora → ["LORA"]`，
  `full → ["CHAT","INFERENCE"]`，并记录 `base_model_id` /
  `training_task_id` / `dataset_id` / `created_at`。

## 7. OpenAI 兼容接口

* `GET /v1/models` 现在返回注册中心中的模型（附带 `model_id` /
  `capabilities` / `ready`）；注册表为空时仍返回历史占位项 `default-model`；
* `POST /v1/chat/completions` 先经 ModelResolver 命中注册模型时使用统一的
  运行时管理器（与 Chat 界面共享同一实例），未命中时回落原有后端。

## 8. 默认模型

* 新增 `GET /api/v1/models/default` 与 `POST /api/v1/models/{model_id}/default`；
* 默认模型是用户偏好，与"当前已加载模型"相互独立；
* 删除默认模型时同步清除默认偏好，不会留下悬空引用。

## 9. 数据库

`models` 表新增：`display_name`、`size_bytes`、`capabilities`、
`model_metadata`、`base_model_id`、`parent_model_id`、`updated_time`，
以及 `ix_models_status`、`ix_models_base_model_id` 索引。

* SQLite：启动时按 `schema_migrations` 增量执行 `ALTER TABLE`；
* PostgreSQL：`alembic upgrade head`（`0003_model_runtime`），并按 `format`
  回填 `capabilities`。

旧数据无需人工处理；`ModelRegistry.backfill_capabilities()` 可补齐缺少能力的记录，
无法判断时统一为 `INFERENCE`（不会猜测 `TRAINING`）。

## 10. 未包含

1. 不实现多模型并存、LRU 或复杂显存调度；
2. 不实现 Base + LoRA Adapter 挂载；
3. 不重写下载、训练算法、Chat Memory/History、Dataset 逻辑；
4. 不移动模型文件；修改模型目录后旧目录中的模型会从列表消失，需要重新扫描。

## 11. 验证

| 验证项 | 命令 | 结果 |
|---|---|---|
| 新增用例（注册中心/运行时/API/集成/Chat/OpenAI/E2E） | `.venv\Scripts\python.exe -m pytest -q tests/test_model_registry.py tests/test_model_runtime_manager.py tests/test_model_runtime_api.py tests/test_model_lifecycle_integration.py tests/test_chat_model_registry.py tests/test_openai_registry_integration.py tests/test_model_runtime_e2e.py` | 48 passed |
| 桌面端 | `.venv-gui\Scripts\python.exe -m pytest -q -m desktop` | 59 passed |
| 后端回归 | `.venv\Scripts\python.exe -m pytest -q -m "not desktop and not network and not gpu and not real_model"` | 1111 passed, 1 skipped |
| 路由统计 | `.venv\Scripts\python.exe scripts\api_route_stats.py --check` | 145 paths / 172 operations，README 已同步 |
