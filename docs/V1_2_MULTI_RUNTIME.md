# V1.2 — Multi-Runtime

目标：ModelForge 不再绑定单一推理引擎，模型资产通过 Runtime Resolver 选择适配器。

## 实现

| 组件 | 文件 | 说明 |
|---|---|---|
| RuntimeAdapter 目录 | `services/runtimes/adapters.py` | `llama_cpp` / `transformers` / `ollama` / `remote_openai`，含 label、capabilities、依赖探测、engine 工厂 |
| RuntimeResolver | `services/runtime_resolver.py` | `ModelRecord → supported_runtimes → preferred_runtime → adapter` |
| 注册表列 | `models.supported_runtimes`、`models.preferred_runtime` | `ModelRegistry.refresh()` 自动推导 |
| 运行时 API | `api/runtimes.py` | `GET /api/v1/runtimes`、`GET /api/v1/runtimes/{id}/health` |
| 运行时管理器 | `services/model_runtime_manager.py` | `load(..., runtime=...)` 覆盖；实例记录 `runtime_id` |
| 远程模型进注册表 | `ModelRegistry.remote_model_descriptors()` | `source=remote`、`preferred_runtime=remote_openai`，凭据仍加密 |

## 关键规则

* 适配器只声明**真正能读**的资产：GGUF → `llama_cpp`；HF 目录 → `transformers`；
  两者不会互相冒充，无法服务的资产在加载时返回 `MODEL_FORMAT_UNSUPPORTED`；
* 显式 `runtime` 覆盖仅在适配器支持该资产时生效，否则回退到 preferred；
* 远程模型不入库（无权重、无路径），以 provider 维度出现在同一份模型清单中，
  调用仍走既有 `provider_id` 通道（凭据服务端加密保存）。

## 验收

| 验收项 | 证据 |
|---|---|
| llama.cpp Adapter | `tests/test_multi_runtime.py::test_resolver_picks_llama_cpp_for_gguf_and_transformers_for_hf` |
| Transformers Adapter | 同上（HF 目录只支持 transformers） |
| Remote Adapter | `test_remote_models_enter_the_registry`、`test_models_api_merges_remote_entries` |
| Runtime Resolver | `test_manager_records_the_runtime_it_used`（实例记录实际使用的 adapter） |
| Runtime Health | `test_runtimes_api_reports_inventory_and_health`（依赖/模型数/加载状态） |
| Chat 可切换 Runtime | `POST /api/v1/chat` 与 `POST /api/v1/models/{id}/load` 均支持 `runtime` 字段 |
| Agent 可切换 Runtime | Agent 的 `runtime_config.runtime` 透传给 `RuntimeBackedProvider` |
