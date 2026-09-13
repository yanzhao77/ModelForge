# 模型运行时测试计划与结果（Phase 11）

任务书 `#42–#47`、`#70` 要求本次改造覆盖 Unit / Service / API / Runtime /
Training / Chat / E2E / Regression。本文记录测试映射与最近一次执行结果。

## 1. 测试映射

| 层级 | 文件 | 覆盖点 |
|---|---|---|
| Unit | `tests/test_model_registry.py` | 能力推导（GGUF / Transformers / LoRA / 未知格式）、查询过滤、重复注册、用户隔离、路径越界、缺失文件 → `invalid`、能力回填、默认模型、GGUF/HF 元数据解析 |
| Unit | `tests/test_model_runtime_manager.py` | load / chat / unload、加载 B 自动卸载 A、5 次 load-unload-reload 无残留、幂等 load、自动加载、未知模型、能力不足、加载失败清理、请求进行中拒绝卸载、流式输出、状态视图 |
| Service | `tests/test_model_lifecycle_integration.py` | 下载完成自动注册（含去重）、训练拒绝 GGUF base、训练用注册表路径、LoRA 产物能力、全参产物能力、未完成任务不可注册 |
| API | `tests/test_model_runtime_api.py` | `capability` 过滤、`/load` `/unload` `/runtime`、`/runtime` 实例、未知模型 404、已加载不可删除、默认模型读写、默认模型与已加载无关 |
| API | `tests/test_model_runtime_e2e.py` | 全链路：安装 → 注册表 → 加载 → 对话 → 训练（base_model_id）→ 产物注册 → 能力校验 → 卸载/切换 |
| Chat | `tests/test_chat_model_registry.py` | `model_id` 自动加载、切换模型不复用旧实例、SSE 流式、未知 model_id 404、未注册名称回落旧后端 |
| OpenAI | `tests/test_openai_registry_integration.py` | `/v1/models` 来自注册表、`/v1/chat/completions` 走 RuntimeManager、`stream=true` 增量、未知名回落后端 |
| Regression | `tests/test_api_integration.py`、`tests/test_chat_leakage.py`、`tests/test_resource_lease.py`、`tests/test_model_readiness_*.py`、`tests/test_train_kb.py`、`tests/test_local_runtime*.py`、`tests/test_downloader*.py` | 既有行为不回归 |
| Desktop | `tests/test_desktop_model_runtime_pages.py` | 模型中心能力与加载/卸载、Chat 模型选择器与已加载状态、运行时页实例详情、训练页只列 TRAINING 模型 |

## 2. 关键断言

### 2.1 Runtime 循环

`tests/test_model_runtime_manager.py::test_reload_cycle_five_times_releases_every_engine`
连续 5 次 `Load A → Chat → Unload A`，断言：

* 每次生成独立的引擎实例；
* 全部引擎都被 `stop()`；
* `manager.get_current()` 最终为 `None`（无状态残留）。

### 2.2 异常路径

| 场景 | 期望 |
|---|---|
| 文件不存在 | `MODEL_NOT_READY`（模型状态 `invalid`） |
| 模型不存在 | `MODEL_NOT_FOUND` (404) |
| 能力不足（GGUF 训练 / LoRA 推理） | `MODEL_CAPABILITY_UNSUPPORTED` |
| 加载失败 | `RUNTIME_LOAD_FAILED` (502)，实例清空，状态 `load_failed`，租约释放 |
| 请求进行中卸载 | `RUNTIME_BUSY` (409)，实例保持存活 |
| 删除已加载模型 | `MODEL_ALREADY_LOADED` (409) |

## 3. 执行命令

```powershell
# 后端全量（排除需要 GPU / 真实模型 / 外网 / Qt 的用例）
.venv\Scripts\python.exe -m pytest -q -m "not desktop and not network and not gpu and not real_model"

# 桌面端（离屏 Qt）
.venv-gui\Scripts\python.exe -m pytest -q -m desktop

# 本次改造新增用例
.venv\Scripts\python.exe -m pytest -q tests/test_model_registry.py tests/test_model_runtime_manager.py tests/test_model_runtime_api.py tests/test_model_lifecycle_integration.py tests/test_chat_model_registry.py tests/test_openai_registry_integration.py tests/test_model_runtime_e2e.py
.venv-gui\Scripts\python.exe -m pytest -q tests/test_desktop_model_runtime_pages.py
```

## 4. 结果

| 套件 | 结果 |
|---|---|
| 后端全量（非 desktop） | `1111 passed, 1 skipped, 3 deselected`（294.66s） |
| 桌面端（`-m desktop`） | 59 passed |
| 新增后端用例 | 48 passed |
| 新增桌面用例 | 4 passed |

## 5. 已知限制（第一阶段）

1. 单实例：同一时刻只有一个本地模型处于 `loaded`；
2. LoRA Adapter 仅注册/展示，运行时尚未实现 Base + Adapter 挂载，因此不声明 `CHAT`；
3. 增量流式仅对 GGUF 生效；Transformers 路径按整段返回（一次 delta）；
4. 事件同步使用轮询（运行时页 1.5s），未启用 SSE/WebSocket；
5. GGUF 元数据读取为"尽力而为"，解析失败只影响元数据完整度，不影响可用性；
6. 真实模型冒烟仍需 `requirements-ai.txt`（`torch`/`transformers`/`llama-cpp-python`）与本地权重。
