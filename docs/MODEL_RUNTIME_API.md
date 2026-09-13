# 模型 / 运行时 API 参考（V1.0 Unified Model Runtime）

所有 `/api/v1/*` 接口使用 Bearer Token 或会话 Cookie 认证；错误统一为
`{"detail": {"code", "message", "correlation_id"[, "details"]}}`。

## 1. 模型注册中心

### `GET /api/v1/models`

列出当前用户可见（自身 + 全局）的模型资产。

查询参数（全部可选）：`capability`、`status`、`format`、`source`。

| 参数 | 示例 | 说明 |
|---|---|---|
| `capability` | `CHAT` / `INFERENCE` / `TRAINING` / `LORA` / `VISION` / `EMBEDDING` / `AUDIO` / `IMAGE` | 能力过滤，非法值 → `400 MODEL_CAPABILITY_INVALID` |
| `status` | `ready` | 生命周期状态 |
| `format` | `gguf` | 资产格式 |
| `source` | `download` | 等价于 `provider` |

响应（数组）：

```json
[
  {
    "id": 12,
    "model_id": 12,
    "name": "qwen2.5-0.5b",
    "display_name": null,
    "provider": "download",
    "source": "download",
    "path": "…",
    "size": "520.0MB",
    "size_bytes": 545259520,
    "status": "ready",
    "format": "gguf",
    "quant": null,
    "capabilities": ["CHAT", "INFERENCE"],
    "metadata": {"architecture": "qwen2", "context_length": 32768},
    "base_model_id": null,
    "parent_model_id": null,
    "ready": true,
    "runtime_status": "idle",
    "created_time": "…",
    "updated_time": "…"
  }
]
```

> `model_id` 是跨模块唯一标识；`id` 保留给既有桌面客户端。
> `path` 仅用于本机展示，前端不得把它当作业务主键传回。

### `POST /api/v1/models/install`

登记一个已存在的模型路径（路径必须位于配置的模型根目录内）。

```json
{"name": "qwen2.5-0.5b", "provider": "local", "path": "…", "format": "gguf", "quant": "Q4_K_M"}
```

* 自动推导 `capabilities` / `format` / `size_bytes` / `metadata`；
* 路径越界 → `403 MODEL_PATH_OUTSIDE_ALLOWED_ROOT`。

### `POST /api/v1/models/scan`

扫描模型根目录（或子目录），发现并登记模型。

### `GET /api/v1/models/{model_id}`

读取单个模型；会刷新格式/能力/元数据，并把丢失的文件标记为 `invalid`。

### `DELETE /api/v1/models/{model_id}`

删除记录（不删除磁盘文件）。模型正在运行时返回
`409 MODEL_ALREADY_LOADED`；删除默认模型会同时清除默认偏好。

### `GET /api/v1/models/readiness`

用户级可用性快照。只把 **ready 且文件存在** 的模型列入 `targets`，
已声明但文件丢失的记录不会被当作可用目标。

## 2. 默认模型（与"已加载模型"无关）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/models/default` | 返回 `{"model_id": 12, "model": {…}}`，未设置时为 `null` |
| POST | `/api/v1/models/{model_id}/default` | 设为该用户的默认本地模型（不加载） |
| PUT | `/api/v1/models/default` | 既有接口：`{"kind": "local"|"remote", "model_ref": "…", "provider_id": null}` |
| DELETE | `/api/v1/models/default` | 清除默认模型 |

默认模型是用户偏好；当前加载的实例是运行时状态，二者可以不同。

## 3. 运行时

### `POST /api/v1/models/{model_id}/load`

把注册模型加载到共享运行时（单实例）。

```json
{"context_length": 4096, "gpu_layers": 0, "threads": 8}
```

响应：

```json
{
  "instance_id": "…",
  "model_id": 12,
  "model_name": "qwen2.5-0.5b",
  "runtime": "llama.cpp",
  "status": "loaded",
  "context_length": 4096,
  "gpu_layers": 0,
  "threads": 8,
  "memory_bytes": null,
  "started_at": "…",
  "last_used_at": "…",
  "active": true,
  "active_requests": 0
}
```

加载配置会持久化到 `data/model_runtime_config.json`，下次作为默认值。

### `POST /api/v1/models/{model_id}/unload`

卸载当前模型，释放引用并触发 GC。

```json
{"status": "unloaded", "model_id": 12, "instance_id": "…", "unloaded": true}
```

### `GET /api/v1/models/{model_id}/runtime`

该模型的实时运行时状态；未加载时返回 `{"active": false, "status": "idle"}`。

### 既有运行时接口（兼容 Ollama 等后端）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/runtime` | 当前活跃实例 + 加载配置 + `recent_events`（需要运行时管理员） |
| GET | `/api/v1/runtime/status` | 后端注册表状态 + `instance` + `inference_holder` + `recent_events` |
| POST | `/api/v1/runtime/start` | 请求模型解析为注册模型时走管理器，否则走原有后端 |
| POST | `/api/v1/runtime/stop` | 同上 |
| POST | `/api/v1/runtime/chat` | 同上 |

## 4. 对话

### `POST /api/v1/chat` / `POST /api/v1/chat/stream`

```json
{
  "model": "qwen2.5-0.5b",
  "model_id": 12,
  "messages": [{"role": "user", "content": "你好"}],
  "session_id": 7,
  "provider_id": null
}
```

* `model_id` 存在时：经 ModelResolver → RuntimeManager，未加载则自动加载；
* `model_id` 为空时：保持既有行为（`RuntimeRegistry`，例如 Ollama / 远程服务）；
* 模型切换后不会复用上一个模型的实例。

## 5. OpenAI 兼容接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/models` | 来自统一注册中心；`id` 为模型名，附带 `model_id` / `capabilities` / `ready` |
| POST | `/v1/chat/completions` | 先解析注册模型 → RuntimeManager；未命中回落既有后端；支持 `stream` |

## 6. 训练

### `POST /api/v1/train/start`

```json
{
  "dataset_id": 3,
  "base_model_id": 12,
  "method": "lora",
  "epochs": 1,
  "confirm": true
}
```

* `base_model_id` 优先；后端校验 `TRAINING` 能力，GGUF 推理模型 → `400`；
* 兼容旧客户端：仍可传 `base_model` 文本（Hugging Face repo id / 路径）；
* 子进程使用注册表解析出的**路径**，任务记录保存**显示名**。

### `POST /api/v1/train/{task_id}/register-model`

把训练产物注册为模型：

* `lora` → `capabilities = ["LORA"]`，`requires_base_model = true`；
* `full` → `capabilities = ["CHAT", "INFERENCE"]`，`format = safetensors`；
* 元数据包含 `base_model_id` / `training_task_id` / `dataset_id` / `created_at`。

## 7. 稳定错误码

| HTTP | code | 触发条件 |
|---|---|---|
| 400 | `MODEL_CAPABILITY_INVALID` | 能力过滤值非法 |
| 400 | `MODEL_CAPABILITY_UNSUPPORTED` | 模型不具备所需能力（如训练 GGUF） |
| 400 | `MODEL_NOT_READY` | 文件缺失或状态不可加载 |
| 400 | `MODEL_PATH_INVALID` | 记录路径不在允许根目录内 |
| 403 | `MODEL_PATH_OUTSIDE_ALLOWED_ROOT` | 注册/扫描越界路径 |
| 404 | `MODEL_NOT_FOUND` | `model_id` 不存在或无权访问 |
| 409 | `MODEL_ALREADY_LOADING` | 已有加载/卸载进行中 |
| 409 | `MODEL_ALREADY_LOADED` | 模型正在运行，不能删除 |
| 409 | `RUNTIME_BUSY` | 另一账号占用推理资源，或请求进行中无法卸载 |
| 409 | `RUNTIME_NOT_LOADED` | 明确要求"仅使用已加载实例"但实例不存在 |
| 502 | `RUNTIME_LOAD_FAILED` | 引擎加载失败（模型文件损坏、依赖缺失等） |
| 503 | `RUNTIME_UNAVAILABLE` | 后端运行时不可用 |
