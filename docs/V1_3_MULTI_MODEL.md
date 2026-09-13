# V1.3 — Multi-Model & Resource Manager

目标：从"同一时刻只有一个已加载模型"升级为多实例 + 资源管理 + LRU + 队列 + 优先级。

## 实现

| 组件 | 文件 | 说明 |
|---|---|---|
| ResourceManager | `services/resource_manager.py` | CPU / RAM / GPU / VRAM / Disk 采样（`psutil`、`torch.cuda` 可选，缺失时显式报告未知）；按实例记账与容量预算 |
| 多实例运行时 | `services/model_runtime_manager.py` | `_instances`/`_engines` 字典、`max_instances`、`config`/`runtime_id`/`memory_bytes` 逐实例记录 |
| LRU | 同上 `_lru_victim()` | 只驱逐 `status=loaded` 且 `active_requests=0` 的实例，**绝不**驱逐正在推理的实例 |
| Load Queue + Priority | 同上 `_make_room()`/`queue_snapshot()` | `HIGH/NORMAL/LOW` 排序，排队等待容量（默认 30s 超时 → `RUNTIME_BUSY`） |
| 运行时 API | `api/runtime.py` | `GET /runtime/instances`、`/runtime/resources`、`/runtime/queue`、`POST /runtime/evict`、`POST /runtime/unload-all` |
| 配置 | `core/config.py` | `runtime_max_loaded_models`（默认 2）、`runtime_load_queue_timeout_seconds`、`runtime_memory_ratio` |

## 行为变化

* 加载第二个模型不再自动卸载第一个（在容量内并存）；
* `get_current()` 语义保持兼容：返回最近使用的已加载实例；
* 容量不足时优先 LRU 驱逐空闲实例，全部忙则排队，超时返回 `RUNTIME_BUSY`。

## 验收

| 验收项 | 证据 |
|---|---|
| 多 Runtime Instance | `tests/test_multi_model_runtime.py::test_multiple_instances_coexist` |
| Resource Manager | `test_resource_manager_estimates_and_snapshot` |
| RAM/VRAM tracking | 采样缺失时返回 `None` + `notes`（不伪造数值） |
| LRU | `test_lru_evicts_the_idle_oldest_instance` |
| Load Queue | `test_queued_load_proceeds_when_capacity_frees_up` |
| Priority | `test_queue_reports_priority_order` |
| 多模型 Agent | Agent 通过 `model_id` 使用同一多实例管理器（V1.1 链路） |
| 内存泄漏测试 | `test_load_unload_cycles_release_every_instance_and_claim`（6 轮 load/chat/unload，claims 归零） |
