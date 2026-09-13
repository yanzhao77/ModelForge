# 全量测试结果与 bug 任务清单（2026-09-13 第二轮）

## 1. 全量测试结果（推送后执行）

提交 `0801696` 推送 `origin/master` 之后，按 CI 口径执行全量测试，含 GUI 与后端：

| 验证项 | 命令 | 结果 |
|---|---|---|
| 空白检查 | `git diff --check` | 通过 |
| 静态检查 | `ruff check backend client tests scripts reports` | 通过 |
| 后端导入冒烟 | `PYTHONPATH=backend/app python -c "import main; assert main.app is not None"` | 通过（`version=3.0`） |
| 启动生命周期 | `pytest -q tests/test_app_boot.py` | 1 passed |
| **全量套件（GUI + 后端）** | `pytest tests/ -q --cov=backend/app --cov-fail-under=75` | **1063 passed / 4 skipped**，后端覆盖率 **83.24%**（门槛 75%） |
| GUI 离屏渲染审计 | `python reports/render_pages_offscreen.py` | `ALL_CAPTURES_OK`、`ENDPOINTS_TOUCHED 26`、退出码 0 |
| 路由统计一致性 | `python scripts/api_route_stats.py --check` | 139 paths / 164 operations，README 一致 |
| 运行时依赖审计 | `pip-audit -r requirements.txt` | 无已知漏洞 |
| 真实后端端到端 | 线程内起 uvicorn + 真实 `ModelForgeClient` 调用 30 个端点 | 26 个形状符合契约；4 项为权限（`RUNTIME_ADMIN_REQUIRED`）或调用方缺参，非形状缺陷 |

结论：**没有失败用例**。下面的 bug 清单来自"读代码 + 端到端观察 + 测试基础设施审查"，
全部为可复现的真实缺陷，并按 P1→P3 顺序修复。

## 2. Bug 任务清单

| ID | 等级 | 问题 | 状态 |
|---|---|---|---|
| B-01 | P1 | 更新检查定时器未绑定窗口生命周期：关窗后仍会触发真实网络请求，并造成跨用例 mock 串扰（重负载全量跑出现过一次 `StopIteration`） | 已修复 |
| B-02 | P2 | 调试通道 `MODELFORGE_DEBUG_TEARDOWN=1` 仍以 `0xC0000005` 结束，调试不可用 | 已修复 |
| B-03 | P2 | 8 个页面/组件把原始错误码直接拼进用户文案（实测会显示 `RUNTIME_ADMIN_REQUIRED`） | 已修复 |
| B-04 | P2 | `format_api_error` 只接受字母数字/`_`/`-`，带 `:` 或 `.` 的错误码被降级成 `OPERATION_FAILED` | 已修复 |
| B-05 | P3 | GUI 用例失败时 pytest 进程以 `0xC0000005` 结束，真实断言失败被崩溃码掩盖 | 已修复 |
| B-06 | P3 | `docs/BEHAVIOR_CHANGES_2026-09-12.md` 对 `0xC0000005` 的归因（"探针脚本退出顺序所致"）与实测不符 | 已修复（更正注记） |
| B-07 | P3 | 进程级退出用例耗时约 62s | 接受（受产品 5s 宽限约束，收紧会削弱 overrun 覆盖） |

## 3. 修复明细

### B-01 更新检查定时器归属窗口

- `client/pyside6/main.py`：`QTimer.singleShot(1800, …)` 改为窗口持有的
  `self._update_check_timer`（`_UPDATE_CHECK_DELAY_MS` 常量），`closeEvent` 中 `stop()`。
- 回归：`tests/test_desktop_shutdown.py::test_closing_the_window_cancels_the_scheduled_update_check`
  （把延迟缩到 30ms，关窗后断言定时器不再激活、并把事件循环推进超过延迟后断言 `updater.check_latest` 未被调用）。

### B-02 调试通道可安全退出

- `client/pyside6/main.py`：`_exit_process(exit_code, app=…, window=…)` 在
  `MODELFORGE_DEBUG_TEARDOWN=1` 时先执行 `_dispose_window()`（`hide` → `setParent(None)` →
  `deleteLater` → `processEvents` → `gc.collect()`），不再把活的窗口对象图交给解释器收尾。
- 回归：`tests/test_desktop_process_exit.py::test_debug_teardown_path_also_exits_cleanly`；
  手工验证 `MODELFORGE_DEBUG_TEARDOWN=1 python reports/gui_exit_probe.py --mode fast`
  输出 `PROBE_MAIN_RETURNED 0` 且退出码 0（修复前为 `0xC0000005`）。

### B-03 错误文案统一走本地化

- 改动文件：`agent_workbench_page.py`、`dataset_page.py`、`control_center_page.py`、
  `extensions_page.py`、`knowledge_page.py`、`model_dialogs.py`、`runtime_page.py`、
  `session_sidebar.py`、`settings_page.py`。
- 扩展页额外修正：原判据 `"403" in message` 永不成立（worker 只回稳定错误码），
  改为按 `RUNTIME_ADMIN_REQUIRED` / `ADMIN_REQUIRED` / `FORBIDDEN` 分类，其余走
  `format_api_error`。
- 回归：`tests/test_desktop_error_messages.py`（4 条）。

### B-04 错误码白名单补齐

- `client/pyside6/i18n/ui_localizer.py`：`format_api_error` 的候选字符集加入 `:` 与 `.`，
  使 `INVALID_RESPONSE_SHAPE:models` 这类带作用域后缀的码不再被丢弃。
- 回归：`tests/test_desktop_error_messages.py::test_settings_page_download_source_failure_is_localized`
  （断言文案包含该码且带本地化句式）。

### B-05 GUI 用例失败不再变成崩溃

- 新增 `tests/conftest.py`：默认 `QT_QPA_PLATFORM=offscreen`，并在 `pytest_sessionfinish`
  中于 `QApplication` 存活时关闭/释放所有顶层控件并 `gc.collect()`。
- 验证：故意保留一个失败用例时，进程返回 **1**（干净失败）而不是 `0xC0000005`；
  修复后该套件 5 passed 且退出码 0。

### B-06 文档更正

- `docs/BEHAVIOR_CHANGES_2026-09-12.md`：在 §12 的 A/B 表下加入更正注记，
  说明真实入口稳定复现、两种收尾方式都无效、根因是对象图在 `QApplication` 之后回收。

## 4. 修复后验证

| 验证项 | 结果 |
|---|---|
| `ruff check backend client tests scripts reports` / `git diff --check` | 通过 |
| `tests/test_desktop_shutdown.py`（含新增定时器用例） | 2 passed |
| `tests/test_desktop_error_messages.py` + `tests/test_i18n_runtime.py` | 5 passed |
| `tests/test_desktop_process_exit.py`（fast/slow/overrun/realclient + 调试通道） | 5 passed |
| 定向组合（上述 4 个文件） | 12 passed |
| `reports/gui_exit_probe.py --mode overrun --block-seconds 9` | 退出码 0；日志确认"仍有在途请求"分支被执行（`retained_ms=5078`） |
| GUI 离屏渲染审计（修复后复跑） | `ALL_CAPTURES_OK`、`ENDPOINTS_TOUCHED 26`、退出码 0（66s） |
| **全量套件（GUI + 后端，带覆盖率门槛）** | **1069 passed / 4 skipped**，后端覆盖率 **83.25%**（450s） |

## 5. 残余风险与后续建议

- **更新检查语义**：定时器现在随窗口取消；若产品希望"启动后必须完成一次更新检查"，
  需要改为在关闭时等待既有请求（当前语义是"窗口关闭即不再发起新检查"）。
- **进程级退出用例耗时**：单次约 62s，其中 overrun 场景必须超过 5s 宽限；若后续收紧宽限
  常量，需同步调整用例参数。
- **权限错误文案**：非管理员用户进入运行时/扩展页会看到"请求未完成（RUNTIME_ADMIN_REQUIRED）"，
  扩展页已给出更明确的中文提示；其他页面仍复用通用句式，如需更友好文案可按页面补充。
