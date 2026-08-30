# ModelForge 桌面客户端 UI 修改报告（2026-08-30）

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
