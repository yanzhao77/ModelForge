# 模型生命周期（Model Lifecycle）

本文定义 ModelForge 中"模型资产"从被发现到可用、再到训练回流的状态机，
是 `docs/plan/MODELFORGE_MODEL_RUNTIME_TASK_PLAN.md` 第 6 / 56 / 63 节的落地说明。

## 1. 状态词表

模型资产状态（`models.status`，见 `services/model_capabilities.py`）：

| 状态 | 含义 | 是否可加载 |
|---|---|---|
| `discovered` | 扫描发现但尚未确认 | 是（加载前会再次校验文件） |
| `installing` | 安装/复制中 | 否 |
| `installed` | 已登记但文件尚未落盘 | 否（`is_ready` 为 false） |
| `ready` | 文件存在且可用 | 是 |
| `available` | `ready` 的历史拼写，语义完全相同 | 是 |
| `loading` | 正在加载到内存 | 否 |
| `loaded` | 已加载（RuntimeInstance 存活） | 是（复用同一实例） |
| `unloading` | 正在释放 | 否 |
| `load_failed` | 上次加载失败 | 否（可重试） |
| `invalid` | 记录的路径已不存在 | 否 |

运行时实例状态（`RuntimeInstance.status`，仅内存）：

```
idle ──load──▶ loading ──成功──▶ loaded ──unload──▶ unloading ──▶ idle
                   │
                   └──失败──▶ load_failed（实例被丢弃，模型状态记为 load_failed）
```

## 2. 状态迁移

```
                ┌──────────────────────────────────────────┐
                ↓                                          │
  discovered ─▶ installing ─▶ installed ─▶ ready ─▶ loading ─▶ loaded
                                            ▲            │        │
                                            │            │        │
                                        unloading ◀──────┘        │
                                                                  │
                        训练完成 ─▶ registry.register() ─▶ ready ◀─┘
```

* `ready → loading → loaded`：`POST /api/v1/models/{model_id}/load`；
* `loaded → unloading → ready`：`POST /api/v1/models/{model_id}/unload`；
* 加载失败：实例被丢弃、引用释放、模型状态写为 `load_failed`，推理租约立即释放；
* 文件消失：`ModelRegistry.refresh()` 将状态写为 `invalid`（绝不停留在 `ready`）。

## 3. 一致性规则

| 场景 | 规则 |
|---|---|
| 文件存在、记录不存在 | 通过 `POST /api/v1/models/scan` 或下载完成回调重新注册 |
| 记录存在、文件不存在 | `invalid`，且不会被 readiness 视为可用目标 |
| 重复下载同一仓库 | 按 (user, name) 更新既有记录，不产生重复行 |
| 删除默认模型 | 同步清除该用户的默认模型偏好，避免悬空引用 |
| 删除已加载模型 | 返回 `409 MODEL_ALREADY_LOADED`，必须先卸载 |
| 同一时刻两个加载 | 第二个请求返回 `409 MODEL_ALREADY_LOADING` |
| 加载 B 时 A 已加载 | 自动先卸载 A，再加载 B（单实例策略） |
| 请求进行中卸载 | 返回 `409 RUNTIME_BUSY`，不销毁正在使用的实例 |

## 4. 能力（Capability）

能力由**格式 + 来源**推导，而不是由文件名猜测：

| 资产 | 推导结果 |
|---|---|
| `*.gguf` / `*.ggml` | `CHAT`, `INFERENCE` |
| Transformers 目录（含 `config.json`，safetensors/bin 权重） | `CHAT`, `INFERENCE`, `TRAINING`, `LORA` |
| 训练输出的 `safetensors` 全参微调 | `CHAT`, `INFERENCE` |
| `peft-adapter` LoRA 产物 | `LORA`（并标记 `requires_base_model`） |
| 其它未知格式 | `INFERENCE` |

要点：

* GGUF 推理模型**永远不会**被自动标记为 `TRAINING`；
* LoRA Adapter 在 Runtime 真正支持 Base + Adapter 之前**不会**声明 `CHAT`；
* 训练页只列 `capability=TRAINING` 的模型，后端 `TrainingService.start`
  还会再次校验（UI 过滤不是安全边界）。

## 5. 元数据

`ModelRecord.model_metadata` 是 JSON 文本，尽量记录：

```json
{
  "architecture": "qwen2",
  "context_length": 32768,
  "family": "Qwen",
  "parameters": "0.5B",
  "quantization": "Q4_K_M"
}
```

* GGUF：读取文件头（最多 8 MiB，不加载张量）；
* Transformers：读取目录内 `config.json`；
* 解析失败只记录"元数据不完整"，**不阻塞安装/下载**。

训练产物额外写入：

```json
{
  "training_task_id": "…",
  "method": "lora",
  "dataset_id": 3,
  "base_model_id": 12,
  "output_path": "…",
  "format": "peft-adapter",
  "requires_base_model": true,
  "created_at": "2026-09-13T…"
}
```

## 6. 资源与并发

* `inference_lease`：同一时刻只有一个账号能进行推理/加载；
* `training_lease`：同一时刻只有一个训练任务；
* `ModelRuntimeManager` 内部 `RLock` 保证 load/unload 状态迁移原子化；
* 所有跨模块关联统一使用 `model_id`，禁止以文件路径或名称作为业务主键。

## 7. 事件（Phase 9）

第一阶段不做 SSE/WebSocket，页面以轮询同步。为了让轮询客户端能判断"是否
发生了变化"而不是逐字段比对，运行时管理器维护一个有界事件日志
（最多 50 条，`GET /api/v1/runtime` 与 `/api/v1/runtime/status` 返回
`recent_events`）：

```
MODEL_LOADING → MODEL_LOADED → MODEL_UNLOADING → MODEL_UNLOADED
                       └──────── MODEL_LOAD_FAILED
```

每条事件包含自增 `sequence`、`event`、`at`（UTC）与 `model_id`。
模型安装/删除的同步仍通过任务中心（下载完成事件）与模型列表刷新完成。
