# ModelForge 多模态对话与 Agent 沙箱开发计划

> 编制日期：2026-09-14
>
> 状态：待执行。本文是需求、设计约束、开发任务和验收标准，不代表功能已经实现。
>
> 适用项目：ModelForge，FastAPI 后端 + PySide6 桌面瘦客户端。
>
> 执行对象：Codex 或参与项目的开发者。按里程碑交付，不能仅完成界面后声称完成多模态或沙箱功能。
>
> 本次交付仅新增本文档，不修改业务代码、数据库、配置、依赖、既有计划或运行环境。

## 1. 产品目标与交付边界

### 1.1 产品目标

将现有文本对话升级为统一工作入口，使用户能够：

1. 在一条消息中输入文字，并添加文本文件、文档、图片、音频和视频。
2. 在发送前和发送后预览附件，选择实际提交给模型的内容范围。
3. 根据模型和工具的真实能力，获得文字、公式、代码、文件、图片、音频或视频。
4. 在同一对话内查看、下载、引用和继续修改生成成果。
5. 显式启用 Agent 执行，让主 Agent 委派子 Agent，在受控环境处理文件和运行代码。
6. 查看执行进度、工具操作、审批、资源消耗及错误，并能取消、恢复查看或手动重试。
7. 保留现有会话、纯文本聊天、模型配置、权限、任务中心和三语言体验。

### 1.2 必须区分的概念

| 概念 | 定义 | 不允许的混淆 |
|---|---|---|
| 预览能力 | 客户端能显示或播放某文件 | 能播放视频不代表模型能理解视频 |
| 模型原生能力 | 指定模型、协议和运行时能直接处理该模态 | 不能仅根据模型名称或 `MULTIMODAL` 标签推断 |
| 转换能力 | 解析、OCR、ASR、抽帧后交给模型 | 必须标明转换方式和遗漏范围，不能伪装成原生理解 |
| 生成工具能力 | 独立工具或专用运行时生成媒体、文件 | 不能冒充当前聊天模型的直接输出能力 |
| Agent | 具有任务、上下文、模型和工具权限的执行者 | 子 Agent 不自动获得父级全部数据和权限 |
| 沙箱 | 具备文件、进程、网络、资源隔离的执行环境 | 子进程、工作目录、命令白名单本身都不是完整安全沙箱 |
| 成果 Artifact | 已保存、可校验、可授权访问的实际产物 | 回复中描述了文件名，不等于文件已经生成 |

“各种文本文件”和“各种媒体”按支持矩阵逐步实现，不承诺任意格式都能解析。未知格式必须有明确降级和错误状态。

### 1.3 默认范围

- 保持桌面客户端，不新增 Web 前端，不切换 Electron、React 或其他 UI 框架。
- 保持后端承载业务、客户端负责交互的边界。
- 同时考虑本机后端与远程后端；不能假设客户端可以直接读取服务器文件路径。
- 优先交付文件 + 图片 + 文本回复的可用闭环，再交付音视频、成果版本和 Agent 沙箱。
- 每种生成模态至少实现并验证一个真实适配器，才可声明该模态已交付。
- 模型不存在、密钥缺失、硬件不足或解码器缺失时，禁用相关能力并给出原因，不伪造结果。
- 真实模型下载、付费调用、外部数据发送和系统依赖安装必须遵守显式授权边界。

### 1.4 非首版目标

- 实时双向语音、语音打断、实时摄像头、屏幕共享。
- 完整视频剪辑、音频工作站、在线 Office 编辑器。
- 多用户实时共同编辑、公开成果分享、自动发布到外部平台。
- 任意宿主机 shell、默认访问本机全部文件、默认联网的 Agent。
- 为多模态需求重写模型中心、训练系统、工作流引擎或全套任务治理。
- 所有供应商的所有多模态协议一次性支持。

这些功能进入后续扩展，不应成为基础版的隐含依赖。

## 2. 已核对的项目基础

以下为编制时对当前工作区的定向静态阅读，不是全量代码审计，也不代表相关模块已通过本轮运行验证。执行前必须重新核对，尤其是已有未提交改动。

| 领域 | 已有代码位置 | 当前观察 | 实施方向 |
|---|---|---|---|
| 聊天页面 | `client/pyside6/pages/chat_page.py` | `ComposerInput`、`StreamWorker`、纯文本 `QPlainTextEdit` 消息区 | 保留异步与停止能力，逐步替换消息展示和输入区 |
| 聊天 API | `backend/app/api/chat.py` | `ChatMessage.content` 为字符串，提供普通响应和 SSE | 新增结构化协议，旧路由保持兼容 |
| 聊天服务 | `backend/app/services/chat_service.py` | 历史和记忆注入、文本拼接、成功后保存问答 | 支持结构化内容、幂等轮次、失败及取消状态 |
| 持久化 | `backend/app/models/records.py`、`services/session_service.py` | Message 以 `content: Text` 为核心，按最近 50 条构造历史 | 保留文本投影，增量扩展结构化内容和上下文选择 |
| 模型能力 | `services/model_capabilities.py`、`model_capability_registry.py` | 已有 VISION/AUDIO/IMAGE/ASR/TTS/VIDEO 等分类 | 增加方向、协议、限制、证据和实时可用性，不新建平行注册中心 |
| 远程协议 | `services/runtimes/openai_api_runtime.py` | Responses 优先，可回退 Chat Completions；当前提取文本 | 分协议序列化多模态输入输出，严控回退语义 |
| 运行时 | `services/model_runtime_manager.py`、`services/runtimes/` | 统一模型加载、运行时解析和资源管理 | 新模态沿用模型、用户、运行时身份及租约 |
| Agent | `runtime/runtime.py`、`runtime/types.py` | Run 状态、取消、审批、事件和恢复基础 | 复用 Run 生命周期，绑定对话轮次 |
| 子 Agent | `runtime/tools/delegate.py` | 真实嵌套 Run，深度、循环、子数和预算保护 | 增加附件授权和成果回传；不能假定已具备并行委派 |
| 工具与文件 | `runtime/tools/`、`core/agent_file_access.py`、`services/agent_tools.py` | 工具策略、用户目录访问检查、诊断命令白名单 | 保留限制，另建隔离执行适配器，不放宽宿主命令入口 |
| 任务中心 | `services/task_service.py`、`task_execution.py`、`task_realtime.py` | 任务投影、执行入口和实时状态基础 | 新任务接入既有治理，不维护两份权威任务状态 |
| 客户端任务 | `components/task_store.py`、`task_stream_worker.py` | 快照、SSE 游标、断线恢复 | 复用订阅和恢复模式，避免聊天页面独立轮询全部任务 |
| 视频 | `api/videos.py`、`services/video_generation_service.py`、`video_runtime.py` | 已有视频任务和输出链路 | 聊天引用同一作业及成果，不复制视频生成服务 |
| 数据库升级 | `core/database.py`、`backend/alembic/versions/` | SQLite 增量迁移与服务端 Alembic 两条路径 | 两条升级路径均需设计与测试，不能仅增加 ORM 字段 |
| UI 体系 | `components/mf/`、`theme/`、`i18n/` | 公共组件、主题和中英日热切换 | 新组件遵循现有规范 |

编制时工作区已有模型、视频、Agent、任务、GUI、语言及测试相关未提交改动。不得覆盖、回退或顺手整理这些改动。

### 2.1 与已有计划的关系

- 沿用 `docs/GUI_UI_REDESIGN_SPEC_2026-09-14.md` 的视觉原则和窗口约束。
- `docs/GUI_UI_REDESIGN_TASK_PLAN_2026-09-14.md` 的原任务限制为 UI 整理；本文是新的业务能力扩展，不沿用其“不得改变 API”作为本项目限制。
- 该 UI 计划暂缓的内嵌播放器，由本文 M3 单独实现与验收，不改写历史验收结论。
- 控制平面所有权、错误、合同和协调约束继续有效，相关扩展要同步维护其目录与测试。
- 新增 API 后运行现有路由统计核验；仅按真实变更维护受影响文档，不手填未验证数量。

## 3. 用户工作流与功能需求

### 3.1 输入格式支持矩阵

| 输入 | M2 基础版 | M3 扩展版 | 处理原则 |
|---|---|---|---|
| 文字、Unicode、代码、Markdown | 完整 | 保持 | 保留原文、换行、编码信息 |
| TXT/MD/JSON/JSONL/CSV/TSV/LOG/常见源代码 | 上传、受限预览、文本提取 | 范围引用、表格分页 | 不执行文件，不默认把大文件全文放入上下文 |
| PNG/JPEG/WebP | 上传、缩略图、放大、视觉输入 | 区域引用 | 校验实际格式、尺寸和解码资源预算 |
| PDF | 上传、基础翻页、文本提取 | 页范围、扫描件 OCR | 扫描件无文字时明确需要 OCR |
| DOCX/XLSX | 暂不承诺解析，明确状态 | 段落/表格预览及提取 | 不运行宏、不执行公式、不跟随外部链接 |
| WAV/MP3/M4A/OGG | 暂不承诺理解 | 播放、ASR 或原生输入、时间段引用 | 容器与编码分别检查，保留转写来源 |
| MP4/WebM/MOV | 暂不承诺理解 | 播放、抽帧 + ASR 或原生视频输入 | 显示采样策略，不能声称检查了未采样帧 |
| SVG/HTML/XML | 作为文本 | 可选安全静态预览 | 默认不加载脚本、外部资源和实体 |
| HEIC/GIF、旧版 DOC/XLS、PPTX、压缩包及其他格式 | 不在首批白名单 | 按适配器扩展 | 不静默重命名为已支持类型，不自动解压执行 |

基础阶段对未启用格式给出明确说明并保留本地草稿选择；不将“可以选中”当作“可以上传并交给模型”。原始附件归档可后续独立启用，不能绕过服务端白名单。

### 3.2 输入与附件管理

- REQ-IN-01：选择文件、拖拽文件、粘贴截图、一次添加多个附件；纯附件消息可发送。
- REQ-IN-02：附件显示名称、类型、大小、处理状态；音视频显示可获取的时长。
- REQ-IN-03：上传、校验、解析分别显示状态，支持取消上传、删除草稿附件和手动重试。
- REQ-IN-04：中文、日文、空格、长文件名、重名文件不破坏布局，不影响真实存储路径。
- REQ-IN-05：使用稳定 `attachment_id` 引用文件；显示名不是授权凭证，也不能作为存储路径。
- REQ-IN-06：明确附件作用域：本条消息、当前会话、后续显式加入的上下文。不自动加入跨会话记忆或知识库。
- REQ-IN-07：发送前可选择页码、文本行、表格区域、图片区域或音视频时间段；显示最终选择摘要。
- REQ-IN-08：麦克风录音属于 M3 可选扩展，权限未授予时不影响文件上传；摄像头属于后续版本。

### 3.3 模型与执行路由

- REQ-MOD-01：展示所选模型的可用输入、可用输出、依赖工具、文件限制和能力来源。
- REQ-MOD-02：切换模型后重新验证草稿；不兼容附件不被丢弃，发送前说明处理选项。
- REQ-MOD-03：转换方式由用户确认或已保存的明确规则决定，不静默从图像理解改为 OCR。
- REQ-MOD-04：纯文本模型可读取提取后的文本，但不能收到图片占位符后被视为已“看见图片”。
- REQ-MOD-05：图片、音频、视频生成可选择独立工具模型，展示实际执行者和外发目的地。
- REQ-MOD-06：预检、浏览能力、预览附件不启动推理、不创建 Agent Run、不下载模型、不发生付费探测。
- REQ-MOD-07：模型能力存在但运行时、编码器、显存或配置不满足时，返回不可用原因。

### 3.4 消息、成果和持续修改

- REQ-OUT-01：消息支持文本、Markdown、代码、公式、表格、附件引用、图片、音频、视频和执行记录。
- REQ-OUT-02：文本流式增量更新；媒体显示真实任务状态，不伪造百分比或预览图。
- REQ-OUT-03：生成 TXT/MD/JSON/CSV 和代码文件必须实际写入成果存储，并提供下载和再次引用。
- REQ-OUT-04：中英日及常用数学符号不乱码；数学公式使用受控渲染器，不执行模型提供的脚本。
- REQ-OUT-05：成果区按当前会话列出生成文件，支持类型过滤、版本、预览、下载和关联消息定位。
- REQ-OUT-06：继续修改创建新版本，旧版本不可被隐式覆盖；并发修改使用版本检查。
- REQ-OUT-07：媒体只有完成完整性校验并保存后才能显示“可下载”；部分失败保留已完成成果并标记不完整。
- REQ-OUT-08：禁止通过任意 Markdown 链接自动抓取外部图片或服务器本地文件来生成成果。

### 3.5 对话控制与上下文

- REQ-CTX-01：保留停止、重试、历史加载；补齐发送失败、部分回答和取消后的持久化展示。
- REQ-CTX-02：编辑已发送消息默认创建分支，不重写历史；重新生成创建新的 attempt，不重复插入用户消息。
- REQ-CTX-03：支持消息搜索、固定重要消息、导出对话；已有会话新建、重命名、删除继续工作。
- REQ-CTX-04：展示本次请求包含的消息、附件、选择范围、摘要和估算用量。
- REQ-CTX-05：超出上下文限制时明确阻止或请求压缩确认，不静默截断后假装全文分析。
- REQ-CTX-06：长会话摘要保留来源范围；移除附件后不能继续通过摘要或索引隐式使用其内容。
- REQ-CTX-07：跨会话记忆延续现有能力，但提供当前轮次关闭选项；附件内容默认不自动提取为记忆。
- REQ-CTX-08：导出默认排除密钥、内部路径、原始工具敏感日志；包含附件原件需显式选择。

### 3.6 Agent 与沙箱体验

- REQ-AG-01：输入区有“对话 / Agent”模式；普通对话不因模型输出类似命令而运行代码。
- REQ-AG-02：Agent 模式提交前明确模型、文件授权、执行环境和预算。计划查看不等于执行授权。
- REQ-AG-03：主 Agent 和子 Agent 的任务、父子关系、模型、状态、耗时、工具和结果可查看。
- REQ-AG-04：支持取消子任务或整个任务树；取消请求与实际终止分开显示。
- REQ-AG-05：高风险工具等待审批，展示具体操作、目标、文件范围、联网域名和预计成本。
- REQ-AG-06：沙箱内输入只读、工作文件可写、输出经过校验导出；不能直接写入用户项目。
- REQ-AG-07：日志支持过滤和截断下载，默认仅展示操作摘要，不展示或索取模型内部思维链。
- REQ-AG-08：子 Agent 只继承授权清单和剩余预算；扩大范围必须重新审批。
- REQ-AG-09：可查看生成代码后再批准运行；批准后代码改变必须失效并重新审批。
- REQ-AG-10：环境不可用时禁用执行，允许继续文本聊天，不回退为宿主机直接执行。

## 4. 桌面交互与组件方案

### 4.1 页面结构

沿用应用现有会话导航，聊天页采用以下布局，不重复增加第二套会话侧栏：

```text
顶部：当前会话 / 模型与能力 / 对话或 Agent 模式 / 上下文入口
主体左侧：虚拟化或分页加载的消息时间线
主体右侧：可折叠检查器，按需显示预览 / 成果 / 执行 / 上下文
底部：附件队列 + 多行输入 + 工具选择 + 发送或停止
```

- 1024x680 最小窗口默认折叠检查器，预览使用弹窗或切换视图，不挤压到无法输入。
- 1280x800、1440x900 允许双区工作；高 DPI 和 125%/150% 字体缩放不遮挡操作。
- 输入区沿用已有多行能力，处理中文/日文输入法 composing 状态，不能在选词回车时误发送。
- 图标使用 `theme/icons.py` 现有入口；工具图标提供 Tooltip、accessibleName 和键盘焦点。
- 模式用分段或选择控件，二值权限用开关/复选框，数值用输入或步进器，不用文字按钮模拟全部控件。
- 批量附件有稳定缩略图尺寸和文件名省略规则；完整名称在详情中显示。
- 用户向上阅读时不因新 token 强制滚到底部；提供新内容提示。
- 流式更新按短时间窗口批处理，不每个 token 重建整个消息列表。
- 窗口关闭、页面销毁、账号切换必须清理播放器、线程、临时 URL 和下载缓存。

### 4.2 建议组件边界

下列是建议的新文件或模块职责，不要求机械地拆成同名类；实施前优先检查可复用组件。

| 组件 | 职责 |
|---|---|
| ChatComposer | 文本、附件队列、模式、发送预检 |
| MessageTimeline / MessageItem | 顺序、分页、增量内容块、引用和消息操作 |
| AttachmentQueue / AttachmentItem | 上传状态、进度、重试、删除 |
| PreviewPanel | 文本、图片、PDF、表格、音视频预览调度 |
| ArtifactPanel | 实际成果、版本、下载、再次引用 |
| RunInspector | 主子 Run 树、状态、工具日志、审批和取消 |
| ContextInspector | 本轮输入清单、转换记录、预算和排除操作 |
| ChatStore | 当前会话消息和轮次的客户端投影，不替代全局 TaskStore |

UI 文件建议放在 `client/pyside6/components/chat/`，页面负责组装和交互协调，不能把解析、权限、路径拼接和模型路由写进 QWidget。

### 4.3 预览实现约束

- 图片优先 Qt 原生能力；大图使用受限缩略图，原图按需读取。
- PDF 优先评估 QtPdf；音视频优先评估 QtMultimedia，实际支持取决于打包和平台编码器。
- 文本高亮和 Markdown 复用已有依赖；公式优先评估离线受控渲染，不加载 CDN。
- 初期 HTML 作为文本展示。未来使用 QtWebEngine 时必须关闭 JS、外部导航、文件访问及非白名单网络，并独立测试打包体积与权限边界。
- 播放器下载通过认证 API 或受控缓存；不能把 JWT 放进 URL、系统播放器命令行或日志。
- 不支持的编码显示原因和下载原件入口，不崩溃、不无限等待。

## 5. 后端架构与复用原则

### 5.1 目标数据流

```text
客户端草稿
  -> Attachment API -> 受管存储 -> 受限解析任务 -> 派生预览/文本
  -> Chat Preflight -> 权限 + 能力 + 上下文 + 预算校验
  -> Chat Turn -> ChatService 或已有 AgentRuntime
       -> 模型适配器 / 生成工具 / 沙箱执行器
       -> 持久化消息内容块、Run 事件和成果
  -> 事件流 + 快照 -> 消息时间线 / TaskStore / 成果区
```

### 5.2 服务职责

| 服务 | 职责 | 复用边界 |
|---|---|---|
| AttachmentService，拟新增 | 上传、所有权、状态、派生物、生命周期 | 知识库/数据集解析可复用函数，不复用它们的隐式索引副作用 |
| Content extraction adapters，拟新增 | 文本、PDF、表格、OCR/ASR、抽帧 | 受限任务执行，不在 HTTP 或 Qt 主线程解析 |
| Capability resolution，扩展 | 模型 + 运行时 + 协议 + 工具 + 环境的有效能力 | 依托现有模型注册和 readiness，不维护 UI 独立猜测表 |
| ChatService，扩展 | 结构化内容、上下文清单、轮次及事件 | 普通聊天不必强制转成 Agent Run |
| ArtifactService，拟新增 | 保存、校验、版本和授权下载 | 复用附件字节存储；视频等原任务仍为执行状态来源 |
| Sandbox provider，拟新增 | 环境生命周期、执行、限制、回收 | 接入已有 ToolExecutor 和 Policy，不另建策略系统 |
| Task projection，扩展 | 上传处理/聊天/媒体/沙箱的统一观察 | 任务中心是投影，具体执行记录仍各有唯一权威状态 |

### 5.3 关键工程约束

1. 不让内容块字典直接穿透所有运行时；在边界统一验证，再由适配器序列化。
2. 不把二进制、Base64、供应商临时 URL 或宿主绝对路径存进 Message 文本。
3. `user_id` 来自认证上下文，不接受模型输出、工具参数或客户端声明覆盖。
4. 预检和执行时均校验所有权与能力，防止预检后删除、换模型、撤销权限产生竞态。
5. 所有请求都有 correlation ID；副作用创建请求支持有作用域的幂等键。
6. 使用既有资源租约和队列；父 Agent 等待子 Agent 时不能占住子 Agent 所需的独占推理资源。
7. 不在跨线程或长期后台任务中复用请求级 SQLAlchemy Session；按执行单元创建短事务。
8. 不以客户端断开等同任务取消；旧聊天流维持旧语义，新轮次 API 按明确生命周期运行。

## 6. 数据模型与兼容策略

### 6.1 结构化内容块

内部协议建议使用带 `type` 判别字段的 Pydantic 联合类型，并带 `schema_version`。下例为设计示例，不是当前 API：

```json
{
  "schema_version": 1,
  "role": "user",
  "content": "请分析这张照片，并参考文档第 2 页。",
  "parts": [
    {"type": "text", "text": "请分析这张照片，并参考文档第 2 页。"},
    {"type": "image", "attachment_id": "att_example_image", "detail": "auto"},
    {
      "type": "file",
      "attachment_id": "att_example_pdf",
      "selection": {"kind": "pages", "pages": [2]},
      "processing": "extract_text"
    }
  ]
}
```

- 输入首批类型：`text`、`file`、`image`；M3 加 `audio`、`video`。
- 输出首批类型：`text`、`artifact_ref`、`citation`；后续加媒体引用和 `run_ref`。
- 代码/公式/Markdown 是文本格式属性，避免为每个语法新增顶层模态。
- `content` 保留为旧客户端文本投影；`parts` 存在时是语义来源。二者由服务端校验一致，不向模型重复发送两份文字。
- `parts` 缺失时，将旧 `content` 转为一个 text part；空文字 + 至少一个可用附件为有效输入。
- 不允许客户端伪造 assistant/tool 内容块进入持久会话，不扩大旧协议的角色信任边界。
- 页码与行号从 1 开始；时间以整数毫秒表示，区间为 `[start_ms, end_ms)`；图片区域使用 0 到 1 归一化坐标。
- selection 必须校验实际页数、时长、尺寸与范围；引用派生文本时保留原件和转换版本。
- 未知块由旧显示端展示安全占位，不丢失存储；当前写入端对未知类型明确拒绝。

### 6.2 建议持久化实体

实际表名在 M0 核对现有 records 后确定；不得因为本文的概念名称重复创建已有实体。

| 实体 | 关键字段/关系 | 必须保证 |
|---|---|---|
| Attachment | id、user_id、display_name、storage_key、sha256、MIME、size、state、metadata、created_at | 不透明 ID，所有权校验，上传完成前不可引用 |
| AttachmentDerivative | source_id、kind、processor_version、selection、storage_key、state | 原件不变，派生内容可追溯，可随原件清理 |
| Message 扩展 | parts_json、schema_version、status、turn_id、parent_message_id | 旧 content 字段保留；结构化列遵循现有 JSON-as-Text 模式 |
| MessageAttachment / SessionAttachment | message/session 与 attachment 的关联、scope | 外键与所有权一致，不能只靠前端过滤 |
| ChatTurn | id、user_id、session_id、idempotency_key、request_hash、status、context_manifest、capability_snapshot | 同一用户作用域的幂等键唯一；同键不同载荷返回冲突 |
| ChatAttempt | turn_id、attempt_no、output_message_id、run_id/job_id、status、usage | 重试新增 attempt，保留原失败结果与外部请求标识 |
| ChatEvent | turn_id、sequence、event_key、type、payload | 持久化后推送，序号唯一、终态唯一、可重放 |
| Artifact / ArtifactVersion | owner、session_id、message_id、producer_run/job、version、attachment_id、parent_version | 版本不可变，实际字节可校验，并发采用期望版本 |
| SandboxExecution | run_id、provider、environment_id、status、limits、exit_code、timestamps | 不重复拥有 Agent Run 状态；只描述具体执行环境/命令 |
| Approval 扩展 | run/tool call、参数摘要哈希、文件清单版本、权限、有效期 | 一次批准只适用于匹配操作，不能变成永久通行证 |

M0 必须决定：ChatEvent 是否能复用现有事件存储与 outbox。可以增加聊天领域记录，但不得建立与既有 TaskEvent 重复竞争的任务真相来源。

### 6.3 上传和生成状态

附件状态建议：

```text
UPLOADING -> VALIDATING -> READY
                  |         |
                  v         v
                FAILED   DELETING -> DELETED
UPLOADING -> CANCELLED
```

解析和预览是独立 processing job：`QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`，原件 READY 不意味着每种解析均成功。执行预检按所需派生物决定是否可发送。

聊天轮次使用独立领域状态，并显式映射到已有任务中心：

| ChatTurn 状态 | TaskStore 投影 | 含义 |
|---|---|---|
| QUEUED | QUEUED | 等待资源 |
| RUNNING | RUNNING | 正在生成或执行 |
| WAITING_INPUT | WAITING_INPUT | 等待审批或用户决定 |
| CANCEL_REQUESTED | CANCEL_REQUESTED | 已提出取消，尚未确认停止 |
| SUCCEEDED | SUCCEEDED | 完整完成 |
| PARTIAL | PARTIAL | 留有可用部分，但任务未完整完成 |
| FAILED / TIMED_OUT / INTERRUPTED | FAILED，附具体原因 | 明确失败、超时或重启中断 |
| CANCELLED | CANCELLED | 已确认本地终止或结束跟踪，并注明远端状态 |

现有 Agent `RunStatus` 保持原有词汇，通过映射接入聊天，不全局重命名既有状态枚举。

### 6.4 保存和重试语义

1. 新轮次接受后，在短事务内保存用户消息、轮次、初始事件和任务投影，再启动执行。
2. assistant 消息先保存为进行中，批量检查点保存增量，结束时转为完成/部分/失败/取消。
3. SSE 断线只重连同一轮次，不重新提交；HTTP 超时且结果未知时先查询幂等结果。
4. 明确重试创建新 attempt，并重新检查成本和授权，不重复保存用户消息。
5. 一条分支默认只允许一个活跃生成；并行比较必须显式创建不同分支，避免历史竞态。
6. 服务重启不能把残留 RUNNING 自动标成成功；可查询外部作业则对账，否则标记中断，等待用户选择。
7. 对不支持取消的远端服务显示“已停止接收，远端状态未知/可能继续计费”，不能宣称已停止供应商计算。
8. 超长日志和 SSE 增量有上限、批处理与背压，不为每个字符执行一次数据库提交。

### 6.5 数据库迁移

- 保持增量、可重复执行；默认不删除旧消息列，不重写历史正文。
- SQLite 本地升级覆盖 `core/database.py` 的迁移机制；PostgreSQL 覆盖 Alembic。
- 编制时 migration 目录有两个以 `0003_` 开头的文件，执行前根据 revision/down_revision 检查实际图，不能依据文件名前缀猜测新 revision。
- 新库、旧库、重复启动、失败重试、备份恢复均要测试；升级前提供备份和预检。
- 老消息可读取时懒映射为 text part；需要批量回填时应分批、幂等并记录进度。
- 关闭功能开关不删除新数据；旧客户端获得有意义文本投影和附件提示。
- 数据库降级不应靠破坏性删表实现。先说明兼容窗口，必要时使用升级前备份恢复。

## 7. API 与事件合同

以下为拟新增合同，正式编码前核对现有路由和错误目录。业务前缀沿用 `/api/v1`，外部 OpenAI 兼容 API 单独维护。

### 7.1 文件与成果 API

| 方法与路径 | 用途 | 关键约束 |
|---|---|---|
| POST `/attachments` | multipart 上传一个文件 | 流式写入临时文件、体积限制、用户配额、幂等标识 |
| GET `/attachments/{id}` | 元数据和派生处理状态 | 不返回内部路径或密钥 |
| GET `/attachments/{id}/content` | 授权下载原件 | Content-Type、安全文件名、Range/HEAD 合同验证 |
| GET `/attachments/{id}/preview` | 缩略图/分页预览/派生信息 | 类型白名单与授权，不启动模型处理 |
| POST `/attachments/{id}/process` | 请求某种解析或转换 | 显式操作、幂等、返回任务 ID |
| DELETE `/attachments/{id}` | 删除/撤销使用 | 定义引用冲突、取消处理和清理语义 |
| GET `/sessions/{id}/attachments` | 会话附件列表 | 分页及所有权 |
| GET `/sessions/{id}/artifacts` | 成果列表 | 按类型/消息/运行过滤 |
| GET `/artifacts/{id}/versions` | 版本列表 | 版本不可变 |
| GET `/artifacts/{id}/versions/{version}/content` | 下载确切版本 | 下载内容与哈希一致 |

上传首版允许失败后整文件重传，不承诺大文件分片续传。媒体阶段若引入分片，必须新增 upload session、分片校验、幂等完成和过期回收合同，不能把传输进度恢复伪装成字节级续传。

### 7.2 对话 API

| 方法与路径 | 用途 |
|---|---|
| GET `/chat/capabilities` | 按已解析目标返回有效能力、处理策略和依赖状态 |
| POST `/chat/preflight` | 校验草稿、输入清单、转换、输出和预算，返回无副作用预检 |
| POST `/chat/turns` | 创建持久轮次，返回 202、turn ID、消息 ID、必要的 run/job ID |
| GET `/chat/turns/{id}` | 权威快照、当前 attempt、终态和产物 |
| GET `/chat/turns/{id}/events?after_sequence=N` | 事件历史或流式订阅，具体响应协商在 M0 固定 |
| POST `/chat/turns/{id}/cancel` | 幂等取消请求，传递至实际执行器 |
| POST `/chat/turns/{id}/retry` | 显式创建新 attempt，不自动重放外部副作用 |
| POST `/sessions/{id}/branches` | 从指定消息创建分支，保持来源关系 |

- 保持 `/chat`、`/chat/stream` 的文本参数和既有 `delta/done/error` 语义；不直接把新事件强塞给旧客户端。
- 旧接口遇到无法无损表达的多模态请求应明确拒绝或要求新协议，不静默降成文件名。
- 新旧路径共享上下文、模型路由、权限和错误分类，不长期维护两套互相分叉的业务逻辑。
- 若现有会话消息接口加入 parts，必须检查客户端、SDK、历史分页和 OpenAI 兼容接口的兼容面。
- 普通聊天与 Agent 模式的参数相互校验；对话模式不能夹带可执行工具调用。

请求设计示例：

```json
{
  "schema_version": 1,
  "session_id": 42,
  "target": {"kind": "local", "model_id": 7, "runtime": "transformers"},
  "mode": "chat",
  "message": {"parts": [{"type": "text", "text": "请总结已选择的内容"}]},
  "requested_outputs": [{"type": "text"}],
  "context": {"excluded_message_ids": [], "use_memory": false},
  "idempotency_key": "client-generated-unique-key"
}
```

`target` 为互斥联合类型：本地用 model_id/runtime，远程用 provider_id/model；供应商密钥不进入客户端载荷。预检返回的结果不能作为绕过最终权限检查的凭证。

### 7.3 事件协议

建议新事件信封：

```json
{
  "schema_version": 1,
  "event_id": "evt_example",
  "turn_id": "turn_example",
  "attempt_id": "attempt_example",
  "sequence": 12,
  "type": "message.part.delta",
  "created_at": "2026-09-14T08:00:00Z",
  "correlation_id": "corr_example",
  "payload": {"message_id": 101, "part_id": "part_text_1", "delta": "分析结果"}
}
```

事件至少覆盖：

- `turn.created`、`turn.status_changed`、`turn.finished`。
- `message.created`、`message.part.added`、`message.part.delta`、`message.completed`。
- `attachment.processing`、`artifact.created`、`artifact.version.created`。
- `run.linked`、`run.status_changed`、`approval.required`、`usage.updated`、`error`。

一致性要求：

1. 每个 turn 的 sequence 严格递增；终态状态变更与终态事件原子提交，防止有结果无事件或重复结算。
2. 主子 Run 仍使用各自 run sequence；聊天聚合事件引用 `run_id + source_sequence`，不能把不同 Run 序号混作一个游标。
3. 客户端按 `(turn_id, sequence)` 去重，发现缺口先补历史/快照，不盲目拼接。
4. 事件历史过期返回明确 resync 要求和快照水位；从该水位继续，防止快照与订阅间丢事件。
5. SSE 传小型元数据和文本增量，不传大块二进制媒体。
6. 不支持的事件类型可以安全忽略并查询快照，但不能把未知终态当作成功。

### 7.4 错误合同

沿用现有 problem/error envelope、`correlation_id` 和脱敏规则；新错误码需登记、翻译并测试。

| 错误类别 | 建议错误码 | 行为 |
|---|---|---|
| 格式不支持/损坏 | ATTACHMENT_TYPE_UNSUPPORTED / ATTACHMENT_INVALID | 标记具体附件，不调用模型 |
| 配额或大小限制 | ATTACHMENT_LIMIT_EXCEEDED / STORAGE_QUOTA_EXCEEDED | 说明限制，不泄漏服务器容量细节 |
| 未准备好/已删除 | ATTACHMENT_NOT_READY / ATTACHMENT_UNAVAILABLE | 阻止执行，允许调整草稿 |
| 能力不匹配 | MODEL_INPUT_UNSUPPORTED / MODEL_OUTPUT_UNSUPPORTED | 提供切换模型或明确转换方案 |
| 解析/环境依赖 | PROCESSOR_UNAVAILABLE / MEDIA_CODEC_UNAVAILABLE | 预览或处理降级，不阻断纯文本 |
| 上下文预算 | CONTEXT_LIMIT_EXCEEDED | 展示需调整的输入范围 |
| 资源冲突 | 沿用 RUNTIME_BUSY / TRAINING_BUSY 等 | 不绕过租约 |
| 幂等/版本冲突 | IDEMPOTENCY_CONFLICT / ARTIFACT_VERSION_CONFLICT | 不重复执行或覆盖 |
| 沙箱/审批 | SANDBOX_UNAVAILABLE / SANDBOX_LIMIT_EXCEEDED / APPROVAL_EXPIRED | 默认拒绝，保留诊断摘要 |

对象不存在和对象无权访问对外统一，不能通过错误探测其他用户的附件、成果或 Run。

## 8. 模型能力与多模态适配

### 8.1 能力描述

每个有效能力至少包含：输入/输出方向、模态、原生或转换、协议、MIME 白名单、数量/体积/像素/时长限制、是否流式、工具调用能力、能力来源、验证时间、依赖就绪和不可用原因。

- 能力来源区分 runtime declaration、provider declaration、explicit verification、user configuration。
- 单次文本连接验证不能证明视觉、ASR、TTS 或视频可用。
- 缺失能力是 unknown，不等同 supported；有效限制取应用安全限额和供应商限制的更严格值。
- 用户手动配置可以启用待验证选项，但界面保留“未验证”，执行失败不能被吞掉。
- 格式/任务输出限制单独表达，例如仅允许 JSON 不等同可以生成任意二进制文件。

### 8.2 适配规则

1. Responses 与 Chat Completions 分别构造对应输入类型，不能原样转发内部 file/image 字典。
2. 本地 Ollama、transformers、GGUF 路径分别声明实际支持，不能让文本-only 后端收到媒体占位文本后继续执行。
3. 供应商需要 file upload API 时，保存远端文件 ID 的用户/provider 作用域、过期时间和删除状态。
4. 远程传输默认由后端读取受管原件并发送，不发布临时公网原件链接，不访问客户端路径。
5. 多模态协议回退只在未产生输出、能无损转换且请求无重复副作用风险时允许；否则明确失败。
6. ASR、OCR、抽帧、TTS、图像/视频生成是显式处理或工具步骤，其成本、失败和取消分别可见。
7. 视频生成复用当前 `VideoGenerationService`，关联 job ID；文本对话模型不能直接冒充视频模型。
8. 所有输出经类型、长度、实际字节和所有权校验后进入 ArtifactService。
9. 若需从供应商下载输出 URL，限定可信目标、校验每次解析/重定向、阻断私网/metadata 地址并限制体积与时间，复用现有网络安全规则。

### 8.3 原生与转换可追溯性

每次请求保存只含必要信息的 context manifest：消息 ID、附件版本/hash、selection、解析器和版本、抽帧时间点、转写时间段、截断/压缩决定、实际目标模型及协议。

不能将“不确定是否包含该页/该帧”写成确定事实。生成引用必须落在本次实际提交范围，客户端能定位原文、页码或时间点。

## 9. 文件存储、隐私和生命周期

### 9.1 存储设计

- 使用 `settings.data_dir` 下专用受管目录，目录层级由服务端内部 ID 决定。
- 上传临时目录与完成文件分离，写入过程计算哈希，验证完成后原子发布。
- 保存原始显示名但清理下载响应中的控制字符；禁止路径穿越、绝对路径、特殊设备文件和符号链接导入。
- 存储与数据库事务之间有中断窗口，提供孤儿文件/缺失文件对账，不能假定二者天然原子。
- 去重最多在用户范围内进行；不通过 hash 查询泄漏另一用户是否上传过相同文件。
- 下载要求认证和所有权；HTTP Range、HEAD 和缩略图必须执行与原文件相同授权。
- 客户端缓存按账号和后端实例分区，限制体积，退出登录清理敏感缓存，缓存命中也不能跨账号。

### 9.2 初始限制建议

以下是可配置初始值，不是已验证的模型上限；M0 在基准环境上确认。超限反馈必须发生在推理前。

| 项目 | 初始建议 |
|---|---|
| 每条消息附件数 | 10 |
| 文本/文档单文件 | 25 MiB |
| 图片单文件 | 20 MiB，解码后不超过 40MP，另设内存预算 |
| 音频单文件 | 100 MiB，首版处理时长不超过 30 分钟 |
| 视频单文件 | 250 MiB，首版处理时长不超过 10 分钟 |
| 单用户受管文件配额 | 5 GiB，原件、派生物、成果及临时文件共同计入 |
| 常规文本预览 | 首屏最多 200 KiB，后续分页，不一次载入整文件 |
| PDF 文本处理 | 最多 300 页；OCR 首批最多 50 个选定页 |
| 视频抽帧 | 最多 32 帧，显示采样位置，并受模型图片数限制 |
| CPU 解析任务 | 单任务默认 120 秒，可配置；重型 ASR/OCR 单独预算 |

上限在上传流、解码器、解析器、存储配额和模型请求处都要执行；不能只依赖客户端提示或 Content-Length。

### 9.3 清理与删除

- 未关联草稿和失败上传临时文件默认 24 小时回收；活跃上传有租约保护。
- 已发送附件和正式成果默认保留到用户删除，不静默按临时文件 TTL 回收。
- 删除消息默认解除关联；删除文件内容是独立明确动作，并说明受影响的消息、版本和引用。
- 文件撤销后立即禁止新下载和新任务使用，再异步取消处理并清理原件、派生物、缓存、索引及可清理的远端副本。
- 已经发送给远端模型的数据无法保证撤回，必须明确说明，不能承诺供应商物理删除。
- 摘要和上下文清单记录依赖来源；撤销文件后重新生成或失效相关可复用上下文。
- 审计保留最小必要元数据，不保留被删文件全文；备份留存与最终删除窗口写入产品说明。

## 10. 沙箱与 Agent 安全设计

### 10.1 实现路径

首个执行 provider 建议使用受控 Linux 容器后端。macOS/Windows 通过用户已安装并启用的兼容容器环境运行；未安装时仅禁用沙箱，不自动安装系统服务。

- 优先 rootless 或专用受限运行账户；记录实际隔离级别和残余风险。
- 容器不等于绝对安全，多租户不受信代码需要独立主机/VM 等更强边界评估；未验证前不开放公网多租户任意代码执行。
- 沙箱管理面位于可信后端，模型和容器不得接触 Docker socket 或容器管理凭据。
- 不把整个项目、用户主目录、密钥目录、模型目录、数据库或宿主 `/` 挂载进去。
- 初版仅支持明确的代码执行工具和固定镜像，默认 Python；其他语言按已装依赖增加。
- 固定镜像 digest 和受控依赖，记录版本；运行时联网安装依赖默认关闭。

### 10.2 环境结构与限制

```text
/input      本次授权文件的只读快照
/workspace  当前 Run 独立可写目录
/output     经验证后才能导出的成果目录
/tmp        有体积上限的临时目录
```

| 控制 | 初始要求 |
|---|---|
| 用户权限 | 非 root，无提权，移除无关 Linux capabilities |
| 文件系统 | 根只读，输入只读，输出和临时目录限额 |
| 网络 | 默认无网络；审批后通过受控代理按域名/目的地授权，禁用 host network |
| 资源 | 默认 1 CPU、1 GiB 内存、128 PID、1 GiB 工作空间、120 秒单次执行 |
| 输出 | stdout/stderr 默认各 1 MiB，标记截断；成果总量受配额限制 |
| 系统调用 | 使用支持的平台安全配置，不得以 privileged 或 unconfined 规避启动问题 |
| 凭据 | 默认无宿主环境变量和密钥；外部工具调用由后端执行，密钥不进生成代码 |
| 取消 | 先请求终止，超过宽限期强制停止整个执行环境，验证子进程已回收 |

限制必须由提供者实际强制执行，不能只写入 metadata。磁盘/PID/网络等限制在某个平台无法可靠执行时，该平台不能标为完整沙箱支持。

### 10.3 权限与审批

1. 继续通过现有 Policy 和 ToolExecutor 判断；新增 `sandbox.execute` 等能力，不放宽 `command_execute`。
2. 用户可授予本轮受限执行权限，但宿主写入、外部发送、敏感文件和网络范围变更必须单独确认。
3. 审批绑定 user、run、tool call、代码/参数哈希、输入版本、目标范围和有效期。
4. 批准前重新验证授权，批准后只执行已审阅版本；参数改变、重试 attempt 或权限扩大需要重新匹配。
5. 批准、拒绝、超时和取消有竞态测试；不能批准已经取消或已结束的调用。
6. 文件正文和模型输出都作为不可信数据，不能提升为 system 指令或默认执行授权。
7. 导出时只允许普通文件，阻断符号链接、路径穿越、特殊设备、无限文件和超额文件；宿主导出过程需防 TOCTOU。
8. HTML、脚本等成果仍是被动文件，不因为来自沙箱就自动获得客户端执行权。

### 10.4 主子 Agent 协调

- 默认串行委派，先复用现有 `agent.delegate`。并行执行必须作为单独可验收扩展。
- 每个子 Run 获得独立工作区和显式输入快照；共享成果通过版本化导出，不共享任意可写目录。
- 授权取父级权限与子级策略的交集，不自动继承父级模型供应商密钥。
- 深度、子数、并发、总时长、token 和费用预算由服务端统一扣减，多个子任务不能各自获得完整总预算。
- 不允许父任务持有独占模型租约等待子任务获取同一租约；审批等待同样不能无限占住 GPU。
- 子任务失败必须传播为可识别的失败/部分结果，而不因工具 envelope 为成功就报告整体成功。
- 已完成成果由主 Agent 汇总引用，子任务日志默认折叠；主任务结束前对未完成子任务进行明确取消或移交。
- 初版不实现任意进程暂停/检查点恢复；“恢复”指恢复状态查看或安全重试，不宣称从任意代码中间继续执行。

### 10.5 文件解析风险

PDF、图片、Office、音视频解析在 Agent 沙箱交付前也必须有独立受限 worker、输入限制和超时。该 worker 不接收任意生成代码，也不得对外宣传为安全代码沙箱。

- 使用成熟解析库，不手写 PDF/Office/媒体解码器。
- 拒绝宏执行、外部实体、远程资源自动抓取；解压类格式限制条目数、深度和展开总量。
- 解码失败、解析进程崩溃和超时只影响当前处理任务，不影响 API 和桌面进程。
- 服务端部署处理不可信文件时，解析 worker 也应置于受限容器/隔离主机，纳入上线安全门槛。

## 11. 分阶段开发任务

状态约定：`[todo]` 待开发，`[doing]` 开发中，`[verified]` 已开发且有验证证据，`[blocked]` 外部条件阻塞，`[deferred]` 经明确决定暂缓。

所有任务初始为 `[todo]`。每完成一个独立任务更新状态、证据与剩余风险；不能在里程碑结束时批量把未验证任务标为完成。

### M0：基线、合同和风险确认

目标：在写功能代码前固定兼容边界和最小实现方案。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-001 | [verified] | 阅读当前改动、相关旧计划、API/数据模型/任务与运行时；记录工作树基线 | 已核对计划、聊天 API/服务、消息模型、迁移、会话服务、桌面聊天页和当前未提交改动；本轮未回退既有改动 |
| MM-002 | [verified] | 核对真实模型、运行时、协议和可用依赖；建立初始能力矩阵 | 已在 `reports/multimodal-chat/m0-m2-foundation/verification.md` 记录 Pillow、wave、ffmpeg/ffprobe、PDF/Office/ASR/视频依赖和 Docker CLI 状态；未发起付费或外部模型调用 |
| MM-003 | [doing] | 固定 parts、attachment、turn、artifact、事件和错误合同；评估现有表复用 | 已新增 Pydantic text/file/image/audio/video parts/turn 合同、附件/turn/event/artifact 表和 API；沙箱合同仍需后续扩展 |
| MM-004 | [doing] | 确定迁移图、SQLite 路径、存储根、配额、解析器和容器 provider | 已新增 SQLite 增量迁移、Alembic `0009_multimodal_chat_foundation` 和 `0010_merge_heads`，验证迁移图单 head；容器 provider 与完整解析 worker 仍未实现 |
| MM-005 | [doing] | 跑相关基线测试并记录环境；建立需求-任务-测试映射 | 已记录 `reports/multimodal-chat/m0-m2-foundation/verification.md`；定向后端、SQLite 迁移和 PostgreSQL Alembic smoke 已通过，仍需更广回归和 GUI 实机证据 |

出口：基础协议无歧义；不需要等待所有音视频适配器选型即可继续 M1。

### M1：结构化消息与安全文件基础

依赖：M0。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-101 | [verified] | 内容块 schema、旧文本归一化、附件引用验证 | 已新增 text/file/image/audio/video parts、纯附件新 turn、非法块拒绝测试和旧 `/chat` 回归；音视频执行仍由 M3 处理器任务控制 |
| MM-102 | [verified] | Attachment/关联实体及双路径数据库迁移 | 已新增 ORM、SQLite 迁移和 Alembic revision；验证旧 SQLite `messages` 表增量升级/重复执行、Alembic 单 head、PostgreSQL 16 空库 `upgrade head` 与重复升级 |
| MM-103 | [doing] | 流式上传、临时存储、哈希、限额、取消与清理 | 已实现分块写入、临时文件发布、哈希、大小限制、只读存储对账和未引用已删附件的清理执行入口；主动取消上传和自动后台调度仍待做 |
| MM-104 | [verified] | 授权元数据、原件下载、预览访问和范围下载 | 已测跨用户元数据拒绝、预览、原件/成果 HEAD 与 Range 下载、认证图片缩略图派生物 HEAD/GET 和跨用户拒绝、删除后不可访问 |
| MM-105 | [doing] | 文本/JSON/CSV 和图片处理器、受限解析 worker；PDF 基础处理 | 已实现文本预览、图片基础尺寸元数据、DOCX/XLSX 受限 OOXML 文本预览、PDF 原件归档及 processor-unavailable 状态；独立受限 worker、PDF 提取/OCR 未完成 |
| MM-106 | [verified] | 生命周期、引用撤销和孤儿对账 | 已实现附件引用摘要、活跃 ChatTurn 引用阻止删除、软删除后禁止访问和新聊天输入、只读孤儿/缺失/过期临时文件对账，以及未引用已删附件物理清理入口；后台清理调度仍归 MM-103 后续 |

出口：文件链路能独立通过后端测试，不要求此时界面已完成。

### M2：多模态聊天基础版

依赖：M1。此阶段形成第一个面向用户的可用版本。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-201 | [doing] | 有效能力查询和无副作用 preflight | 已新增 capability/preflight，图片本地输入、音频和视频处理器缺失均明确拦截；能力返回本机处理依赖诊断，预检验证文本行范围与音视频时间范围；完整模型切换 UI 仍待做 |
| MM-202 | [doing] | 持久 ChatTurn/attempt、幂等创建、消息状态、事件重放 | 已实现持久 turn/attempt、创建后立即返回 RUNNING 快照、独立 DB session 后台执行、事件重放、同键重放不重复调度、同键不同载荷冲突，以及 `/chat/turns/{id}/retry` 校验同请求后新增 attempt 且不重复插入用户消息；启动恢复会将遗留 `CANCEL_REQUESTED` 收敛为 `CANCELLED`，将遗留 `QUEUED/RUNNING/WAITING_INPUT` 标记为 `INTERRUPTED` 并同步 attempt/event；部分状态和持久队列仍待做 |
| MM-203 | [doing] | ChatService 结构化上下文、文本投影、旧 API 兼容 | 已拆出无持久化 completion，结构化 turn 保存 parts，旧模型聊天回归通过；记忆/长上下文策略仍待补齐 |
| MM-204 | [doing] | Responses/Chat Completions 文本+图片序列化；本地能力拒绝或真实接入 | 已实现远程 Responses/Chat Completions 图片 payload 转换、本地文本运行时拒绝和 mock 合同测试；真实视觉模型路径仍待用户授权与环境验证 |
| MM-205 | [doing] | 桌面混合输入、拖拽/粘贴、多附件、上传反馈、预检和草稿保留 | 已添加附件选择、拖拽/粘贴本地文件入队、粘贴截图临时 PNG 入队、上传队列、结构化发送路径、发送前 preflight 阻断提示、按 MIME 生成 image/audio/video/file parts，以及派生物下载/删除/turn 取消/retry API 封装；持久草稿恢复仍待做 |
| MM-206 | [doing] | 消息块渲染、Markdown/代码/公式、图片/PDF/文本预览 | 已实现附件队列双击基础预览，文本预览和媒体/图片派生元数据以安全纯文本方式展示；富消息块、Markdown/代码/公式渲染和内嵌图片/PDF 预览仍待做 |
| MM-207 | [doing] | 停止/取消、新旧流兼容、快照恢复、页面销毁清理 | 已新增结构化 turn 取消端点，终态取消为幂等 no-op；RUNNING turn 可进入 CANCEL_REQUESTED，后台 worker 启动前看到取消会收尾为 CANCELLED，服务重启恢复也会结算遗留取消/运行中 turn；桌面结构化提交后按 `after_sequence` 事件水位轮询并在终态拉取快照，可对 active turn 调用取消；旧流式停止保持原语义；真实远端计算中断、SSE 长连接订阅和页面销毁深度清理仍待做 |
| MM-208 | [doing] | 基础 ArtifactService 与 TXT/MD/JSON/CSV/代码成果下载 | 已实现文本 artifact/version、会话成果列表、确切版本下载、基于 expected_version 的文本新版本创建和版本冲突；桌面聊天页可显示当前会话成果列表、查看版本摘要，并将最新版作为下一条结构化消息的附件再次引用；更多格式、显式下载位置和修改入口仍待做 |

出口演示：同条消息提交文字 + TXT/PDF + 图片，预览后发送给实际支持的模型，流式回答并生成可下载文本文件；重启后仍可查看。

### M3：音视频和复杂文档

依赖：M2；MM-301/302 的部分处理器可以在 M1 合同稳定后并行开发。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-301 | [doing] | DOCX/XLSX 解析和分页预览、PDF 页范围、可选 OCR | 已实现无额外依赖的 DOCX/XLSX 只读 OOXML 文本预览并接入 chat preflight，不执行宏/公式/外链；已新增受限内置 PDF 文本预览，可处理简单文本内容流、记录 `ocr_required`、按页号标记预览，并在 preflight 校验 PDF `pages` selection 越界；复杂 PDF 字体/编码、真实分页渲染和 OCR 仍待做 |
| MM-302 | [doing] | 音视频元数据、播放器、认证缓存、时间段选择 | 已实现 WAV 音频元数据、MP4/WebM/MOV `ffprobe` 视频元数据、audio/video 时间段 schema 和预检范围校验；视频上传会生成认证下载的 `video_frame` JPEG 派生物；播放器、认证缓存和更多编码降级仍待做 |
| MM-303 | [doing] | ASR 与视频抽帧链路；原生音视频能力按适配器开启 | 已实现 ffmpeg 单帧抽取，派生物记录 `time_ms`、尺寸和 MIME，抽帧失败不会伪装为视频理解；ASR、抽帧范围/多帧策略和原生音视频模型适配器仍待做 |
| MM-304 | [todo] | 音频输出适配器及成果，区分模型音频输出与 TTS | 至少一个真实音频生成路径，可播放和下载 |
| MM-305 | [todo] | 图片生成适配器及参数/任务/成果 | 至少一个真实图像生成路径，输出文件完整有效 |
| MM-306 | [todo] | 聊天接入现有视频作业、取消、进度、成果播放器 | 与视频页指向同一 job；至少一个真实视频产物验证 |
| MM-307 | [doing] | 多媒体转换确认、成本提示、时长/解码限制和依赖诊断 | 已记录并通过 `/chat/capabilities` 暴露本机媒体/文档依赖矩阵，在预检中对 ASR/抽帧缺失返回 `PROCESSOR_UNAVAILABLE`；用户确认、成本提示和后台处理队列仍待做 |

出口演示：上传一段音视频，定位引用后总结；生成并预览图片、音频、视频。各生成能力逐项发布，不因某个适配器未就绪而阻断已完成模态。

### M4：上下文、分支和成果工作流

依赖：M2；媒体版本功能依赖 M3 对应模态。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-401 | [doing] | ContextInspector、输入 manifest、范围选择和 token/媒体预算 | 已在 preflight 返回 `context_estimate`，统计文本字符、估算提交字符、附件数和已选范围；桌面结构化提交前显示“本轮上下文”摘要；真实 token 估算、媒体费用和完整 ContextInspector 面板仍待做 |
| MM-402 | [doing] | 长历史压缩、来源依赖、排除消息/附件和记忆开关 | 已实现结构化 turn 历史窗口的 `excluded_message_ids` 与 `excluded_attachment_ids` 过滤；排除附件会排除引用该附件的消息及同 turn 助手结果，当前消息若显式引用已排除附件会被 preflight 阻断；结构化 turn 仅在 `use_memory=true` 时注入/提取记忆。长历史摘要、摘要失效和 UI 排除操作仍待做 |
| MM-403 | [doing] | 编辑分支、重新生成 attempt、历史搜索和固定消息 | 已新增消息搜索 API、固定/取消固定 API、SQLite/Alembic 消息固定字段迁移，以及桌面当前会话搜索/固定消息入口；搜索和固定均限定在会话/用户边界内。编辑分支 UI、分支上下文和更完整重新生成语义仍待做 |
| MM-404 | [doing] | 成果区、不可变版本、再次引用、并发版本检查 | 已实现文本 artifact 新版本 API、旧版本不可变下载、parent_version 和 expected_version 冲突检查；桌面聊天页已有会话成果列表、版本摘要和最新版再次引用；更完整来源追踪、版本对比和编辑入口仍待做 |
| MM-405 | [doing] | 对话导出、清理入口、存储用量和隐私说明 | 已新增会话 JSON 导出、会话存储用量摘要、已删除未引用附件清理入口和隐私标记；导出不包含原始附件字节、内部 storage_key 或凭据。桌面导出文件保存、用户可读隐私说明和更完整清理 UX 仍待做 |

出口演示：基于附件生成文件，再引用该版本修改，比较两个版本；从旧消息分叉，排除某个附件后确认不再发送该内容。

### M5：受控沙箱执行

依赖：M1 安全存储、M2 轮次及成果、M0 安全方案；可在 M3/M4 之外独立推进，但不可跳过安全门槛。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-501 | [doing] | Sandbox provider 接口、可用性诊断、受控镜像和平台探测 | 已新增 `/api/v1/sandbox/status` 与默认关闭的 `/api/v1/sandbox/execute-python`；provider 诊断 Docker CLI/daemon/rootless/security options、配置镜像、本地镜像是否存在，并保持 `host_fallback=false`。执行只在 `MODELFORGE_SANDBOX_EXECUTION=1` 且镜像已本地存在时开启，不自动 pull 镜像 |
| MM-502 | [doing] | 独立工作区、只读输入、网络/进程/CPU/内存/磁盘限制 | Docker 执行命令已使用独立临时 workspace、`--network none`、CPU/内存/PID 限制、只读根文件系统和受限 `/tmp`，并只收集普通输出文件预览；仍缺真实容器逃逸、磁盘超额、跨平台和长运行进程树验证 |
| MM-503 | [doing] | sandbox.execute 工具接入既有 Policy/审批 | 已注册 `sandbox.execute` 工具和 legacy alias `sandbox_execute`，工具权限为 `EXECUTE`，默认 Policy 拒绝；显式允许执行权限后仍可通过 `require_approval_for` 标记需要人工审批。审批事件、代码哈希绑定和文件授权清单仍待接入 |
| MM-504 | [todo] | 日志、取消、超时、进程树清理、重启对账 | 死循环/进程派生可回收，无持续宿主负载 |
| MM-505 | [todo] | 输出收集、普通文件验证、成果导入、临时环境回收 | 符号链接/特殊文件/超额输出不能导出，成果不随环境消失 |
| MM-506 | [todo] | 安全回归和平台支持矩阵 | 真实容器测试有证据，mock 通过不能代替隔离验证 |

出口演示：用户授权读取 CSV，在无网沙箱运行代码生成统计文件，预览下载；超时、拒绝授权和读取未授权文件均被正确处理。

### M6：聊天中的主子 Agent

依赖：M2、M5；上下文细粒度控制复用 M4。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-601 | [doing] | 对话/Agent 模式、ChatTurn 与既有 Run 绑定 | 桌面聊天页已新增对话/Agent 模式选择；Agent 模式即使 text-only 也走结构化 turn/preflight，后端在沙箱执行未实现前明确返回 `SANDBOX_UNAVAILABLE`，普通聊天仍不启动工具；ChatTurn 与既有 Run 绑定仍待做 |
| MM-602 | [todo] | 委派时传递附件能力清单、独立 workspace、成果引用 | 子 Agent 无法访问未授权附件或其他子任务可写区 |
| MM-603 | [todo] | RunInspector 主子树、工具摘要、审批和日志 | 和任务中心使用同一执行状态，子任务失败不显示整体成功 |
| MM-604 | [todo] | 剩余预算传播、资源租约交接、取消级联和审批竞态 | 父等子不死锁，子任务总预算不超额，取消不遗留执行 |
| MM-605 | [todo] | 成果回传、主 Agent 汇总、恢复查看和显式重试 | 结果可追溯、重试不重复外部副作用、重启不假完成 |
| MM-606 | [todo] | 可选有界并行委派 | 仅在串行闭环通过后开启，原子预算和并发隔离测试通过 |

出口演示：主 Agent 将文档提取和表格计算交给两个子任务，用户查看具体任务与沙箱日志，取消其中一个后主任务正确给出部分结果和实际成果。

### M7：加固、兼容和发布

依赖：已计划发布的全部前置功能；部分模态阻塞时发布范围必须明确缩减，不能伪称全量完成。

| ID | 状态 | 任务与交付物 | 验收 |
|---|---|---|---|
| MM-701 | [todo] | 全量后端/桌面回归、双数据库升级、旧客户端合同 | 无新增严重回归，跳过项有原因 |
| MM-702 | [todo] | 性能、断网、服务重启、磁盘满、配额和并发故障注入 | 状态一致，无重复执行和静默数据损坏 |
| MM-703 | [todo] | 中英日、浅深色、最小窗口、高 DPI、键盘和原生截图验收 | 不遮挡、不乱码、焦点可达，真实播放器验证 |
| MM-704 | [todo] | macOS/Windows/Linux 打包、Qt 插件/媒体依赖、许可证与依赖检查 | 在声明支持的平台运行，未测平台不标通过 |
| MM-705 | [todo] | 功能开关、灰度、诊断、迁移/恢复指南、路由统计与发布说明 | 关闭新入口不丢数据，安全拒绝不被开关绕过 |
| MM-706 | [todo] | 最终需求覆盖表和真实演示证据 | 每项声明均对应测试/文件/截图，剩余限制公开 |

## 12. 测试策略与验收清单

### 12.1 现有回归范围

优先复用并扩展以下现有测试，而不是仅新增一套与旧行为无关的测试：

- 聊天：`test_chat_cursor.py`、`test_chat_history_window.py`、`test_chat_leakage.py`、`test_chat_model_registry.py`。
- 远程协议：`test_openai_compatible_provider.py`、`test_remote_provider_protocol.py`、`test_remote_provider_selection.py`、`test_provider_network_policy.py`。
- 运行时：`test_model_runtime_api.py`、`test_model_runtime_manager.py`、`test_multi_model_runtime.py`、`test_local_runtime_offload.py`。
- Agent/权限：`test_agent_runs_phase2.py`、`test_agent_events_phase3.py`、`test_multi_agent_guards_phase5.py`、`test_agent_file_access.py`、`test_policy_phase6.py`。
- 任务：`test_task_sse_outbox.py`、`test_task_store_stream.py`、`test_task_center_cancel.py`、`test_task_retry_execution.py`。
- 桌面：`test_desktop_model_runtime_pages.py`、`test_desktop_resilience.py`、`test_desktop_shutdown.py`、`test_desktop_process_exit.py`、`test_i18n_runtime.py`。
- 其他：`test_video_api.py`、`test_migration_preflight.py`、`test_core_contracts.py`。

### 12.2 拟新增测试模块

| 建议模块 | 核心覆盖 |
|---|---|
| test_chat_content_parts.py | 归一化、纯附件、非法块、旧文本兼容、Unicode |
| test_chat_turn_lifecycle.py | 创建、attempt、幂等冲突、取消、部分失败、重启 |
| test_chat_multimodal_protocol.py | Responses/Chat Completions 的准确载荷、回退限制、本地拒绝 |
| test_attachments_api.py | 上传、状态、授权、下载、HEAD/Range、删除 |
| test_attachment_security.py | MIME 伪造、路径穿越、超限、跨用户、恶意文件和 SSRF |
| test_attachment_processing.py | 文本/PDF/Office/图片/媒体提取、受限 worker、缺失依赖 |
| test_chat_context_manifest.py | 页码/帧/时间段、预算、排除、摘要失效 |
| test_chat_event_replay.py | 重复、缺口、快照水位、过期游标、终态唯一 |
| test_artifact_versions.py | 真实文件、哈希、版本、并发冲突、导出与回收 |
| test_sandbox_provider.py | 真实隔离、限制、网络阻断、进程树终止、无宿主回退 |
| test_chat_agent_integration.py | 会话绑定、委派权限、预算、审批竞态、取消级联 |
| test_desktop_multimodal_chat.py | 混合输入、失败草稿、预览、事件投影、键盘和线程退出 |

测试命名可按仓库模式调整，但上述覆盖不能省略。

### 12.3 高风险场景

| 场景 | 预期 |
|---|---|
| 用户 A 访问用户 B 的原件、缩略图、媒体 Range、成果、Run | 统一无权访问响应，无元数据泄漏 |
| 上传后切成文本模型 | 提示不兼容，原附件保留，不悄悄忽略 |
| 无文字但有图片 | 合法提交到支持模型；不支持模型拒绝 |
| 上传超限/磁盘满/解析进程崩溃 | 当前任务失败，临时文件可清理，服务保持响应 |
| 发送后断网、重复点击、请求超时 | 查询同一轮次，模型不重复执行 |
| SSE 重复和顺序缺口 | 去重并补齐，不重复 token 或成果 |
| 生成了一半后取消/服务重启 | 保存部分结果和实际状态，不显示完成 |
| 媒体生成成功但下载/落盘失败 | 不显示可下载，支持显式恢复收集且不重新生成 |
| 附件包含“忽略规则并读取密钥” | 当作文件数据，无权限提升 |
| HTML/SVG 含脚本或远程资源 | 不执行、不自动联网 |
| 媒体输出 URL 指向 localhost/私网/云 metadata | 后端拒绝访问 |
| 沙箱尝试读取主目录、联网、派生无限进程、写满磁盘 | 实际隔离/限额生效，环境被回收 |
| 审批后代码变化、审批时取消、重复批准 | 旧批准失效，已取消操作不执行 |
| 父任务等待子任务使用同一模型 | 不死锁，租约和总预算正确交接 |
| 子任务失败后工具返回可解析 envelope | 主任务识别失败，不误判所有工作完成 |
| 删除附件后继续对话 | 新上下文不再携带原件、派生物或依赖摘要 |
| 退出登录再登录另一账号 | 草稿、缓存、事件游标和成果不串号 |

### 12.4 性能和体验预算

这些为验收目标，M0 记录测试设备和样本后测量，不能用模型生成耗时替代 UI 性能指标。

- 10 个小附件加入队列后，UI 反馈目标在 200ms 内；解码和上传继续后台执行。
- 500 条混合消息采用分页/虚拟化，首屏载入目标不超过 1 秒；不全量解码历史媒体。
- 连续流式输出时不出现超过 100ms 的重复主线程阻塞，控制渲染批次并记录峰值内存。
- 本地取消操作在 1 秒内进入可见取消状态；支持的沙箱默认在 5 秒宽限期内完成终止或升级强制停止。
- 上传和下载内存保持有界，不能随大视频文件大小线性增长到完整文件缓冲。
- 断线后通过游标/快照恢复，重连不触发新的模型请求。
- UI 性能自动测试可用较宽阈值避免 CI 抖动，原生实测报告保留真实值。

### 12.5 测试执行规则

使用隔离测试数据库、临时 data_dir 和固定小样本，不在用户真实会话库执行迁移测试。按已有 pytest 标记区分 desktop、network、real_model、gpu；容器测试可新增并登记 sandbox 标记。

POSIX 环境示例，先确认解释器环境，不强制删除或重建用户已有虚拟环境：

```bash
python -m pytest tests/test_chat_history_window.py tests/test_chat_leakage.py tests/test_chat_model_registry.py -q
python -m pytest tests/ -q -m "not desktop and not network and not real_model and not gpu"
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q -m desktop
python -m ruff check backend/app client/pyside6 tests
python scripts/api_route_stats.py --check
```

- 新增模块后运行对应精确测试；上面的命令是实施时建议，不代表本文编制时已执行。
- 桌面 offscreen 通过不能替代真实窗口、音视频播放、原生退出和打包测试。
- 使用 Qt 测试和原生截图，不为桌面项目强行引入浏览器测试框架。
- mock 用于协议、错误和确定性测试；每种对外宣称可用的模态另做真实样本验证。
- 测试需要下载模型、访问外网、付费或安装容器环境时先遵守授权要求；缺条件记为 blocked，不改成假实现。

## 13. 发布、功能开关和回滚

### 13.1 建议能力开关

开关由后端配置并投影到客户端；确切配置名在 M0 对齐现有 config 结构：

- multimodal_chat：新轮次、结构化消息和附件聊天。
- document_processing：PDF/Office/OCR 等解析能力，按处理器细分。
- media_input：音视频输入，按具体 adapter readiness 启用。
- media_generation：图片/音频/视频生成分别控制。
- sandbox_execution：真实环境可用且安全门槛通过才开放。
- chat_agent_delegation：聊天内委派；并行委派另设限额与开关。

禁用功能只阻止新操作，历史内容仍可安全查看/下载。关闭 UI 开关不能作为唯一权限检查。

### 13.2 版本顺序

1. 内部版 A：M0-M2，文件/图片输入、结构化回复、文本成果、可恢复轮次。
2. 内部版 B：M3-M4，文档及音视频处理、实际媒体生成、上下文和成果版本。
3. 内部版 C：M5-M6，审批、隔离执行和主子 Agent 闭环。
4. 发布候选：M7，完成安全、兼容、打包和真实验证后按明确支持矩阵发布。

MVP 不等于完整交付。用户最初要求的音视频和沙箱仍需后续阶段完成，不能在 A 版关闭整个计划。

### 13.3 回滚与运维

- 升级前备份数据库及受管文件索引，验证恢复流程，不只检查备份文件存在。
- 新功能故障时关闭新提交入口，保留原有文本聊天与历史预览。
- 数据库已升级后优先采用前向修复；二进制回滚前检查旧代码能否忽略新增列与状态。
- 对长期任务和远端作业先结算或取消，不能直接停进程后遗留未知计费任务。
- 指标覆盖上传失败、处理耗时、预检拒绝、首 token、断线恢复、队列等待、沙箱终止、存储配额和孤儿清理。
- 日志默认不记录原始附件、全文提示、Base64、密钥、JWT、含凭据 URL 和敏感宿主路径。
- 发布说明列出支持格式、模型/工具、依赖、平台、限制和未验证项。

## 14. Codex 执行规约

### 14.1 每个任务的工作方式

1. 先读对应模块和相关测试，检查 `git status --short`，识别已有改动。
2. 更新当前任务为 `[doing]`，说明计划修改的文件和验证方法。
3. 以最小完整功能切片实施：合同/服务/持久化/API/客户端/测试按风险需要配套推进。
4. 使用现有架构和公共组件；不因为方便而新建平行任务系统或放宽安全策略。
5. 先跑定向测试，再跑受影响回归；共用数据模型、权限、协议变更必须扩大测试范围。
6. 有真实证据后标为 `[verified]`，记录命令、结果、环境、截图/样本位置和残余限制。
7. 条件不足时标记 `[blocked]` 并继续不依赖该条件的任务；不得填充假成功、样例媒体或 mock 执行冒充交付。
8. 阶段结束提交摘要：已完成、验证结果、未完成、风险、下一阶段入口。除非用户授权，不自动 commit/push/release。

### 14.2 不允许的“完成”方式

- 只做上传按钮但文件未送到模型。
- 只显示文件名、缩略图或转写，未声明原生/转换区别。
- 仅写入数据库记录但没有实际可下载文件。
- 用固定图片/视频或测试样本冒充模型输出。
- 仅取消客户端线程而声称所有后台和远端工作已停止。
- 用 `subprocess` + cwd 冒充沙箱，或缺容器时自动在宿主运行。
- 仅 mock 通过就标记真实模型、播放器或隔离能力已验证。
- 新增 Message 字段但未迁移旧 SQLite 数据库。
- 创建新的 Agent Runtime、审批系统和任务中心绕开现有机制。
- 全局格式化、重命名、还原无关文件，或修改既有未提交代码来缩小 diff。

### 14.3 每阶段证据目录

建议采用 `reports/multimodal-chat/<milestone>/`，包含：

- `verification.md`：命令、环境、结果、跳过原因、需求映射。
- `screenshots/`：中英日、浅深色和不同窗口的真实截图。
- `contracts/`：去敏后的协议样本和能力矩阵。
- `samples/`：小型、无敏感信息的验证输入/输出及哈希。

不提交用户附件、真实密钥、大模型权重、大视频、生产数据库或不必要的二进制日志。大型证据按仓库现有制品约定处理。

### 14.4 可直接交给 Codex 的启动指令

```text
请按 docs/plan/MODELFORGE_MULTIMODAL_CHAT_AGENT_DEVELOPMENT_PLAN_2026-09-14.md
实施 ModelForge 多模态对话和 Agent 沙箱能力。

从 M0 开始，先核对当前仓库和已有未提交改动，保留用户工作。
保持 FastAPI + PySide6，复用现有模型注册、运行时、Agent Run、Policy、
任务中心和视频生成服务，不重写成 Web 应用，不放宽宿主命令执行限制。

按任务 ID 逐项推进，第一轮优先交付 M0-M1；每个任务同步补齐必要测试，
只有有验证证据才标为 verified。之后按依赖继续 M2-M7。
不要把只做界面、mock 输出或普通子进程当作多模态或安全沙箱完成。

真实模型、付费服务、系统安装或平台环境不足时记录准确阻塞，继续无依赖任务。
不要未经授权下载大模型、安装系统服务、向外发送用户文件、提交或发布。
每阶段报告修改范围、测试命令和结果、真实验证、未完成项及下一步。
若当前执行无法覆盖整个阶段，保留准确状态和明确的下一个任务 ID，不能宣称全部完成。
```

### 14.5 并行协作边界

仅当执行环境支持且用户允许时使用子任务协作。合同和数据迁移先由一个实现者统一，随后可按以下边界拆分：

- 文件处理：AttachmentService、解析器和对应后端测试。
- 桌面交互：聊天组件、预览、i18n 和桌面测试。
- 模型适配：能力解析、多模态协议和运行时合同测试。
- 沙箱：provider、受限工具、审批扩展和安全测试。

`models/records.py`、`core/database.py`、核心 schema、`chat_service.py`、任务事件和公共语言文件需要明确单一合并负责人，避免多任务同时修改共享合同。

## 15. 总体验收定义

以下全部满足才可称为本计划完整交付；不具备条件的模态/平台需明确列入未完成项，而不是隐去：

- [ ] 既有纯文本聊天、历史、模型选择、停止、用户隔离和三语言不回归。
- [ ] 支持混合文字、文本文件、图片、音频和视频输入，按格式矩阵预览。
- [ ] 所有附件经授权和校验，模型实际收到的是用户确认的原生或转换内容。
- [ ] 能力矩阵与实际适配器一致，不支持的组合在执行前明确拒绝。
- [ ] 文字、Unicode、代码、公式、文本文件和媒体成果可正确呈现。
- [ ] 图片、音频和视频输出各有至少一个真实验证路径，产物可下载且文件有效。
- [ ] 轮次、消息、附件、成果和执行状态可持久化；重连/重试不重复副作用。
- [ ] 上下文、引用、范围、摘要和成果版本可检查、排除和追溯。
- [ ] 聊天内主子 Agent 复用既有 Run，具有明确权限、预算、状态和取消机制。
- [ ] 模型生成代码在真实受限环境执行；无环境时默认拒绝，无宿主回退。
- [ ] 安全测试覆盖跨用户访问、恶意附件、SSRF、审批竞态、资源限制和输出导出。
- [ ] SQLite 与 PostgreSQL 升级、恢复、旧协议兼容均有验证记录。
- [ ] 声明支持的平台完成真实 GUI、媒体、沙箱和打包验证；未测平台清晰标注。
- [ ] 发布范围、依赖、成本提示、隐私、删除及已知限制文档与实际行为一致。

## 16. 执行记录

| 日期 | 范围 | 状态 | 证据与说明 |
|---|---|---|---|
| 2026-09-14 | 计划编制 | 已完成文档，开发未开始 | 定向阅读当前聊天、消息存储、模型能力、远程协议、Agent 委派、文件访问、任务投影、视频和迁移机制；仅新增本文，未运行功能测试 |
| 2026-09-14 | M0-M3 基础切片 | 进行中 | 新增结构化 text/file/image/audio/video parts、附件/turn/event/artifact 数据模型、SQLite/Alembic 迁移、附件 API、结构化 chat turn API、文本 artifact、桌面附件队列与结构化发送路径；新增认证缩略图、WAV/视频元数据、音视频预检阻断、范围校验、处理依赖诊断、turn 取消合同和附件存储对账；验证见 `reports/multimodal-chat/m0-m2-foundation/verification.md`，定向后端测试 86 passed，Ruff 通过，PostgreSQL Alembic smoke 通过；真实 ASR/OCR/抽帧/播放器、媒体生成、沙箱和 Agent 委派仍未完成 |

后续实施在此补充阶段总结，并在第 11 节逐项更新任务状态。不要将“计划已编制”当作 M0 的基线测试和合同实现已完成。
