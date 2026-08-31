# ModelForge 桌面客户端 UI 审核报告（2026-08-30）

## 1. 审核范围与方法

- **对象**：`client/pyside6/` 桌面客户端全部 14 个导航目的地、任务中心 Dock 与登录对话框，双主题（Light/Dark）。
- **方法**：静态代码走查（页面、主题 token、i18n、组件）+ 真实离屏渲染逐页截图。截图通过 `reports/render_pages_offscreen.py`（`FakeApi` 桩，不触网、不执行真实动作）在 `modelforge:gui-test` 容器（Linux + Qt offscreen + Noto CJK 字体，与 CI desktop 作业同构）中生成，输出至 `reports/ui-audit/`（修改后）与 `reports/ui-audit-before/`（修改前留档，未入库）。
- **参照规范**：`docs/MODELFORGE_DESIGN_SYSTEM.md`、`docs/UI_AUDIT.md`（上一轮审计）、`theme/tokens.py`。
- **与上一轮审计的关系**：`UI_AUDIT.md` 指出的"QTabWidget 顶层导航、无 token、无 MF 原语"等结构性问题已在现行 AppShell 架构中修复；本次审计聚焦遗留债务与新发现。

## 2. 总体结论

整体架构健康：AppShell 左导航 + QStackedWidget 骨架清晰，主题走"Python token → 属性选择器 QSS"的正确路线，10/18 页面已使用 MF 原语，任务中心的禁用态与活动页空态是标杆。**但存在 1 个功能性渲染缺陷、多处暗色主题可读性缺陷、大范围中英文混排，以及 4 个页面的危险按钮在空数据时仍可点击。**按 P0/P1 修复批次处理后（见 `UI_REMEDIATION_REPORT_2026-08-30.md`），剩余问题均为 P2 交互打磨项。

## 3. 发现清单

### A. 功能性缺陷（P0，已修复）

| 编号 | 问题 | 位置 | 证据 |
|---|---|---|---|
| A1 | `RunTimeline._append_tool_card` 执行 `view.append(str(card))`，`str(QFrame)` 返回对象地址（如 `<PySide6.QtWidgets.QFrame object at 0x…>`），**工具调用的参数与结果从未真正显示**，时间线里是乱码行 | `pages/run_timeline.py`（修改前 L157-160） | 代码走查；Run 时间线仅在有真实运行时出现 |
| A2 | 时间线全部事件颜色硬编码（`#1565C0/#333/#888/#2E7D32/#D32F2F/#E65100/#F57C00/#666`），暗色主题下 `#333/#666` 文本近乎不可见 | 同上（修改前 L55-153） | token 对照 + 暗色截图 |
| A3 | 时间线等宽字体写死 `font-family: monospace`，未接 `FONT_MONO` token | 同上（修改前 L84） | 代码走查 |

### B. 主题与视觉一致性（P1，已修复）

| 编号 | 问题 | 位置 |
|---|---|---|
| B1 | `task_center.py` 连接状态 4 处硬编码 Material 色（`#2e7d32/#c62828/#1565c0/#ef6c00`），暗色主题对比度不足且不随主题切换 | `components/task_center.py`（修改前 L130-144） |
| B2 | QSS 未覆盖 `QTabWidget/QTabBar`：控制中心 8 个页签呈原生小方块样式，与整体设计割裂 | `theme/theme.py` + 截图 `ui-audit-before/light-control.png` |
| B3 | QSS 未覆盖 `QDockWidget`：任务中心 Dock 标题栏为原生样式 | 同上 + `ui-audit-before/light-tasks.png` |
| B4 | `QComboBox::drop-down/down-arrow` 未样式化，下拉框右侧出现原生箭头按钮叠在圆角边框内 | 同上 + `ui-audit-before/light-training.png` |
| B5 | `theme/metrics.py` 与 `theme/tokens.py` 双源冲突：`TOPBAR_HEIGHT` 68 vs 52、`MIN_WINDOW` 1180 vs 1120；metrics 中 `TOPBAR_HEIGHT` 为死值（无人导入） | `theme/metrics.py`、`theme/tokens.py` |
| B6 | 导航栏 4 个次级目的地（Agent 工作台/自动化/控制中心/扩展治理）缺图标定义，`glyph()` 回退为"·"，视觉上与主项不一致 | `theme/icons.py` + 各截图侧栏 |
| B7 | `QCheckBox/QRadioButton/QToolTip/QSpinBox/QSplitter/横向滚动条` 无主题规则，呈控件原生观感 | `theme/theme.py` |

### C. 国际化（P1，中文界面出现英文，已修复）

| 编号 | 文案 | 位置 |
|---|---|---|
| C1 | 按钮 `PREVIEW` / `Training preflight` / `Delete selected` | `pages/dataset_page.py`（修改前 L70） |
| C2 | 状态徽标 `0 datasets synced`、`Syncing datasets`、`Datasets unavailable` | `pages/dataset_page.py` L42/94/97 |
| C3 | 表头 `Run / Agent / Status / Output`、徽标 `0 Agents synced` | `pages/agent_page.py` L192/269 |
| C4 | GroupBox 标题 `Training configuration` / `Run detail`、徽标 `Tasks updating` | `pages/training_page.py` L53/66/109 |
| C5 | 徽标 `RUNTIME SYNCHRONIZED` | `pages/runtime_page.py` L107 |
| C6 | 登录页 `BACKEND ENDPOINT <url>`、`CONNECTION FAILED`、`BACKEND AUTHENTICATED`、占位符 `WORKSTATION USERNAME`/`ACCESS PASSWORD` | `pages/login_dialog.py` L42/91/92/132/137 |
| C7 | 聊天页 provider 选中态 `<name> selected` | `pages/chat_page.py` L166 |

**i18n 机制性根因**：三轨制（36 个 JSON 外壳 key / `_TEXT` 中文源串词典 / 硬编码中文）中，`_TEXT` 词典是实际主力，但新增文案未同步录入，且部分页面直接英文硬编码。本次修复统一回归"中文源串 + `_TEXT` 三语条目"轨道。

### D. 状态与交互（P2，未修改，建议下一批次）

| 编号 | 问题 | 位置 |
|---|---|---|
| D1 | 空数据时危险操作按钮仍可点：扩展治理 7 个操作按钮、自动化"启用/暂停/立即运行/删除计划"、控制中心"编辑/删除所选记忆"、智能体页"取消运行"（数据集页同类问题已在本次修复，作为范式） | `pages/extensions_page.py`、`automation_page.py`、`control_center_page.py`、`agent_page.py` |
| D2 | 页面身份不一致：Agent 工作台/控制中心/自动化/扩展治理只有 eyebrow 无大标题（H1），与概览/模型/训练等页不一致 | 同上四个页面 |
| D3 | 空态不统一：MFEmptyState（活动/模型页，佳）vs 纯文本"暂无记忆。"/"暂无计划…"（控制中心/自动化）vs 纯空白（扩展治理/智能体列表） | 相应页面 |
| D4 | 状态栏泄漏内部信息：页脚显示原始 `base_url`（`已连接到 http://…`）、任务中心显示原始错误码（如 `OPERATION_FAILED`/`TASK_SSE_DISCONNECTED`） | `main.py` `_navigate_to/_load_status`、`task_center.py` |
| D5 | 命名不一致：导航与顶栏叫"对话"，聊天页 H1 却是"聊天" | `pages/chat_page.py` |
| D6 | 对话页会话列表空态仅有顶部一行小字，大片留白未用 `MFEmptyState` | `pages/session_sidebar.py` |
| D7 | 控制中心按钮整行堆叠（新建/编辑/删除各占一行），信息密度低 | `pages/control_center_page.py` |

### E. 文档与实现脱节（P2，未修改）

| 编号 | 问题 |
|---|---|
| E1 | `MODELFORGE_DESIGN_SYSTEM.md` 描述的深色工程面板 token（`BG #07090D`、CYAN `#4DE8FF`、半径 4/6/8）与实现（zinc 中性色 `#0F0F10`、accent=前景色、半径 6/8/10、含浅色主题）完全不一致。文档是"目标态"，实现是"现状"，二者必须择一对齐，否则新页面无所适从。 |
| E2 | 设计文档最小视口 1180×720 与 tokens 1120×720 冲突（本次修复已按文档统一到 1180×720，见修改报告）。 |

### F. 测试基建（P2，未修改）

| 编号 | 问题 |
|---|---|
| F1 | 8 个桌面测试文件**按特定顺序连跑**时，`test_chat_cursor` 会因前置文件创建/销毁 QApplication 导致 fatal abort（`QApplication.instance() or QApplication([])` 未持有引用）。CI 按文件名字母序恰好避开该顺序。建议各测试文件模块级持有 QApplication 引用，或统一用 pytest fixture。复现：`pytest tests/test_desktop_api_errors.py tests/test_desktop_resilience.py tests/test_desktop_task_client.py tests/test_gui_async_worker.py tests/test_chat_cursor.py`（分两批跑则全绿，本次验证即分两批执行）。 |

## 4. 正面观察

- AppShell 左导航 + 命令面板（Ctrl+K）+ 右侧任务 Dock 的信息架构清晰，页脚状态条分区合理。
- `mf/primitives.py` 原语（MFPanel/MFSection/MFMetric/MFStatusBadge/MFEmptyState）设计正确，采用率达 10/18 页。
- 任务中心的重试/批量重试/取消/日志按钮禁用态随数据联动，是全应用状态管理的标杆（D1 各页应向它看齐）。
- 活动页、模型页的空态设计符合规范（明确告知数据从何而来）。
- 页面均不在 GUI 线程做 HTTP，统一经 `AsyncApiMixin`/专用 QThread，架构红线执行到位。

## 5. 证据索引

- 修改前截图：`reports/ui-audit-before/{light,dark}-{目的地}.png`（31 张，本地留档）
- 修改后截图：`reports/ui-audit/{light,dark}-{目的地}.png` + `dark-login.png`（31 张，本地留档）
- 重新生成：`docker build -f Dockerfile.gui-test -t modelforge:gui-test . && docker run --rm -v "$(pwd):/app" -w /app modelforge:gui-test python reports/render_pages_offscreen.py`
