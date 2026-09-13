# 行为变更说明：设置 → 模型（下载源与默认存放地址）

> 范围：桌面端「设置」新增“模型”节点，以及支撑它的后端接口。
> 本文只记录使用者可感知的语义变化与验证方式。

## 1. 新增“模型”设置节点

`设置` 的分类从 `通用 / 外观 / 语言 / 服务连接 / 关于` 变为
`通用 / 模型 / 外观 / 语言 / 服务连接 / 关于`，新增的“模型”页包含两块：

| 面板 | 作用 |
|---|---|
| Hugging Face 下载源 | 在官方源与 HF Mirror（中国大陆镜像）之间切换；此前位于“服务连接”页，本次迁入“模型”页，控件与错误提示保持不变 |
| 默认存放地址 | 查看/修改模型下载目录，带“浏览… / 保存 / 恢复默认”，并显示解析后的绝对路径、目录状态、剩余空间与目录内模型文件数 |

“服务连接”页只保留 endpoint 与账号信息，不再承载下载源设置。

## 2. 存放地址同时决定“下载位置”和“扫描根目录”

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| 配置项 | `model_dir`（下载落盘）与 `model_path`（模型扫描根）是两个可独立漂移的字段，默认都为 `./models` | 保存存放地址时两者写入同一路径，避免“下载完成却扫描不到” |
| 生效范围 | 仅进程启动时读取 | 保存后立即对后续下载任务与模型扫描生效，无需重启 |
| 持久化 | 无 | 写入 `data/runtime_settings.json`（`model_dir` + `model_path`），并在启动加载时优先于 `.env` 的 `MODEL_PATH`/`MODEL_DIR` |

**为什么需要覆盖 `.env`**：仓库自带的 `.env` 声明了 `MODEL_PATH=./models`。
若环境变量优先级不变，用户在界面上显式选择的目录会在重启后被静默丢弃。
因此 `model_dir`/`model_path` 属于“桌面端托管设置”，在 `load_config()` 中
最后应用；`config_path` 显式传入（测试、脚本）时该覆盖不参与，行为不变。

## 3. 接口契约

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/system/model-storage` | 返回 `model_dir`、`resolved_path`、`default_path`、`is_default`、`exists`、`writable`、`free_bytes`、`total_bytes`、`entries`、`model_files`、`truncated` |
| PUT | `/api/v1/system/model-storage` | 请求体 `{"model_dir": "..."}`；校验后创建目录并做写入探针，成功返回同一结构 |

错误码（均带 `correlation_id`）：

| 状态 | 代码 | 触发条件 |
|---|---|---|
| 400 | `MODEL_DIR_INVALID` | 仅空白，或指向文件系统根目录 |
| 400 | `MODEL_DIR_NOT_A_DIRECTORY` | 路径已存在且不是目录 |
| 400 | `MODEL_DIR_NOT_WRITABLE` | 无法创建或无法写入（探针文件失败） |
| 500 | `MODEL_STORAGE_PERSIST_FAILED` | 目录可用但设置无法写入 `runtime_settings.json` |
| 422 | — | 请求体缺失或长度超出 1–1024 |

相对路径按 ModelForge 安装根目录解析（不依赖进程 CWD），`~` 会被展开；
目录扫描最多统计 2000 个顶层条目，超出时 `truncated` 为 `true`。

## 4. 未包含

1. 不移动、不复制、不删除任何已有模型文件；修改存放地址后旧目录中的模型
   会从模型列表中消失，需要手动迁移或重新扫描。
2. 不改动下载任务的并发/队列语义，也不改变远程模型服务配置。

## 5. 验证

| 验证项 | 命令 | 结果 |
|---|---|---|
| 后端用例 | `.venv\Scripts\python.exe -m pytest tests/test_system_model_storage.py -q` | 12 passed |
| 桌面端用例 | `.venv-gui\Scripts\python.exe -m pytest tests/test_desktop_settings_model_page.py tests/test_desktop_ui_remediation.py tests/test_desktop_error_messages.py -q` | 18 passed |
| 相关回归 | `.venv\Scripts\python.exe -m pytest tests/test_security_hardening.py tests/test_config_example_consistency.py tests/test_phase1_backend.py tests/test_phase3_model_manager.py tests/test_downloader_resume.py -q` | 64 passed |
| 路由统计 | `.venv\Scripts\python.exe scripts\api_route_stats.py --check` | 140 paths / 166 operations，README 已同步 |
| 非 GUI 全量 | `.venv\Scripts\python.exe -m pytest tests/ -q` | 1060 passed / 4 skipped / 2 failed（见下，与本改动无关） |
| GUI 全量 | `.venv-gui\Scripts\python.exe -m pytest tests/ -q -m desktop` | 55 passed |
| 端到端 | 启动 uvicorn 后用真实 `ModelForgeClient` 调 `get/update_model_storage` | 目录创建、回读、空值 422 均符合契约 |

全量运行时的 2 个失败均来自同一工作区内并行进行的模型注册表改动
（`services/model_registry.py`、`model_resolver.py`、`api/models.py` 等未提交文件）：
`tests/test_agent_runs_phase2.py::test_create_agent_persists_ready_model_target`
与 `tests/test_model_readiness_api.py::test_readiness_and_default_are_scoped_and_never_expose_secret_data`。

定位方式：在干净 `HEAD`（`202657c`）的临时 `git worktree` 中，仅叠加本改动涉及的
`backend/app/api/system.py`、`backend/app/core/config.py` 与
`tests/test_system_model_storage.py` 后，
`pytest tests/test_agent_runs_phase2.py::TestAgentRunApi::test_create_agent_persists_ready_model_target tests/test_model_readiness_api.py tests/test_system_model_storage.py -q`
为 15 passed。该失败属于并行改动的工作范围，不应计入本改动。
