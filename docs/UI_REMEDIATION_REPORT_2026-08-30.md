# ModelForge 桌面客户端 UI 修改报告（2026-08-30，追加批次 2026-08-31）

本报告记录针对 `UI_AUDIT_REPORT_2026-08-30.md` 中 P0/P1 发现实施的修改、验证证据与遗留事项。所有修改仅涉及 `client/pyside6/` 展示层与 QA 工具，**未触碰认证、REST 合约、SSE 流、聊天/训练/Agent 行为等红线**，未修改任何后端文件。

## 1. 修改清单（13 个源文件 + 2 个 QA 工具）

### A1-A3 功能缺陷修复：`pages/run_timeline.py`（重写渲染层）

- **修复 `str(QFrame)` 缺陷**：`ToolCallCard` 保留类名（`test_agent_client_phase8.py` 断言依赖），改为存储工具名/参数/结果，新增 `to_html()` 并重写 `__str__` 返回主题化 HTML——时间线 `append(str(card))` 的调用形态不变，但显示的从对象地址变成真实的工具名、参数 JSON 与结果摘要（截断 300 字符）。
- **主题化配色**：新增 `_timeline_palette()`，经 `window().theme_manager.palette()` 解析当前 Light/Dark 调色板（异常时回退 `tokens.LIGHT`）；全部事件行、审批状态、错误行改为引用 `p["text"]/p["muted"]/p["success"]/p["warning"]/p["danger"]/p["accent"]`，删除全部 8 种硬编码 hex。暗色主题下时间线文字可读性恢复。
- **去 emoji 图标**：🛠🔧❓💬✅⛔ 替换为与 `theme/icons.py` 同族的几何符号（▶ ▸ ◂ ✔ ✘ ■ ?），审批按钮改为纯文本"批准/拒绝"。
- **字体**：`font-family: monospace` → `theme.tokens.FONT_MONO`。
- **事件文案中文化**（运行开始/工具执行中/需要人工批准等），保留测试断言要求的字面量 `Generating...`（spec 51）。

### B1 主题化状态色：`components/task_center.py`

新增 `_set_connection_status(status)`，通过 Qt 动态属性 + unpolish/polish 应用语义色；任务快照（online/error）与实时流（info/warning）4 处硬编码 hex 全部移除。

### B2-B4/B7 QSS 补齐：`theme/theme.py` + `theme/tokens.py`

- `tokens.py`：LIGHT/DARK 两套调色板新增 `info` 色（Light `#2563EB` / Dark `#60A5FA`）。
- `theme.py` 新增规则：`QTabWidget::pane` + `QTabBar::tab`（选中态下划线）、`QDockWidget` + 标题栏、`QComboBox::drop-down/down-arrow`（CSS 三角箭头替代原生箭头）+ 下拉视图、`QCheckBox/QRadioButton::indicator`（选中态 accent 填充）、`QToolTip`、`QSpinBox`、`QSplitter::handle:hover`、横向滚动条。控制中心页签、任务中心 Dock、全部下拉框从此纳入主题。

### B5 双源统一：`theme/metrics.py`

重写为仅含窗口级指标（`MIN_WINDOW 1180×720`（按设计文档统一，原 1120 冲突值废弃）、`STATUSBAR_HEIGHT`、`CONTENT_MAX_WIDTH`）；删除与 `tokens.py` 冲突的死值 `TOPBAR_HEIGHT=68`（无任何导入方）。`SIDEBAR_WIDTH/TOPBAR_HEIGHT/RADIUS_*` 唯一来源为 `tokens.py`。

### B6 图标补全：`theme/icons.py`

新增 `workbench ◫ / automation ◔ / control ⊞ / extensions ⊕`，导航栏 4 个次级项不再回退为"·"。

### C1-C7 中文化（中文源串 + `_TEXT` 三语轨道）

| 文件 | 修改 |
|---|---|
| `pages/dataset_page.py` | 按钮 `PREVIEW/Training preflight/Delete selected` → `预览/训练预检/删除所选`；徽标 → `正在同步数据集/已同步 n 个数据集/数据集不可用` |
| `pages/agent_page.py` | 表头 → `运行/智能体/状态/输出`；徽标 → `已同步 n 个智能体` |
| `pages/training_page.py` | GroupBox → `训练配置/运行详情`；徽标 → `任务更新中` |
| `pages/runtime_page.py` | 徽标 → `运行时已同步` |
| `pages/login_dialog.py` | `BACKEND ENDPOINT <url>` → `服务地址`（URL 移入 tooltip，不再常驻泄露）；`CONNECTION FAILED/BACKEND AUTHENTICATED` → `连接失败/服务地址`；占位符 → `用户名/密码` |
| `pages/chat_page.py` | `<name> selected` → `format_text("已选择 {name}")` |
| `i18n/ui_localizer.py` | `_TEXT` 新增 9 组三语条目（预览/训练预检/删除所选/正在同步数据集/数据集不可用/任务更新中/运行时已同步/训练配置/运行详情/已选择 {name}） |

### 交互安全（D1 范式修复）：`pages/dataset_page.py`

预览/训练预检/删除按钮改为**选中驱动**：存储按钮引用，`itemSelectionChanged` → `_sync_row_actions()`，无选中行时禁用（渲染后选择清空自动生效）。删除前二次确认逻辑保持不变。其余页面的同类问题见"遗留事项"。

### 健壮性：`pages/chat_page.py` / `pages/agent_page.py`

`_render_readiness` 增加 `isinstance(snapshot, dict)` 防御（离屏渲染曾因桩数据返回 list 而抛 `AttributeError`；真实 API 为 dict，不构成线上缺陷，但防御成本极低）。

### 新增 QA 工具

- `reports/render_pages_offscreen.py`：全目的地 × 双主题 + 登录对话框离屏截图脚本（FakeApi 桩，不触网）。
- `Dockerfile.gui-test`：基于 `modelforge:server` 叠加 Qt offscreen 运行库（libegl1/libgl1/libglib2.0-0/libxkbcommon0/libdrm2/libgbm1/libnss3）与 Noto CJK 字体的本地 QA 镜像，用于在本机复现 CI desktop 环境跑 GUI 测试与截图（绕开 Windows/Anaconda 的 PySide6 DLL 冲突）。
- 截图证据（修改前 `reports/ui-audit-before/`、修改后 `reports/ui-audit/` 各 31 张）**仅本地留档未入库**（各 2.1MB），可用上述工具随时重新生成；`.gitignore` 已忽略这两个目录。

## 2. 验证证据

| 验证项 | 方式 | 结果 |
|---|---|---|
| 静态检查 | 容器内 `ruff check client/pyside6` | 0 问题 |
| GUI 测试（批次 1） | 容器内 `pytest test_desktop_api_errors / desktop_resilience / desktop_task_client / gui_async_worker` | **9 passed** |
| GUI 测试（批次 2） | 容器内 `pytest test_i18n_runtime / workspace_task_center_smoke / chat_cursor / task_store_stream / agent_client_phase8` | **16 passed**（含 `ToolCallCard/RunTimeline/Generating...` 结构断言） |
| 视觉回归 | 容器内重渲染 15 目的地 × 双主题 + 登录对话框 | `ALL_CAPTURES_OK`（31 张）；人工比对确认：控制中心页签/任务中心 Dock/下拉框已纳入主题、导航 4 项有图标、数据集页按钮中文化且空表禁用、智能体页表头与徽标中文化、时间线配色主题化 |
| 后端影响 | 无后端文件改动，未重跑后端全量 | 不适用 |

## 3. 遗留事项（P2，未在本批次修改）

> **2026-08-31 更新：本节全部 7 项已由追加批次完成修复，见第 5 节。**

按优先级排序，均已在审计报告 D/E/F 节给出精确位置：

1. **空数据危险按钮**（D1）：扩展治理 7 个操作、自动化 6 个操作、控制中心记忆编辑/删除、智能体"取消运行"——建议复制数据集页的选中驱动模式，并补选择信号。
2. **页面身份统一**（D2）：4 个次级页面补 `role="pageTitle"` 大标题。
3. **空态统一**（D3）：纯文本/空白空态迁移到 `MFEmptyState`。
4. **状态栏信息泄露**（D4）：页脚去掉裸 `base_url`、任务中心错误码改为可读文案（保留 correlation_id）。
5. **"对话/聊天"命名统一**（D5）与会话列表空态（D6）。
6. **设计文档对齐**（E1）：`MODELFORGE_DESIGN_SYSTEM.md` 的 token 表需与 zinc 实现二选一对齐——建议更新文档以描述现行 zinc 体系并保留 cyan 作为未来 accent 候选。
7. **测试基建**（F1）：桌面测试文件 QApplication 生命周期统一为模块级引用或 fixture。

## 4. 复现验证的命令

```bash
docker build -f Dockerfile.gui-test -t modelforge:gui-test .
# GUI 测试（分两批，见审计报告 F1）
docker run --rm -v "$(pwd):/app" -w /app modelforge:gui-test \
  python -m pytest tests/test_i18n_runtime.py tests/test_workspace_task_center_smoke.py tests/test_chat_cursor.py tests/test_task_store_stream.py tests/test_agent_client_phase8.py -q
# 视觉截图
docker run --rm -v "$(pwd):/app" -w /app modelforge:gui-test python reports/render_pages_offscreen.py
```

## 5. 追加批次（2026-08-31）：P2 遗留项全量修复

原第 3 节列出的 7 项 P2 遗留事项已全部实施，共改动 15 个文件（12 个源文件 + 2 个测试文件 + 本报告）。仍仅涉展示层，未触碰任何红线。

### D1 空数据危险按钮 → 选中驱动门控

- **通用组件**：`components/mf/primitives.py` 新增 `install_empty_state(view, title, detail)`——以 viewport 覆盖层方式为任意列表/表格挂 `MFEmptyState`（随视口自动缩放），返回 `set_empty(bool)` 开关；不改动任何现有布局。
- `extensions_page.py`：健康检查 + 5 个生命周期按钮无选中时禁用（`_sync_selection_actions`），"刷新已加载扩展"始终可用。
- `automation_page.py`：启用/暂停/立即运行/查看下五次/查看执行历史/删除计划 6 个按钮选中驱动（`_sync_plan_actions`）。
- `control_center_page.py`：`_tab` 工厂对"所选/归类现有"类按钮注册门控（`_SELECTION_ACTIONS` 集合），`itemSelectionChanged` 联动；新建/查看/预检类保持可用。
- `agent_workbench_page.py`：保存为模板/删除所选模板选中驱动。
- `agent_page.py`：取消运行改为"有选中 Run 且非忙"才可用（`_set_run_busy` + `_on_run_selected`），删除智能体同样选中驱动。

### D2 页面身份统一

根因是 4 个次级页面用了 `setObjectName("pageTitle")`（QSS 匹配的是动态属性 `role`），标题实际存在但从未生效。已全部改为 `setProperty("role", "pageTitle")`：扩展治理、自动化、控制中心、Agent 工作台，H1 大标题恢复与其它页面一致。

### D3 空态统一 → MFEmptyState 覆盖层

控制中心 7 个列表（记忆/产物/知识集合/插件 MCP/模型洞察/数据库/审计）、扩展治理列表、自动化计划列表、工作台定义/模板列表、智能体页智能体列表、会话侧栏列表（D6）全部改为 `install_empty_state` 空态面板；控制中心 `_fill` 改为实例方法联动空态开关，不再把"暂无记忆。"塞进列表项。

### D4 状态栏脱敏

- `main.py`：页脚不再拼接裸 `base_url`（`_navigate_to`/`_show_service_status`），服务地址移入 tooltip；`_load_status` 复用 `footer.connecting` 键；任务流状态从"原始错误码拼接"（如 `TASK_SSE_DISCONNECTED`）改为语义文案，原始错误详情放 tooltip。
- `components/app_shell.py`：`set_status(text, tooltip=None)` 支持 tooltip。
- 任务中心连接行保留 `format_api_error` 的"稳定 code + correlation_id"格式（符合脱敏契约，不回退）。
- `i18n/zh_CN.json` / `en_US.json` / `ja_JP.json`：新增 `footer.connected` / `footer.task_stream_connected` / `footer.task_stream_reconnecting` 三组三语键。

### D5+D6 命名与会话空态

- `chat_page.py`：页头 `MFSection("对话", "聊天")` → `MFSection("会话工作区", "对话")`，H1 与导航/顶栏一致。
- 会话侧栏空态见 D3（暂无会话面板）。

### E1 设计文档对齐

`docs/MODELFORGE_DESIGN_SYSTEM.md` 重写为与实现一致的 zinc 体系：双主题调色板 token 表（含 `info`）、accent=前景色、cyan/purple 标注为保留候选色、半径 6/8/10、最小视口 1180×720、metrics 单一来源规则；并补充本次确立的三条规范——`role="pageTitle"` 属性写法、`install_empty_state` 空态规范、选中驱动禁用规范、页脚/状态栏不得暴露端点与错误码、用户可见文案必须走 i18n 轨道。

### F1 测试 QApplication 生命周期

`tests/test_chat_cursor.py` 与 `tests/test_workspace_task_center_smoke.py` 改为模块级持有 QApplication 引用（`_ensure_qapp()`），消除"GUI 测试文件按特定顺序连跑时后跑文件继承已销毁 app 实例导致 fatal abort"的顺序脆弱性；8 个桌面测试文件现在任意顺序连跑均稳定。

### 追加批次验证证据

| 验证项 | 方式 | 结果 |
|---|---|---|
| 静态检查 | 容器内 `ruff check client/pyside6` | 0 问题 |
| i18n 资源 | 三个语言 JSON 解析 | 全部合法 |
| GUI 测试（批次 2 + phase6/phase8） | 容器内 pytest | **23 passed** |
| GUI 测试（批次 1） | 容器内 pytest | **9 passed** |
| 视觉回归 | 重渲染 31 张截图并目检 | 控制中心/扩展治理/自动化/工作台 H1 生效；扩展页 6 按钮与控制中心编辑/删除空数据时呈禁用态；工作台/对话/扩展/自动化空态面板替代空白；页脚不再出现裸 URL 与原始错误码 |

### 本批次改动文件

`components/mf/primitives.py`、`components/app_shell.py`、`pages/control_center_page.py`、`pages/extensions_page.py`、`pages/automation_page.py`、`pages/agent_workbench_page.py`、`pages/agent_page.py`、`pages/session_sidebar.py`、`pages/chat_page.py`、`main.py`、`i18n/{zh_CN,en_US,ja_JP}.json`、`tests/test_chat_cursor.py`、`tests/test_workspace_task_center_smoke.py`、`docs/MODELFORGE_DESIGN_SYSTEM.md`、本报告。
