# 桌面 GUI 测试 Bug 清册与收敛计划（2026-09-13）

## 1. 结果摘要

本轮以"重建可用的 GUI 测试环境"为起点，清出 7 个问题并全部收敛：

| ID | 等级 | 问题 | 状态 |
|---|---|---|---|
| GUI-BUG-01 | P1 | 正常退出以 `0xC0000005`（访问违例）结束 | 已修复 |
| GUI-BUG-02 | P1 | 页面销毁时在途 `ApiWorker` 线程随页面析构 → `qFatal` `0xC0000409` | 已修复（前序提交）+ 本轮独立验证 |
| GUI-BUG-03 | P2 | 离屏渲染审计脚本退出码非 0，且不判定槽内异常 | 已修复 |
| GUI-BUG-04 | P2 | 页面槽函数对 payload 形状无防御，失败态对用户不可见 | 已修复 |
| GUI-BUG-05 | P2 | CI `desktop` 作业只覆盖 5 个 GUI 文件 | 已修复 |
| GUI-BUG-06 | P2 | 缺少子进程级、真实入口的退出码回归 | 已修复 |
| GUI-BUG-07 | P2 | 孤儿 worker 无上界、无诊断；退出分支跳过收尾刷盘 | 已修复（诊断 + 清理 + flush） |

范围仅限桌面客户端（`client/pyside6`）及其测试与 QA 脚本；后端服务不在本轮范围内。

## 2. 环境基线（2026-09-13 实测）

| 项 | 实测值 |
|---|---|
| 新环境 | `.venv-gui`（已加入 `.gitignore`） |
| 解释器 | CPython 3.11.3，基座 `C:\data\python\Python311`（非 Anaconda） |
| 关键依赖 | PySide6 6.11.1 / fastapi 0.141.1 / pytest 9.1.1 / ruff 0.16.3，`pip check` 无冲突 |
| 旧环境对照 | `.venv`（Anaconda 3.10 基座）：`import PySide6.QtWidgets` → `ImportError: DLL load failed while importing QtWidgets` |
| Qt 可用性 | 新环境 `QApplication` 可创建，`platformName() == offscreen` |

复现命令（Windows）：

```powershell
python -m venv .venv-gui
.\.venv-gui\Scripts\pip install -r requirements.txt -r requirements-dev.txt -r requirements-gui.txt
$env:QT_QPA_PLATFORM="offscreen"
.\.venv-gui\Scripts\python -m pytest tests/ -q
.\.venv-gui\Scripts\python reports\render_pages_offscreen.py
```

## 3. Bug 明细与修复

### GUI-BUG-01：正常退出以 `0xC0000005` 结束

**现象**：窗口关闭、`main()` 返回 `0` 之后，进程在解释器收尾阶段以访问违例
（`-1073741819` = `0xC0000005`）结束；`faulthandler` 显示
`Windows fatal exception: access violation`、`<no Python frame>`，故障在 C++ 侧收尾。

**根因**：窗口对象图被信号/lambda 的引用环持有，只在解释器收尾时由循环回收器释放，
而 `QApplication` 已经析构，Qt 收尾访问已释放对象。对照实验：

| 收尾方式 | 退出码 |
|---|---|
| 直接 `return`（修复前） | `0xC0000005` |
| `del window` + `gc.collect()` | `0xC0000005` |
| `deleteLater()` + `sendPostedEvents(DeferredDelete)` | `0xC0000005` |
| `hide()` + `setParent(None)` + `deleteLater()` + `processEvents()` + `del` + `gc` | `0` |
| `os._exit(code)` | `0` |

前四种依赖 Python 何时回收引用环，不可靠，因此采用确定性退出。

**修复**：`client/pyside6/main.py` 新增 `_exit_process()`：`recovery.mark_clean_exit()`
之后 flush `stdout`/`stderr`、`logging.shutdown()`，再 `os._exit(exit_code)`；
设 `MODELFORGE_DEBUG_TEARDOWN=1` 时保留 Python 正常收尾，便于调试。

**验证**：`reports/gui_exit_probe.py` 四种模式进程退出码均为 `0`（见 §5）。

### GUI-BUG-02：页面销毁时在途线程导致 `0xC0000409`

**现象**：页面（或父窗口）销毁时若其名下 `ApiWorker` 仍在运行，Qt 析构运行中线程触发
`qFatal`，进程以 `0xC0000409` 结束。

**证据**：单页面探针构造 `RuntimePage` 后立即退出 → `0xC0000409`；等待 0.5s 让 worker 结束
→ `0`。旧 `closeEvent` 只回收 6 个页面，`models`/`chat`/`extensions`/`automation`/
`control_center`/`settings`/`developer` 等在途线程无人回收。

**修复（前序提交）**：`shutdown_async_api` 超时后把线程与页面临时解绑并交给进程级
`_ORPHANED_WORKERS`；`closeEvent` 遍历全部页面回收；`main()` 退出前
`wait_for_api_workers(5000)`。

**本轮独立验证**：`reports/gui_exit_probe.py --mode slow`（请求在宽限期内结束）与
`--mode overrun`（请求超出宽限期，走"仍有线程"分支）均退出 `0`，且 stderr 无
`fatal exception`；`tests/test_gui_async_worker.py` 断言解绑后页面不再收到迟到结果。

### GUI-BUG-03：离屏渲染审计脚本退出码非 0、不判定槽内异常

**现象**：`reports/render_pages_offscreen.py` 打印 `ALL_CAPTURES_OK` 并产出全部 33 张图，
但退出码为 `0xC0000005`；桩返回 `[]` 时页面在 Qt 槽内抛
`AttributeError: 'list' object has no attribute 'get'`，脚本仍判定成功。

**根因**：桩与客户端契约不一致；PySide6 只打印槽内异常，不改变退出码；另外当
`model_readiness != READY` 时首次使用向导会以模态方式打开，把事件循环拖进嵌套循环，
使审计耗时从约 40s 膨胀到 100–180s。

**修复**：

1. 新增 `reports/desktop_contract_stub.py`：从 `ModelForgeClient` 的返回注解推导默认值
   （`dict`→`{}`、`list[dict]`→`[]`），未定义的方法显式报错，并记录被调用端点；
2. 桩的就绪快照改为 `READY`，首次使用向导不再打开；
3. 审计脚本安装 `sys.excepthook` 捕获槽内异常并计入失败，同时加 15s 步进看门狗
   （模态对话框卡住事件循环时输出 `CAPTURE_STALLED` 并以非 0 退出）；
4. 结束时 flush 后 `os._exit(exit_code)`。

**验证**：输出 `ALL_CAPTURES_OK` + `ENDPOINTS_TOUCHED 26`，退出码 `0`，无槽异常。

### GUI-BUG-04：payload 形状防御与失败可见

**现象**：页面槽函数直接 `payload.get(...)`；服务返回的形状不符时异常在槽内被打印吞掉，
页面静默停在旧状态，用户与测试都看不到失败。

**修复（三层）**：

1. `api_client/client.py`：响应对象 `ResponsePayload.get()` 按调用方给出的默认值校验字段类型，
   不符抛 `INVALID_RESPONSE_SHAPE:<字段>`；非法 JSON 抛 `INVALID_RESPONSE_BODY`；
   标量 JSON 抛 `INVALID_RESPONSE_SHAPE:<path>`；
2. 返回裸数组的端点（`list_models`/`list_sessions`/`list_agents`/`knowledge_documents` 等 13 个）
   改用 `_get_list` / `_post_list`，收到对象而非数组时抛
   `INVALID_RESPONSE_SHAPE:<endpoint>`，避免"迭代到字典键"这种静默错位；
3. `components/api_worker.py` 在投递边界捕获处理函数异常，记录日志并以
   `CLIENT_RENDER_FAILED:<code|异常类型>` 走页面失败回调；失败回调自身再抛也不会逃逸。

**验证**：`tests/test_desktop_payload_shape.py` 9 条（数组/对象/字段/非法 JSON/标量/
处理函数异常可见化/失败回调不逃逸/关停后不收迟到结果）全部通过。

### GUI-BUG-05 / GUI-BUG-06：CI 与退出码回归缺口

**修复**：

- `.github/workflows/ci.yml` 的 `desktop` 作业从 5 个文件扩展到 12 个文件，覆盖全部 10 个
  GUI 文件（含 `test_desktop_shutdown.py`）与两个新增回归文件；
- 新增 `tests/test_desktop_process_exit.py`：以子进程运行 `reports/gui_exit_probe.py`，
  断言 `fast`/`slow`/`overrun`/`realclient` 四种场景 `returncode == 0` 且输出无 `fatal exception`；
- README「测试」一节同步为 10 个 GUI 文件，并更新无 PySide6 时的 ignore 列表。

**验证**：桌面相关 16 个文件、62 条用例全部通过（见 §5）。

### GUI-BUG-07：孤儿 worker 治理

**修复**（`components/api_worker.py`）：

- `_prune_finished_orphans()`：在 `pending_api_workers()`／诊断／退出日志前先清掉线程已结束的条目，
  避免把"已结束但事件循环还没回收"的 worker 报成在飞；
- `orphaned_worker_report()`：输出每个保留 worker 的操作名、是否仍在运行、已保留毫秒数；
- 超过 `_ORPHAN_WARN_THRESHOLD`（2）时记录结构化告警；
- `log_pending_api_workers()` 在退出前输出待处理请求；保留线程只做"钉住 + 上报"，
  不主动丢弃（丢弃运行中的 QThread 正是要避免的崩溃）。

**验证**：`tests/test_gui_async_worker.py` 新增 2 条（保留报告含年龄/操作名、退出前日志
且无待处理时保持安静）通过。

## 4. 改动清单

| 文件 | 作用 |
|---|---|
| `client/pyside6/main.py` | 确定性退出 `_exit_process()`，退出前记录在飞请求 |
| `client/pyside6/components/api_worker.py` | 投递边界异常可见化、孤儿 worker 诊断与清理 |
| `client/pyside6/api_client/client.py` | 响应形状与字段类型校验（`ResponsePayload`、`_get_list`） |
| `reports/desktop_contract_stub.py` | 契约形状的 QA 桩（按真实客户端注解推导） |
| `reports/gui_exit_probe.py` | 进程级退出探针（fast/slow/overrun/realclient） |
| `reports/render_pages_offscreen.py` | 槽异常计入失败、步进看门狗、确定性退出 |
| `tests/test_desktop_process_exit.py` | 子进程退出码回归 |
| `tests/test_desktop_payload_shape.py` | 形状边界与失败可见化回归 |
| `tests/test_gui_async_worker.py` | 孤儿 worker 诊断与保留行为回归 |
| `.github/workflows/ci.yml` | desktop 作业扩展到全部 GUI 文件 + 退出码回归 |
| `README.md` | GUI 文件数量、ignore 列表与退出码说明 |

## 5. 验证结果（2026-09-13）

| 验证项 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check backend client tests scripts reports` | 通过 |
| 空白检查 | `git diff --check` | 通过 |
| 全量套件 | `.venv-gui\Scripts\python -m pytest -q tests/`（空载） | **1063 passed / 4 skipped** |
| 桌面相关用例 | `.venv-gui\Scripts\python -m pytest -q` 16 个桌面/客户端文件 | 62 passed |
| 退出码回归 | `pytest -q tests/test_desktop_process_exit.py` | 4 passed（四种场景均退出 0） |
| 形状边界 | `pytest -q tests/test_desktop_payload_shape.py` | 9 passed |
| 渲染审计 | `.venv-gui\Scripts\python reports\render_pages_offscreen.py` | `ALL_CAPTURES_OK`、`ENDPOINTS_TOUCHED 26`、退出码 `0` |

进程级退出码 A/B（`reports/gui_exit_probe.py`，空载）：

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 关闭窗口时无在途请求 | `0xC0000005` | `0` |
| 关闭窗口时有请求在宽限期内结束 | `0xC0000005` | `0` |
| 关闭窗口时请求超出宽限期 | `0xC0000005`（更早实现为 `0xC0000409`） | `0` |
| 真实 `ModelForgeClient`、无后端 | `0xC0000005` | `0` |

## 6. 残余风险与后续建议

- **平台覆盖**：`0xC0000005`/`0xC0000409` 均在 Windows + PySide6 6.11.1 观察；CI（ubuntu）
  已纳入同一批用例，若 Linux 侧出现不同的收尾行为，会在 `desktop` 作业暴露。
- **调试入口**：`MODELFORGE_DEBUG_TEARDOWN=1` 会保留 Python 正常收尾（该路径仍可能触发
  `0xC0000005`），仅供调试使用。
- **测量干扰**：同一渲染脚本耗时在不同时段从 38s 波动到 178s，并行跑全量套件时按目的地
  放大约 6 倍；耗时只能在同一时段的空载条件下横向对比，不要作为性能门槛。
- **孤儿线程语义**：保留线程只在进程退出时释放；已发出的服务端写操作不承诺取消
  （沿用前序设计结论）。
- **已知顺序性抖动（待跟进）**：在同时跑两个全量套件的重负载下，
  `tests/test_desktop_task_client.py::test_task_events_and_logs_use_bounded_query_params`
  曾以 `StopIteration` 失败一次（mock 的 `side_effect` 被额外一次 HTTP 调用消耗）；
  空载复跑两次全量均通过（`1063 passed / 4 skipped`）。根因是更早的 GUI 用例构造 `MainWindow`
  时排定的 `QTimer.singleShot(1800, _check_for_updates)`，在测试主线程长时间阻塞
  （如子进程退出码用例）后集中触发，出界的真实网络调用落到了后续用例的 mock 上。
  建议后续把该定时器绑定到窗口生命周期（`closeEvent` 里取消），或在构造 `MainWindow` 的用例中
  把 `updater` 换成 no-op；本轮的进程级退出测试不依赖它。
