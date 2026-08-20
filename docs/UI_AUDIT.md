# ModelForge Future UI 2.0 — UI Audit

## 1. Current UI Architecture

桌面端为 PySide6 薄客户端。`main.py` 目前用 `QMainWindow + QTabWidget` 承载工作台、运行时、聊天、数据集、训练、知识库和 Agent；任务中心是右侧 `QDockWidget`。所有页面复用 `ModelForgeClient` 和 `AsyncApiMixin`，在后台 `QThread` 发起 REST 请求；全局 `TaskStore` 使用快照加 SSE 游标维护任务状态。

## 2. Current Navigation

现有主导航是顶层标签页，模型中心、下载、任务中心等能力通过传统菜单和 Dock 入口暴露。聊天还嵌入会话侧栏。该结构功能完整，但入口分散，页面身份弱，难以形成“本地 AI 工作站”的稳定操作骨架。

## 3. Current Page Inventory

| 页面/组件 | 真实数据与行为 | 当前界面形态 |
|---|---|---|
| 工作台 | 任务摘要、引导状态、模型与任务入口 | 若干 `QGroupBox` 与快捷按钮 |
| 运行时 | `/runtime/status`、模型启停 | 标题、表格和操作按钮 |
| 聊天/会话 | 会话 CRUD、模型加载、流式聊天 | 分割器、文本框与表单 |
| 数据集 | 列表、上传、校验、删除 | 表格、对话框与局部工具栏 |
| 训练 | 任务、模板、轮询、停止与注册 | 表格、表单与进度文本 |
| 知识库 | 文档、检索、问答、删除 | 列表与文本结果 |
| Agent | Agent CRUD、Run、审批与事件时间线 | 表单、列表和时间线 |
| 任务中心 | 任务 SSE、重试、取消、日志、导出 | 右侧 Dock + 列表/详情/日志 |
| 登录 | 注册与 Bearer 登录 | 传统 `QDialog + QTabWidget` |

## 4. Current Component Inventory

现有可复用基础是 `AsyncApiMixin`、`TaskStore`、`TaskCenterDock`、聊天/Agent 流 Worker 和会话侧栏。项目没有主题令牌、统一卡片/指标/状态/空态组件或图标系统。样式主要散落在页面内 `setStyleSheet` 调用，导致颜色、间距、字号、状态语义不一致。

## 5. Existing Problems

页面以 Qt 默认控件为主；`QTabWidget`、`QGroupBox`、`QTableWidget`、Dock 和传统菜单共同构成“工具软件”观感。工作台没有真正的 Command Center 信息层级；任务、运行时、Agent 与模型数据虽是真实 API 数据，却未形成统一遥测、状态和决策语言。

## 6. UX Problems

导航将主要页面、模型下载、任务中心和刷新入口分散在标签、菜单和浮动 Dock 内。加载、空结果、权限、连接状态和失败状态多以文本或消息框呈现，缺少连续、可扫描的反馈。登录不像连接本地工作站，聊天也缺少运行时遥测区域。

## 7. Visual Problems

当前浅色默认控件、可变圆角、硬编码绿/红/蓝文本和页面级 StyleSheet 缺少整体性。排版没有区分产品标题、操作文本与工程数据；图标策略不统一，部分页面存在 emoji。视觉密度与留白未经统一度量，无法达到专业 AI Workstation 质感。

## 8. Information Architecture Problems

缺少稳定左侧导航、当前页面标题、全局系统状态、Activity Stream 和 Settings 信息架构。`Runtime` 既是核心操作区又位于普通标签内；`TaskCenterDock` 是关键 Operations Center，却不是一级可发现空间。

## 9. Technical UI Problems

页面可以调用真实 API，但组件无共享设计系统，重构成本高。当前项目已存在异步 Worker、SSE 和关闭收敛改动；UI 重构必须沿用这些边界，不得把网络请求带回 GUI 主线程。无独立版本发布资产时，更新器会安全地仅报告没有可安装版本。

## 10. Risk Areas

UI 改造不能改动认证、REST 合约、任务 SSE、聊天流、训练/Agent 行为或数据库。全局 `TaskStore`、聊天 `StreamWorker`、Agent `EventStreamWorker` 和 API Worker 的生命周期必须保持受控。真实系统没有的 GPU、VRAM、吞吐或 Activity 数据一律显示 `Unavailable`，不得伪造。

## 11. Recommended Refactoring Strategy

先建立 `theme/` 令牌、图标、组件和全局样式；再以左导航、顶部系统栏、状态栏和内容栈替换标签骨架，同时保留现有页面实例与 API Client。随后按 Command Center、聊天、模型/运行时、数据/训练/知识、Agent、任务、登录/设置的顺序迁移。每个阶段保持可运行，执行离屏与真实 API 回归，最后保存全页截图和 QA 报告。
