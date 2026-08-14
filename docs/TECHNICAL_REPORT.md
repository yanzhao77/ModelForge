# ModelForge 统一新版架构 —— 全面技术报告

> 目标：**统一使用新版客户端**（FastAPI 后端 + PySide6 瘦客户端），把旧版桌面应用的全部功能迁移、修复、优化到新架构，并补齐缺失功能，最终交付一个功能完整、可测试、可打包、可部署的 ModelForge 2.0。
>
> 本报告基于当前 master 分支代码实测：112 个测试中 111 通过 / 1 失败；后端仅注册根路由；旧版与新版两套代码并存。

---

## 目录

1. [背景与现状分析](#1-背景与现状分析)
2. [目标架构总览](#2-目标架构总览)
3. [技术选型](#3-技术选型)
4. [统一数据库设计](#4-统一数据库设计)
5. [后端 API 全量规划](#5-后端-api-全量规划)
6. [分模块实现方案](#6-分模块实现方案)
7. [需要修复的问题清单（Bug 级）](#7-需要修复的问题清单bug-级)
8. [需要优化的点](#8-需要优化的点)
9. [需要追加的功能清单](#9-需要追加的功能清单)
10. [客户端 UI 全量规划](#10-客户端-ui-全量规划)
11. [分阶段实施路线图](#11-分阶段实施路线图)
12. [测试策略与 CI](#12-测试策略与-ci)
13. [打包与部署](#13-打包与部署)
14. [代码清理与迁移](#14-代码清理与迁移)
15. [风险与注意事项](#15-风险与注意事项)

---

## 1. 背景与现状分析

### 1.1 现状：两代代码并存

仓库里同时存在两套互不相通的实现：

| | 旧版（遗留桌面应用） | 新版（目标架构） |
|---|---|---|
| 入口 | main.py / main_session.py | backend/app/main.py（FastAPI）+ client/pyside6/main.py |
| 主要代码 | gui/, api/, database/, models/, pytorch/, interface/ | backend/app/{api,core,services,models,plugins}, client/pyside6/ |
| 功能 | 完整：登录、会话、记忆、GGUF 下载、本地推理、接口对话、微调脚本 | 只有骨架：服务层 + 测试，**路由全部未接线** |
| 测试 | test/ 手工脚本 | tests/ pytest（112 个用例，1 失败） |

### 1.2 新版架构的实测问题（本报告修复依据）

1. **后端是空壳**：backend/app/main.py 只注册了 GET / 。backend/app/api/ 下的 4 个 router（runtime/agent/knowledge/plugin）从未 include_router，set_runtime() 等注入钩子从未被调用；**/models 路由完全不存在**，但客户端 client.py 却调用 /models、/models/scan、/models/install、/models/{id}。
2. **依赖缺失**：requirements.txt 缺 sqlalchemy、python-dotenv、PyYAML、langgraph、langchain-core（agent_engine.py 顶层 import langgraph），CI 装完依赖后 pytest 必然收集失败。
3. **测试失败**：tests/test_phase4_providers.py::TestHFProvider::test_download 硬编码 /test/cache，在 macOS 上报 Read-only file system，在 CI 非 root 用户下同样失败。
4. **AgentEngine 是假 LangGraph**：顶层 import 了 StateGraph/ToolNode 等但从未使用，实际是普通内存消息循环；死 import 还导致依赖装不上。
5. **客户端页面空目录**：client/pyside6/{pages,components,resources} 只有空 __init__.py。

### 1.3 旧版功能清单（必须全部迁移到新架构）

| 模块 | 旧版实现文件 | 功能点 |
|---|---|---|
| 用户 | gui/login_dialog.py, api/auth_service.py | 注册、登录、JWT（HS256）、PBKDF2 密码哈希、邮箱、用户数据隔离 |
| 会话 | gui/session_sidebar.py, api/session_service.py, models/database_models.py | 创建/软删除/切换/重命名/清空会话、消息 CRUD、自动标题（首条用户消息前 30 字）、消息计数 |
| 记忆 | api/memory_service.py | 关键词规则提取（偏好/事实）、重要性评分、访问计数、LIKE 搜索、上下文格式化注入、旧记忆清理 |
| 模型下载 | gui/dialog/gguf_download_dialog.py | HF 搜索、作者筛选、量化类型识别、单文件下载、hf-mirror 镜像 |
| 本地推理 | pytorch/model_generate.py, pytorch/session_model_generate.py | transformers 加载、GGUF（llama-cpp-python）加载、生成参数（温度/top_k/beams）、深度思考模式、快速模式、OOM 降级、资源释放、性能监控装饰器 |
| 在线搜索 | pytorch/webSearcher.py | duckduckgo 搜索、关键词触发、LRU 缓存 |
| 接口对话 | pytorch/interface_generate.py, gui/menu/interface_menu.py | OpenAI 兼容接口（含讯飞星火）、参数透传 |
| OpenAI 兼容服务 | interface/api_interface_fastapi.py | /v1/chat/completions、Bearer 鉴权、开关 |
| 微调 | pytorch/trainer_model.py, pytorch/loRA_model.py | 全参微调（Trainer）、LoRA 微调（peft） |
| 树形界面 | gui/tree_view/, gui/menu/ | 模型树、菜单栏 |

---

## 2. 目标架构总览

### 2.1 架构图

```
                 ┌─────────────────────────────────────┐
                 │        PySide6 桌面客户端 (瘦客户端)     │
                 │  client/pyside6/                       │
                 │  登录 / 会话 / 聊天 / 模型 / 下载 /       │
                 │  Agent / 知识库 / 训练 / 设置            │
                 └──────────────┬──────────────────────┘
                                │ REST (httpx) + SSE 流式
                 ┌──────────────▼──────────────────────┐
                 │       FastAPI 后端 (backend/app)      │
                 │  auth │ models │ runtime │ chat │     │
                 │  sessions │ memories │ agent │        │
                 │  knowledge │ plugins │ train │ api    │
                 └───┬──────────┬──────────┬────────────┘
                     │          │          │
          ┌──────────▼──┐  ┌────▼─────┐  ┌─▼──────────────┐
          │ SQLite/     │  │ 推理运行时 │  │ 外部服务         │
          │ SQLAlchemy  │  │ 本地 HF   │  │ Ollama / HF Hub │
          │ + Alembic   │  │ GGUF     │  │ ModelScope /    │
          │ + 向量存储   │  │ Ollama   │  │ OpenAI 兼容 API  │
          └─────────────┘  │ API 接口 │  └─────────────────┘
                          └──────────┘
```

### 2.2 目录结构规划（最终形态）

```
ModelForge
├── main.py                    # 新版客户端入口（替换旧 main.py / main_session.py）
├── backend/
│   └── app/
│       ├── main.py            # FastAPI 应用：include_router + lifespan 注入
│       ├── api/               # 路由层：auth, models, runtime, chat, sessions,
│       │                      #        memories, agent, knowledge, plugins, train, system, openai
│       ├── core/              # config, database, security, logging, deps(依赖注入)
│       ├── models/            # SQLAlchemy 模型（统一 schema）
│       ├── services/          # 业务层：model_manager, providers, runtimes,
│       │                      #        agent_engine, knowledge_base, memory, session,
│       │                      #        auth, training, downloader, searcher, plugin_manager
│       ├── schemas/           # Pydantic v2 请求/响应模型
│       └── plugins/           # SPI 插件包（示例插件）
├── client/
│   └── pyside6/
│       ├── main.py            # 窗口入口（启动即检查后端连通性）
│       ├── api_client/client.py   # REST+SSE 客户端（补齐全部接口）
│       ├── pages/             # HomePage, LoginPage, ChatPage, SessionSidebar,
│       │                      # ModelCenterPage, DownloadPage, AgentPage,
│       │                      # KnowledgePage, TrainingPage, SettingsPage
│       ├── components/        # 消息气泡、Markdown 渲染、流式打字机
│       └── resources/         # QSS 主题、图标
├── migrations/                # Alembic 迁移脚本
├── tests/                     # pytest（单元 + API 集成 + 客户端 mock）
├── requirements.txt           # 后端最小依赖（CI 可用）
├── requirements-dev.txt       # 开发/测试依赖
├── requirements-gui.txt       # 桌面客户端依赖（PySide6）
├── requirements-ai.txt        # 重型可选：torch/transformers/llama-cpp/peft
├── config.yaml / .env.example
├── Dockerfile                 # 多阶段构建（后端镜像）
└── legacy/                    # 旧版代码归档（迁移完成后移入，不再参与构建）
```

### 2.3 设计原则

1. **后端承载全部业务逻辑**，客户端零业务逻辑，只做展示与交互（当前 client.py 已是这个方向，但接口不全）。
2. **一切多用户数据必须按 user_id 隔离**（旧版已做，新版 records.py 没做，需补）。
3. **推理、下载、训练全部异步化**：后台任务 + 任务状态轮询或 SSE 推送。
4. **流式输出**：聊天一律走 SSE，客户端打字机渲染（旧版是整段返回，体验差）。
5. **配置驱动**：所有可调参数（模型路径、Ollama 地址、HF 镜像、密钥）进 config.yaml / 环境变量。

---

## 3. 技术选型

| 领域 | 选型 | 说明 |
|---|---|---|
| 后端框架 | FastAPI 0.115+ / Uvicorn | 已有，保持 |
| 数据校验 | Pydantic v2 | 已有 |
| ORM | SQLAlchemy 2.x + Alembic | 迁移管理必加（当前无迁移） |
| 认证 | PyJWT 2.x + passlib(bcrypt) 或原生 PBKDF2 | 旧版 PBKDF2-HMAC-SHA256 可复用；SECRET_KEY 改为从配置持久化读取 |
| 配置文件 | pydantic-settings + PyYAML + python-dotenv | 统一 core/config.py（当前缺 dotenv 依赖） |
| HTTP 客户端 | httpx | 已有 |
| 流式 | sse-starlette（或原生 StreamingResponse） | SSE 推送聊天/任务进度 |
| Agent | langgraph + langchain-core | 改为真正实现（当前是假的） |
| 本地推理 | transformers + llama-cpp-python（可选，进 requirements-ai.txt） | 端口旧 model_generate.py 逻辑 |
| 在线搜索 | duckduckgo_search | 已有 |
| 向量检索 | numpy（默认）→ faiss-cpu（可选） | RAG/记忆 |
| 嵌入 | 可选 sentence-transformers（默认 TF-IDF 词袋可先用） | |
| 微调 | transformers Trainer + peft（LoRA） | 后台任务 |
| 客户端 | PySide6 6.x + QSS | 已有；Markdown 渲染用 QTextBrowser/Qt 自带或 markdown 库 |
| 测试 | pytest + pytest-asyncio + httpx(TestClient) | 已有 |
| 部署 | Docker（多阶段）、PyInstaller | |

> **依赖拆分原则**：requirements.txt 只放后端轻量必需（fastapi/uvicorn/sqlalchemy/pydantic/httpx/jwt/dotenv/yaml/langgraph...），CI 秒级安装；requirements-ai.txt 放 torch/transformers/llama-cpp/peft/datasets（桌面用户按需安装）；requirements-gui.txt 放 PySide6。彻底解决当前"CI 装 torch 2.5GB"的问题。

---

## 4. 统一数据库设计

合并旧版 models/database_models.py 与新版 models/records.py，统一到 backend/app/models/，全部表带 user 隔离。

| 表 | 关键字段 | 来源 | 说明 |
|---|---|---|---|
| users | id, username(unique), email, password_hash, is_active, created_at, last_login | 旧版 | |
| sessions | id, user_id FK, title, model_id FK(nullable), is_active(软删), created_at, updated_at | 旧版+新版 | 关联所选模型 |
| messages | id, session_id FK, role, content, token_count, timestamp, meta(JSON) | 旧版 | meta 存推理参数快照 |
| memories | id, user_id FK, memory_type(preference/fact/...), key, value, source_session_id, importance, embedding(BLOB, 可选), created_at, last_accessed, access_count | 旧版 | 升级：可存向量 |
| models | id, name(index), provider, path, size, status, format(gguf/safetensors), quant, config(JSON), user_id, created_time | 新版 ModelRecord | 扩展字段 |
| agents | id, name(unique), user_id, model, tools(JSON), memory_config(JSON), system_prompt, created_at | 新版 AgentRecord | |
| knowledge_documents | id, user_id, filename, filetype, chunk_count, doc_meta(JSON), created_at | 新增 | RAG 文档索引 |
| knowledge_chunks | id, doc_id FK, chunk_index, content, embedding(BLOB), metadata(JSON) | 新增 | 向量块 |
| api_keys | id, user_id, name, key_hash, created_at, last_used | 新增 | OpenAI 兼容接口鉴权 |
| download_tasks | id, user_id, repo_id, filename, status, progress, target_path, error, created_at | 新增 | GGUF/模型下载任务 |
| train_tasks | id, user_id, base_model, method(full/lora), config(JSON), status, log_path, created_at | 新增 | 微调任务 |

**实施**：
- 用 SQLAlchemy 2.x 声明式模型重写（Mapped/mapped_column），保留旧版字段名兼容数据。
- 引入 Alembic：alembic init migrations，基线从 0 建表；后续演进只加迁移。
- 数据库路径沿用 config.yaml 的 database_path；索引：sessions(user_id, updated_at)、messages(session_id, timestamp)、memories(user_id, importance)。

---

## 5. 后端 API 全量规划

统一前缀 /api/v1（除 OpenAI 兼容端点）。鉴权：除 /auth/register|login 外全部要求 Authorization: Bearer <jwt>。

| 模块 | 方法与路径 | 功能 | 当前状态 |
|---|---|---|---|
| auth | POST /api/v1/auth/register | 注册 | ❌ 缺失（服务在 legacy/api） |
| auth | POST /api/v1/auth/login | 登录返回 JWT | ❌ |
| auth | GET /api/v1/auth/me | 当前用户 | ❌ |
| auth | POST /api/v1/auth/change-password | 改密码 | ❌ |
| models | GET /api/v1/models | 模型列表 | ❌ 路由缺失（ModelManager 已有） |
| models | POST /api/v1/models/scan | 扫描目录 | ❌ |
| models | POST /api/v1/models/install | 登记模型 | ❌ |
| models | DELETE /api/v1/models/{id} | 删除记录 | ❌ |
| models | POST /api/v1/models/{id}/config | 保存用户模型参数 | ❌ |
| models | GET /api/v1/models/search?q=&author= | HF 搜索 | ❌（HFProvider 已有） |
| models | POST /api/v1/models/download | 后台下载（GGUF/全量） | ❌ |
| models | GET /api/v1/models/download/{task_id} | 下载进度 | ❌ |
| runtime | POST /api/v1/runtime/load | 加载模型到运行时 | ❌ 未接线 |
| runtime | POST /api/v1/runtime/chat | 普通聊天（非流式） | ❌ |
| runtime | GET /api/v1/runtime/chat/stream | **SSE 流式聊天** | ❌ 新增 |
| runtime | POST /api/v1/runtime/stop | 卸载 | ❌ |
| runtime | GET /api/v1/runtime/status | 当前已加载模型 | ❌ |
| sessions | GET/POST /api/v1/sessions | 列表/创建 | ❌（SessionService 在 legacy） |
| sessions | GET/PATCH/DELETE /api/v1/sessions/{id} | 详情/重命名/软删 | ❌ |
| sessions | GET/POST /api/v1/sessions/{id}/messages | 消息列表（分页）/追加 | ❌ |
| sessions | DELETE /api/v1/sessions/{id}/messages | 清空 | ❌ |
| sessions | POST /api/v1/sessions/{id}/title | 自动生成标题 | ❌ |
| memories | GET/POST/DELETE /api/v1/memories | 列表/手动添加/删除 | ❌（MemoryService 在 legacy） |
| memories | GET /api/v1/memories/search?q= | 语义/关键词搜索 | ❌ |
| memories | PATCH /api/v1/memories/{id} | 改重要性 | ❌ |
| agent | GET/POST /api/v1/agents | 列表/创建 | ❌ 未接线 |
| agent | POST /api/v1/agents/{name}/chat | Agent 对话（SSE） | ❌ |
| agent | DELETE /api/v1/agents/{name} | 删除 | ❌ |
| knowledge | POST /api/v1/knowledge/upload | 上传文档 | ❌ 未接线 |
| knowledge | POST /api/v1/knowledge/query | 检索问答 | ❌ |
| knowledge | GET /api/v1/knowledge/stats | 统计 | ❌ |
| knowledge | GET/DELETE /api/v1/knowledge/documents | 文档管理 | ❌ 新增 |
| plugins | GET /api/v1/plugins | 列表 | ❌ 未接线 |
| plugins | POST /api/v1/plugins/{name}/install | 安装 | ❌ |
| train | POST /api/v1/train/start | 启动微调任务（full/lora） | ❌ 新增 |
| train | GET /api/v1/train/status/{task_id} | 进度（含日志尾） | ❌ |
| train | POST /api/v1/train/stop/{task_id} | 停止 | ❌ |
| openai | POST /v1/chat/completions | OpenAI 兼容 | ❌（legacy/interface 有，需重写） |
| system | GET /api/v1/system/status | CPU/GPU/内存/磁盘/运行时长 | ❌ 新增 |
| system | GET /api/v1/system/logs?tail=N | 日志查看 | ❌ 新增 |

**接线方式（修复核心）**：backend/app/main.py 用 lifespan 初始化并注入单例，然后 include_router 全部路由：

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import init_db
from core.config import settings
from services import runtime_registry, agent_engine, knowledge_base, plugin_manager
from api import (auth, models, runtime, chat, sessions, memories,
                 agent, knowledge, plugins, train, system, openai_api)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    runtime.set_runtime(runtime_registry.get_runtime())
    agent.set_agent_engine(agent_engine.get_engine())
    knowledge.set_knowledge_base(knowledge_base.get_kb())
    plugin.set_plugin_manager(plugin_manager.get_manager())
    yield

app = FastAPI(title="ModelForge", version="2.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (auth.router, models.router, runtime.router, chat.router,
          sessions.router, memories.router, agent.router, knowledge.router,
          plugins.router, train.router, system.router, openai_api.router):
    app.include_router(r)
```

---

## 6. 分模块实现方案

> 每个模块按「现状 → 改动 → 修复 → 优化 → 新增」组织，标注实现方式与技术。

### M1 基础设施（配置 / 依赖 / 日志 / 启动）

- **改动**：
  - core/config.py：改为 pydantic-settings + 环境变量 + yaml 三层覆盖（保留现有 load_config 逻辑），新增字段：jwt_secret、jwt_expire_minutes、ollama_base_url、hf_endpoint、model_dir、data_dir、max_upload_size、enable_streaming。
  - requirements.txt 拆分为 base/dev/gui/ai 四份（见第 3 节）。
  - 新增 .env.example 与 config.example.yaml。
- **修复**：补 python-dotenv、PyYAML、sqlalchemy 依赖；修复 dotenv import。
- **优化**：core/logging_config.py 加 RotatingFileHandler（当前单文件无限增长）、统一 JSON 结构化日志可选。
- **新增**：启动时健康检查脚本 scripts/healthcheck.py；/api/v1/system/status 用 psutil 采集系统指标。

### M2 认证与用户管理

- **现状**：旧版 api/auth_service.py 完整可用（PBKDF2 + JWT），新版无认证。
- **改动**：把 AuthService 移植为 services/auth.py，增加 SQLAlchemy 2.x 风格、Pydantic 校验（schemas/auth.py：RegisterRequest/LoginRequest/TokenResponse）。
- **修复**：SECRET_KEY 改为 settings.jwt_secret（当前每次进程随机 → 重启后 token 全失效）；密码最小长度校验（旧版 6 位）后端强制；用户名长度 3-32。
- **优化**：登录失败统一延迟（防爆破）、登录失败次数限流（可选 slowapi）；datetime.utcnow 全部替换为 datetime.now(timezone.utc)。
- **新增**：GET /auth/me、改密码、可选 refresh token（短期 access + 长期 refresh）。

### M3 会话与消息

- **现状**：旧版 api/session_service.py 完整；新版无。
- **改动**：移植为 services/session.py + api/sessions.py，路由按第 5 节实现；消息支持分页（?page=&page_size=）。
- **修复**：auto_generate_title 只取首条用户消息（旧版有边界 bug：若首条是 assistant 返回 False）；软删后创建新会话逻辑客户端处理。
- **优化**：消息列表游标分页 + 惰性加载（旧版一次性全量）；sessions 列表只返回元信息（标题/时间/消息数），不拉消息。
- **新增**：会话导出（Markdown/JSON）、消息 token 统计、会话固定（pin）。

### M4 记忆系统

- **现状**：旧版 api/memory_service.py 关键词规则提取（preference/fact）+ LIKE 搜索 + 重要性 + 访问统计；新版 services/memory.py 是纯内存向量（TF-IDF）版。
- **改动**：合并两者——数据库持久化 + 可选向量列。提取仍用规则（中文关键词），**改进**：把提取逻辑做成可插拔（规则提取器 + 可选 LLM 提取器）。
- **修复**：LongTermMemory.remember 每次插入全量重嵌 O(n)（改为增量：新文本单独 fit/embed，或统一在写入时用 SimpleEmbedder 增量词表）。
- **优化**：搜索先用 SQL LIKE 粗筛，再（可选）向量重排；访问热记忆 LRU 缓存；cleanup_old_memories 改为定期后台任务。
- **新增**：记忆管理 UI（查看/编辑/删除/手动添加）、记忆开关（会话级/全局）、注入模板可配置。

### M5 模型管理

- **现状**：新版 services/model_manager.py 完整（scan/list/install/remove/info + 文件类型识别 + 目录识别 + 大小格式化），但无路由。
- **改动**：新增 api/models.py 路由（scan/install/remove/info/list）+ schemas/models.py；scan 支持指定路径与全量。
- **修复**：scan 后列表按 created_time 倒序已在实现，但 ModelRecord 表缺 user_id 隔离 → 补列（迁移）；name 唯一索引与多用户冲突 → 唯一约束改为 (user_id, name)。
- **优化**：scan 放后台任务（大目录会阻塞）；目录大小统计用 os.scandir 迭代而非 rglob 一次性汇总（大模型目录很慢）。
- **新增**：模型参数配置持久化（ModelConfig 表，旧版有模型，移植）、模型删除可选删文件、模型格式/量化识别。

### M6 模型下载（GGUF / HF / ModelScope）

- **现状**：旧版 gguf_download_dialog.py（HF 搜索 + 作者筛选 + 量化识别 + hf-mirror + 单文件下载）；新版 HFProvider/ModelScopeProvider 已有接口。
- **改动**：把下载逻辑移到后端 services/downloader.py：
  - search_models(query, author) → 复用 HFProvider.list_models + 过滤 GGUF 文件（siblings 判断，端口旧逻辑）。
  - start_download(repo_id, filename, provider) → 用 BackgroundTasks/asyncio.create_task 跑 snapshot_download，进度写入 download_tasks 表；客户端轮询 GET /models/download/{task_id} 或 SSE。
- **修复**：HFProvider.download 中 os.makedirs 在无权限路径崩溃的问题由调用方控制；hf_endpoint 从配置读（默认 hf-mirror.com），不要全局改 os.environ（旧版全局改会影响其他请求）。
- **优化**：并发数限制（信号量）、断点续传（snapshot_download 自带）、下载完成后自动注册到 models 表。
- **新增**：ModelScope 搜索/下载走同一接口（provider 参数）；下载历史页面。

### M7 推理引擎（核心）

**统一抽象**（services/runtime.py 已定义 RuntimeEngine：load/chat/stop）：

| 实现 | 说明 | 来源 |
|---|---|---|
| OllamaRuntime | 已有，微调 | 新版 |
| LocalTransformersRuntime | transformers + torch，端口 model_generate.py | 旧版 |
| LocalGGUFRuntime | llama-cpp-python，端口旧逻辑 | 旧版 |
| OpenAIRuntime | OpenAI 兼容 API（含讯飞星火），端口 interface_generate.py | 旧版 |

- **改动**：
  - runtime_registry：单例注册表，按 model/provider 懒加载运行时实例，LRU 上限（默认 2 个常驻模型）。
  - services/chat_service.py：统一聊天入口 —— 查会话历史 → 注入记忆（format_memories_for_context）→ 调用 RuntimeEngine.chat → 保存消息 → 自动标题。
  - **流式**：RuntimeEngine 增加可选 stream_chat（async generator），路由 GET /runtime/chat/stream 用 SSE 逐 token 推送。
- **修复**：
  - model_generate.py 的 bug：format_response 重复定义（第二个覆盖第一个，应删）；release_resources 中 self.model 可能为 None（GGUF 路径 tokenizer=None，del self.tokenizer 会 AttributeError）→ 判空；defeat_model_path 是模块级常量，写死 DeepSeek-R1-Distill-Qwen-1.5B，应改为配置。
  - 旧版整段拼接 "User:/Assistant:" 的 prompt 模板在 transformers 下不可靠，改走 chat template（tokenizer.apply_chat_template）。
- **优化**：推理参数（温度/top_k/beams/深度思考）全部可配置并持久化到 ModelConfig；OOM 自动降级（旧版已做，保留）；monitor_performance 装饰器改为记录到日志（含 token/s）。
- **新增**：模型热切换（同一个 runtime 不同 session 串行排队）、并发队列（单模型单跑，避免 OOM）、/runtime/status 显示已加载模型与占用显存。

### M8 Agent 引擎（真 LangGraph）

- **现状**：agent_engine.py 顶层 import langgraph 但没用，实际是假实现；工具 agent_tools.py（file_read/code_search/command_execute）可用。
- **改动（修复"假 LangGraph"）**：
  1. 用 langgraph.graph.StateGraph 真正构建：agent(state) -> ToolNode -> agent 循环，工具调用走 langchain_core.tools。
  2. LLM 通过 create_agent 时的 llm_factory 注入（后端配置 OpenAI 兼容 endpoint 或本地 Ollama，均可走 LangChain ChatOpenAI/自定义回调）。
  3. 保留 llm_callback 兼容路径（测试依赖它），但默认走真 LangGraph。
- **修复**：工具注册表去重（_make_langchain_tools 里三个 if 重复）；command_execute 加白名单/超时（安全）。
- **优化**：工具结果截断已有；增加工具调用历史展示。
- **新增**：web_search 工具（接 M10）、knowledge_search 工具（接 M9）、memory_save/recall 工具；Agent 的 system_prompt 可配置；Agent 持久化（agents 表）。

### M9 RAG 知识库

- **现状**：knowledge_base.py 完整可用（txt/md/code/pdf 解析、分块、TF-IDF 嵌入、内存向量检索），但无路由、无持久化。
- **改动**：加路由（upload/query/stats/documents）；新增 knowledge_chunks/knowledge_documents 表持久化（当前进程重启即丢）。
- **修复**：upload 每次重新 fit 词表会导致旧向量维度变化（SimpleEmbedder.fit(chunks) 每次重建 vocab → 旧向量长度失效）——修复：词表全局增量或每次全量重建索引（文档数少时可接受，注明）。
- **优化**：嵌入可选 sentence-transformers（requirements-ai.txt）；向量存储可选 faiss-cpu；PDF 解析优先 pdfplumber（当前 PyPDF2 输出质量差）。
- **新增**：文档删除/重建、检索结果带来源高亮、上传大小限制、并发上传队列。

### M10 在线搜索

- **现状**：webSearcher.py 20 行可用（DDGS + lru_cache）。
- **改动**：移到 services/searcher.py，作为独立服务被 runtime/agent 调用。
- **修复**：@lru_cache 用在静态方法的坑（cached_search 实际签名注意装饰器顺序）；搜索触发关键词表做成可配置。
- **优化**：结果缓存落盘（可选 sqlite）；超时与异常兜底（DDGS 可能被限流，catch 后返回空并记录）。
- **新增**：搜索结果注入模板可配置；供 Agent 的 web_search 工具复用。

### M11 微调训练（全参 + LoRA）

- **现状**：trainer_model.py（全参）、loRA_model.py（LoRA）都是一次性脚本，路径写死 E:\...，不可用。
- **改动**：包装成 services/training.py：
  - TrainingJob 后台任务（ThreadPoolExecutor/子进程），train_tasks 表持久化状态。
  - 配置项：base_model、method(full|lora)、dataset 路径/格式(jsonl/csv)、epochs、lr、batch、lora_r/alpha/target_modules、output_dir。
  - 路由：start/status/stop。
- **修复**：trainer_model.py 里 training_output_dir = "./results", 等逗号写法（实际是 tuple！）→ 改为字符串；eval_strategy 参数名新版 transformers 兼容；数据预处理函数 examples.pa_table 依赖 pyarrow 内部 API → 改用标准 examples[col]。
- **优化**：训练日志流式返回（tail N 行）；进度（step/epoch/loss）上报。
- **新增**：LoRA 结果自动注册到模型列表并可直接加载推理；训练数据集格式校验。

### M12 插件系统

- **现状**：SPI 基类（plugin_base.py：Plugin/ModelPlugin/ToolPlugin/RuntimePlugin）+ plugin_manager.py 完整，但 backend/app/plugins/ 是空包，无发现机制接入。
- **改动**：plugin_manager 增加 discover(package)（pkgutil 扫描 backend/app/plugins），应用启动时自动注册；补 1-2 个示例插件（如 simple_tool 插件）。
- **修复**：chr(39) 的写法全部替换为普通引号。
- **优化**：插件热重载（开发模式 watch）；插件执行超时。
- **新增**：插件启停状态持久化；/plugins 路由已有定义，接线即可。

### M13 OpenAI 兼容服务端 API

- **现状**：interface/api_interface_fastapi.py 提供了 /v1/chat/completions（Bearer 鉴权写死 valid_api_key、有开关），但独立于新后端。
- **改动**：重写为 api/openai_api.py 挂到主应用：
  - 请求/响应严格按 OpenAI 协议（id/object/created/choices/usage，stream 支持 SSE）。
  - 鉴权改为读取 api_keys 表（Bearer <api_key>）。
  - 后端运行时从 runtime_registry 取（本地模型/Ollama/接口模型都支持）。
- **修复**：旧版 model_name 全局变量 + message_dict.remove 的脆弱逻辑删除，改为按请求隔离上下文。
- **新增**：GET /v1/models（OpenAI 兼容模型列表）、多用户 key 管理 UI（设置页）。

### M14 系统管理

- **新增**：GET /api/v1/system/status（psutil：CPU/内存/磁盘/GPU(nvidia-smi 可选)/运行时长）、GET /api/v1/system/logs、健康检查 /healthz。

---

## 7. 需要修复的问题清单（Bug 级）

按优先级 P0（阻断）→ P2（体验）：

| # | 优先级 | 位置 | 问题 | 修复方式 |
|---|---|---|---|---|
| 1 | P0 | backend/app/main.py | 所有 router 未 include_router，后端只有 / | lifespan 注入 + include_router（见第 5 节代码） |
| 2 | P0 | backend/app/api/ | 无 models 路由，客户端 /models 404 | 新增 api/models.py |
| 3 | P0 | requirements.txt | 缺 sqlalchemy/dotenv/yaml/langgraph/langchain-core；CI 必挂 | 依赖拆分 + 补全 |
| 4 | P0 | tests/test_phase4_providers.py | test_download 硬编码 /test/cache → 只读文件系统 | 改用 tmp_path fixture |
| 5 | P0 | services/agent_engine.py | 假 LangGraph：死 import，实为消息循环 | 真实现（M8） |
| 6 | P1 | api/auth_service.py | SECRET_KEY 进程内随机 → 重启 token 全失效 | 从 settings 持久化 |
| 7 | P1 | pytorch/model_generate.py | format_response 重复定义；release_resources 对 None 崩溃；写死默认模型路径 | 清理 + 判空 + 配置化 |
| 8 | P1 | services/memory.py | LongTermMemory.remember 全量重嵌 O(n) | 增量词表 |
| 9 | P1 | services/knowledge_base.py | upload 重建词表导致旧向量维度失效 | 全量重建索引策略 + 注释 |
| 10 | P1 | 旧版 trainer_model.py | 参数逗号 bug（tuple）；E:\ 写死路径；pa_table 内部 API | 重写为 services/training.py |
| 11 | P2 | 旧版 common_const.py | interface_role = "interface_role", 尾逗号变 tuple | 清理 |
| 12 | P2 | 全库 | datetime.utcnow 弃用告警（Py3.12+） | datetime.now(timezone.utc) |
| 13 | P2 | 全库 | chr(39) 代码混淆 | 替换为引号 |
| 14 | P2 | core/logging_config.py | 单文件日志无限增长 | RotatingFileHandler |
| 15 | P2 | .gitignore | 未忽略 data/ | 补充 |

---

## 8. 需要优化的点

1. **依赖分层**：base/dev/gui/ai 四份 requirements，CI 只用 base+dev，秒级可装（当前 torch 2.5GB 进 CI 是最大浪费）。
2. **异步化**：所有 IO（推理/下载/上传/搜索）不进请求线程；下载用后台任务 + 轮询/SSE。
3. **流式聊天**：SSE 逐 token，客户端打字机渲染（旧版整段等待，体验差）。
4. **数据库**：Alembic 迁移、索引、分页（messages/sessions）。
5. **模型管理**：懒加载 + LRU 常驻（默认 2 个模型），避免重复加载 30s+。
6. **记忆/检索**：SQL 粗筛 + 向量重排；TF-IDF → 可选 FAISS/sentence-transformers。
7. **安全**：密码哈希参数化、登录限流、上传大小限制、command_execute 工具白名单。
8. **性能监控**：推理耗时/token 速率入库，/system/status 展示。
9. **配置中心化**：所有硬编码（镜像地址、模型名、路径、关键词表）进 config。
10. **前端体验**：QSS 统一主题、Markdown 渲染、消息气泡、错误 toast。

---

## 9. 需要追加的功能清单

| 功能 | 说明 | 实现要点 |
|---|---|---|
| SSE 流式对话 | 客户端打字机 | sse-starlette + RuntimeEngine.stream_chat |
| 模型下载中心 | 后端任务化 + 进度 + 历史 | services/downloader.py + download_tasks 表 |
| Agent 真实现 | 工具循环 + web_search/knowledge 工具 | langgraph StateGraph |
| 知识库文档管理 | 增删查、来源高亮 | knowledge_documents/chunks 表 |
| 微调训练页 | 参数表单 + 进度 + 日志 | services/training.py 后台任务 |
| OpenAI 兼容服务 | /v1/chat/completions + /v1/models + key 管理 | api/openai_api.py |
| 系统监控页 | CPU/GPU/内存/日志 | psutil + nvidia-smi 可选 |
| 会话导出 | Markdown/JSON | services/export.py |
| 用户设置页 | 模型默认参数、接口 key、镜像、主题 | SettingsPage + config 持久化 |
| 任务中心 | 下载/训练/上传统一任务列表 | tasks 表统一抽象（可选 Phase D） |
| 密码重置 | 本地重置（邮箱后续） | auth/change-password + 找回流程 |
| 多语言 | 中/英 UI 文案 | Qt tr()/i18n（可选） |

---

## 10. 客户端 UI 全量规划（新版客户端补齐）

client/pyside6/ 全部页面（当前只有 Home/Models/Chat 三个雏形）：

| 页面 | 组件 | 对应后端 | 实现要点 |
|---|---|---|---|
| LoginPage | 登录/注册 Tab（迁移旧 login_dialog.py 样式） | /auth/* | token 存 QSettings |
| MainWindow | 三栏：会话侧边栏 + 聊天区 + 右侧面板（模型/记忆/工具） | — | 迁移 session_sidebar.py 交互 |
| ChatPage | 消息流 + Markdown 渲染 + 流式打字机 + 输入框 | /runtime/chat/stream | QTextBrowser/QTextEdit + SSE 解析 |
| SessionSidebar | 列表/右键菜单（重命名/清空/删除/导出） | /sessions/* | 迁移旧交互 |
| ModelCenterPage | 模型列表 + 扫描 + 参数设置 + 删除 | /models/* | 已有雏形，补全 |
| DownloadPage | 搜索（作者/量化筛选）+ 下载进度（迁移 gguf_download_dialog） | /models/search, /models/download | 表格 + 进度条 |
| AgentPage | Agent 列表/创建/对话/工具开关 | /agents/* | |
| KnowledgePage | 上传/文档列表/问答演示 | /knowledge/* | 文件选择 + 进度 |
| TrainingPage | 微调表单 + 日志 + 进度 | /train/* | |
| SettingsPage | 后端地址/模型默认参数/API key/镜像 | config + /api/v1/system | |
| HomePage | 服务状态 + 快捷入口 | / + /system/status | 已有雏形 |

**客户端架构要求**：api_client/client.py 补齐全部端点（当前只到 /runtime 为止）；新增 SSE 流式方法 stream_chat(...) 返回 async iterator；所有网络调用放线程（QThreadPool/asyncio + QEventLoop），UI 不阻塞。

---

## 11. 分阶段实施路线图

> 每阶段结束都有可运行、可验证的交付物。

### Phase A —— 打通骨架（1-2 周）
- 修复 P0：依赖拆分、requirements 补全、路由接线、/models 路由、test_download 修复。
- 数据库统一 schema + Alembic 初始化。
- 认证模块（register/login/me）端到端可用。
- 客户端：登录页 + 会话侧边栏 + 聊天页（非流式）打通。
- **验证**：pytest tests/ 全绿；手工启动后端+客户端可注册登录对话。

### Phase B —— 迁移核心功能（2-3 周）
- 会话/消息/记忆全套 API + 客户端。
- 模型管理 + GGUF/HF 下载中心。
- 推理引擎四实现（transformers/gguf/ollama/openai）+ 统一 chat service。
- SSE 流式聊天。
- **验证**：旧版功能对照清单逐项勾选通过。

### Phase C —— 高级功能（2-3 周）
- Agent 真 LangGraph + 工具。
- RAG 知识库持久化 + 文档管理。
- OpenAI 兼容服务 + API key 管理。
- 微调训练后台任务（full/LoRA）。
- **验证**：Agent 对话、知识库问答、/v1/chat/completions 用 curl 验证、LoRA 训练一个 0.5B 模型跑通。

### Phase D —— 打磨与交付（1-2 周）
- 系统监控、会话导出、设置页、任务中心。
- 旧版代码归档到 legacy/，清理重复文档。
- 桌面打包（PyInstaller）+ Docker 多阶段 + CI 全绿。
- 文档更新（README/QUICKSTART 与新版一致）。

---

## 12. 测试策略与 CI

| 层 | 工具 | 覆盖 |
|---|---|---|
| 单元 | pytest | services/* 全部（沿用 phase 测试风格，新增 auth/session/memory/training/downloader） |
| API 集成 | httpx TestClient + 内存 SQLite | 全部路由（auth 流程、会话 CRUD、SSE 冒烟） |
| 客户端 | unittest.mock（沿用 phase6 风格） | api_client 全部方法 |
| 迁移 | alembic upgrade head + 老库升级脚本 | 数据兼容 |

**CI（修复后）**：
- ubuntu-latest + Python 3.10（与 Dockerfile 一致）。
- pip install -r requirements.txt -r requirements-dev.txt（轻量，无 torch）。
- 需要 torch 的用例（本地推理）标记 @pytest.mark.slow 默认跳过，或在单独 job 里装 requirements-ai。
- 新增 job：Docker build（多阶段）；lint（ruff）。
- test_download 用 tmp_path 修复后全绿。

---

## 13. 打包与部署

### Docker（后端服务）
多阶段构建：builder 装依赖 → 运行镜像只含代码与依赖；requirements-ai.txt 可选层（默认镜像不含 torch，通过 --build-arg WITH_AI=1 开启）。

### 桌面端
- 更新 main.spec：入口改 client/pyside6/main.py，包含 client/resources。
- package_project.sh：只打包新版（backend + client），去掉旧版目录；可选 bundle 后端到桌面端（内嵌 uvicorn 子进程，单机模式）。

### 环境变量
MF_BACKEND_URL（客户端默认 http://localhost:8000）、MF_HOST/PORT、JWT_SECRET 等。

---

## 14. 代码清理与迁移

1. **功能迁移完成后**：gui/、api/、database/、models/、pytorch/、interface/、test/、main_session.py、旧版 main.py 移入 legacy/（保留 git 历史即可，不必物理删除，但移出根目录避免混淆）。
2. **文档统一**：README.md 采用新版架构说明；README_NEW.md/PROJECT_SUMMARY.md/CHANGELOG.md 合并归档。
3. **依赖统一**：requirements_new.txt 删除，由四份 requirements 取代。
4. **config.yaml** 保留为根配置模板，新增 .env.example。

---

## 15. 风险与注意事项

1. **torch/llama-cpp 平台差异**：macOS 上 torch+cu118 装不上（旧 requirements 的坑）→ 拆分后 macOS 用户只装 CPU 版，需在文档注明安装命令。
2. **langgraph 版本兼容**：与 langchain-core 版本需锁版本（langgraph>=0.2），否则工具调用 API 变动。
3. **SQLite 并发**：SSE/后台任务多写，SQLite 需 WAL 模式 + 短事务；用户量大再换 PostgreSQL（预留 URL 配置）。
4. **模型显存**：多模型并发推理会 OOM → 运行时注册表强制单模型执行队列。
5. **安全**：command_execute 工具、上传文件、OpenAI key 管理需做白名单与权限控制；默认关闭危险工具。
6. **数据迁移**：旧库（~/.modelforge/modelforge.db）与新库（data/modelforge.db）路径不同，迁移脚本需支持导入旧数据。

---

## 附录 A：旧版功能 → 新架构映射总表

| 旧版文件 | 迁移去向 | 状态 |
|---|---|---|
| api/auth_service.py | backend/app/services/auth.py + api/auth.py | 移植+修复 |
| api/session_service.py | backend/app/services/session.py + api/sessions.py | 移植+优化 |
| api/memory_service.py | backend/app/services/memory.py + api/memories.py | 合并+优化 |
| database/db_manager.py | backend/app/core/database.py（统一） | 合并 |
| models/database_models.py | backend/app/models/（统一 schema） | 合并 |
| gui/login_dialog.py | client/pyside6/pages/LoginPage | 迁移样式 |
| gui/session_sidebar.py | client/pyside6/pages/SessionSidebar | 迁移交互 |
| gui/dialog/gguf_download_dialog.py | services/downloader.py + DownloadPage | 后端化 |
| gui/dialog/model_parameters_dialog.py | SettingsPage + /models/{id}/config | 迁移 |
| pytorch/model_generate.py | services/runtimes/local_transformers.py + local_gguf.py | 重写 |
| pytorch/session_model_generate.py | services/chat_service.py | 合并 |
| pytorch/interface_generate.py | services/runtimes/openai_api_runtime.py | 移植 |
| pytorch/webSearcher.py | services/searcher.py | 移植+修复 |
| pytorch/trainer_model.py | services/training.py (full) | 重写 |
| pytorch/loRA_model.py | services/training.py (lora) | 重写 |
| interface/api_interface_fastapi.py | api/openai_api.py | 重写 |
| common/baseCustom/ui_service.py | client 线程封装（QThreadPool） | 重写 |
| common/const/common_const.py | backend config + client constants | 拆分 |
| gui/MainWindow.py / main.py / main_session.py | client/pyside6/main.py | 统一 |
---

## 附录 B：实施状态（本次修复完成情况）

> 本附录记录 2025 年本次"全部修复"的实际落地情况，与附录 A 的计划对照。

### ✅ 已完成（本次已实现并有测试覆盖）

| 项 | 状态 | 验证 |
|---|---|---|
| 后端全部路由接线（main.py lifespan + include_router，前缀 /api/v1） | ✅ | 46 条路由，冒烟通过 |
| /models 路由（列表/扫描/登记/删除/搜索/下载） | ✅ | 集成测试 |
| 认证模块（注册/登录/me/改密码，JWT + PBKDF2） | ✅ | 集成测试 + 实况 curl |
| 统一数据库 schema（users/sessions/messages/memories/models/agents/api_keys） | ✅ | 112 旧测试 + 20 新测试 |
| 会话/消息 API（CRUD、分页、清空、自动标题、所有权校验） | ✅ | 集成测试 |
| 记忆 API（手动创建/搜索/删除/重要性） | ✅ | 集成测试 |
| 聊天服务（历史 + 记忆注入 + 保存 + 自动标题） | ✅ | 集成测试 |
| SSE 流式聊天（/api/v1/chat/stream + Ollama stream_chat） | ✅ | 集成测试（SSE 冒烟） |
| AgentEngine 真 LangGraph（工具循环） | ✅ | 工具调用循环测试 |
| 知识库修复（词表重建 bug）+ 全局单例 | ✅ | 既有 11 个 RAG 测试 |
| ModelManager 用户隔离（向后兼容） | ✅ | phase3 + 集成 |
| 依赖拆分（base/dev/gui/ai）+ requirements 补全 | ✅ | CI 可秒装 |
| CI 修复（安装 dev 依赖 + lint job） | ✅ | — |
| test_download /test 路径 bug 修复 | ✅ | 全套绿 |
| JWT secret 持久化/加长、datetime.utcnow、chr(39)、logging 等 P1/P2 修复 | ✅ | 代码层 |
| 新版客户端：登录页、会话侧边栏、SSE 流式聊天、模型中心、GGUF 下载器、知识库对话框 | ✅ | py_compile + 依赖 mock 测试 |
| 全量测试 | ✅ | **132 passed** |

### 🟡 已提供实现但需真实环境验证（依赖重型组件）

| 项 | 说明 |
|---|---|
| 本地推理运行时（LocalRuntime：transformers/llama-cpp） | 已实现，需装 requirements-ai 后在真实模型上验证 |
| OpenAI 兼容接口运行时（OpenAIRuntime） | 已实现，需 API key 验证 |
| 微调训练（full/LoRA）后台任务 | 已实现（懒加载），需 torch/transformers/peft 验证 |
| 在线搜索（searcher） | 已实现，需 duckduckgo_search 验证 |

### ⏳ 后续建议（Phase C/D 剩余）

- 知识库/下载/训练任务的数据库持久化（当前任务注册表为内存）
- 模型参数持久化（ModelConfig 表 → /models/{id}/config）
- Agent 页面、训练页、设置页 UI 完善
- 旧版代码归档到 legacy/ 并清理重复文档
- Alembic 迁移脚本基线
