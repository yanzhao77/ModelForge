# 全量测试与 bug 收敛（2026-09-13 第三轮）

## 1. 全量测试结果

以 `7822c5f` 为基线，按 CI 口径执行全量测试（GUI + 后端）：

| 验证项 | 命令 | 结果 |
|---|---|---|
| 空白检查 | `git diff --check` | 通过 |
| 静态检查 | `ruff check backend client tests scripts reports` | 通过 |
| 后端导入冒烟 | `PYTHONPATH=backend/app python -c "import main; assert main.app is not None"` | 通过（`version=3.0`） |
| 启动生命周期 | `pytest -q tests/test_app_boot.py` | 1 passed |
| **全量套件（GUI + 后端）** | `pytest tests/ -q --cov=backend/app --cov-fail-under=75` | **1069 passed / 4 skipped**，覆盖率 **83.23%** |
| 桌面 GUI 子集 | `pytest -q -m desktop` | 39 passed |
| GUI 离屏渲染审计 | `python reports/render_pages_offscreen.py` | `ALL_CAPTURES_OK`、退出码 0 |
| 路由统计一致性 | `python scripts/api_route_stats.py --check` | 139 paths / 164 operations，README 一致 |
| 4 条跳过项 | `pytest -rs` | 均为环境门槛：symlink 特权、`RUN_NETWORK_TESTS`、CPU smoke 模型、无 torch |

代码层面没有失败用例，因此本轮 bug 来自**真实后端写入流程**与**测试/文档基础设施**审查。

## 2. Bug 任务清单

| ID | 等级 | 问题 | 状态 |
|---|---|---|---|
| B-01 | P1 | 客户端对所有请求强制 `Content-Type: application/json`，multipart 上传在服务端看不到 `file` 字段 → 数据集/知识库上传全部 `HTTP_422`（功能不可用） | 已修复 |
| B-02 | P1 | 9 处 `_delete(..., json=...)` 运行时 `TypeError`（`httpx.Client.delete()` 无 body 参数）→ 删除日程/产物/集合文档/集合/插件档案/记忆、插件卸载、MCP 注销全部不可用 | 已修复 |
| B-03 | P2 | 上传文件名用 `filepath.split("/")[-1]`，Windows 下把整条路径当文件名 | 已修复 |
| B-04 | P2 | `/api/v1/knowledge/answer` 在上游推理不可用时返回裸 `HTTP_500`，与 `/chat` 的稳定错误契约不一致 | 已修复 |
| B-05 | P2 | 15 处错误对话框把 worker 原始错误码直接展示给用户（`QMessageBox.warning(..., error)`） | 已修复 |
| B-06 | P2 | CI `desktop` 作业与 README 手工维护 GUI 文件清单，本轮两次手工补列表；新增 GUI 用例会被静默漏掉 | 已修复 |
| B-07 | P3 | `knowledge_answer(model, question)` 位置参数易误用（本轮实测传错参数） | 已修复 |
| B-08 | P3 | 无 Qt 环境依赖手写 `--ignore` 列表，新增 GUI 用例后文档命令即失效 | 已修复 |

## 3. 修复明细与证据

### B-01 上传不再被 JSON Content-Type 覆盖

- 现象：`upload_dataset` / `knowledge_upload` 返回 `HTTP_422`，响应体为
  `{"detail":[{"type":"missing","loc":["body","file"],...}]}`。
- 定位：`_headers()` 固定返回 `Content-Type: application/json`，httpx 因此不会为
  `files=` 生成 `multipart/form-data`；同一请求仅去掉该头即 `200`。
- 修复：`client/pyside6/api_client/client.py` 的 `_headers()` 只保留 `Authorization`，
  由 httpx 依据 `json=`/`files=` 自行决定内容类型。
- 证据：修复后 `upload_dataset` → `{"id":1,...}`、`knowledge_upload` → `{"status":"ingested",...}`；
  回归测试 `tests/test_desktop_http_contract.py`。

### B-02 DELETE 带 body 走通用请求

- 现象：`delete_knowledge_collection` / `delete_plugin_profile` 抛
  `TypeError: Client.delete() got an unexpected keyword argument 'json'`。
- 修复：`_request_json` 对"带 body 的 DELETE"改用 `client.request("DELETE", …)`；
  其余动词保持 `client.get/post/put/patch/delete`，与既有测试的打桩方式一致。
- 证据：修复后 `delete_memory` / `delete_knowledge_collection` / `delete_plugin_profile` /
  `delete_session` 均返回 `{"ok": true, "correlation_id": …}`；回归测试断言 DELETE 走
  `Client.request` 且不会调用无 body 参数的 `Client.delete`。

### B-03 上传文件名用 basename

- 修复：两处上传改用 `os.path.basename(filepath)`；回归测试断言 `files["file"][0] == "probe.csv"`。

### B-04 RAG 回答复用推理异常分类器

- 现象：Ollama 等后端不可用时 `/knowledge/answer` 抛出未捕获的 `httpx.HTTPStatusError`，
  服务端返回 500，桌面端只能显示 `HTTP_500`。
- 修复：把 `api/chat.py` 的异常分类器抽到 `services/inference_errors.py`
  （`classify_inference_exception`），`/chat` 与 `/knowledge/answer` 共用；
  `/knowledge/answer` 新增映射分支。
- 证据：同一场景下 `/chat` 与 `/knowledge/answer` 现在都返回 `PROVIDER_UNAVAILABLE`；
  `tests/test_knowledge_answer_error_contract.py` 覆盖 502/429/连接失败/未知异常四种映射。

### B-05 错误文案统一本地化

- 修复：`main.py`（更新检查/下载）、`dataset_page.py`（4 处）、`knowledge_page.py`（5 处）、
  `model_dialogs.py`（2 处）、`runtime_page.py`、`session_sidebar.py` 的错误对话框统一走
  `format_api_error`。
- 证据：`tests/test_desktop_error_messages.py`（含运行时页、设置页、扩展页断言）。

### B-06 / B-08 GUI 用例选择改为显式标记

- 现象：CI `desktop` 作业与 README 各自维护一份 GUI 文件清单；本轮新增两个 GUI 用例时需要
  手工补两处，且"间接依赖 Qt"的文件（如 `tests/test_i18n_runtime.py`，只引用
  `client/pyside6` 路径）无法被文本启发式识别。
- 修复：
  1. 需要 Qt 的测试文件在文件内声明 `pytestmark = pytest.mark.desktop`（11 个文件）；
  2. `tests/conftest.py` 依据该声明在缺少 Qt 时自动 `collect_ignore`，并提供会话级 Qt 收尾；
  3. `pytest.ini` 注册 `desktop` marker；
  4. CI `desktop` 作业改为 `pytest -q -m desktop --cov=client/pyside6`；
  5. README 的非 GUI 命令简化为 `pytest tests/ -q`。
- 证据：有 Qt 时 `-m desktop` 选中 39 条、桌面子集 39 passed；无 Qt 的解释器（本机 Anaconda
  `.venv`，`PySide6` 可导入但 Qt DLL 加载失败）执行 `pytest tests/ -q --collect-only`
  得到 **1044 collected / 0 error**（修复前为 10 个 collection error）。

### B-07 调用点改用关键字参数

- 修复：`knowledge_page.py` 与 `chat_page.py` 改为
  `knowledge_answer(model=..., question=..., top_k=3)`，避免 `(model, question)` 顺序误用。

## 4. 修复后验证

| 验证项 | 结果 |
|---|---|
| `git diff --check` / `ruff check backend client tests scripts reports` | 通过 |
| 新增回归：`tests/test_desktop_http_contract.py` + `tests/test_knowledge_answer_error_contract.py` | 10 passed |
| 桌面 GUI 子集 `-m desktop` | 39 passed |
| **全量套件（GUI + 后端 + 覆盖率门槛）** | **1079 passed / 4 skipped**，覆盖率 **83.31%** |
| 真实后端写入流程扫描（上传/校验/删除/记忆/集合/档案/会话/RAG） | 15 项全部正常，**0 bug** |
| RAG 与聊天在无推理后端时的错误码 | 均为 `PROVIDER_UNAVAILABLE` |
| GUI 离屏渲染审计 | `ALL_CAPTURES_OK`、`ENDPOINTS_TOUCHED 26`、退出码 0（52s） |
| 无 Qt 解释器收集 | 1044 collected / 0 error |

## 5. 残余风险与后续建议

- **`runtime_*` 端点仍是管理员专属**：普通账号调用 `/runtime/start`、`/runtime/chat`、
  `/runtime/status` 会得到 `RUNTIME_ADMIN_REQUIRED`（设计如此）。若产品希望普通用户也能
  切换本地运行时，需要单独的产品/权限决策。
- **上传体积与类型校验**：`upload_dataset` / `knowledge_upload` 目前只依赖后端校验
  （`DATASET_FILE_TOO_LARGE` 等），客户端未做前置大小检查。
- **CI 标记约定**：新增 GUI 用例必须声明 `pytestmark = pytest.mark.desktop`，否则会在无 Qt
  环境里以 collection error 暴露（README 已记录该约定）。
