# ModelForge 2.1

> 本地 AI Agent 工作站 —— 从模型管理、微调训练到 Agent 执行的一站式平台。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-152%20passed-brightgreen)
![API](https://img.shields.io/badge/API-58%20routes-important)
![License](https://img.shields.io/badge/License-MIT-blue)

基于 **FastAPI 后端 + PySide6 瘦客户端** 架构：后端承载全部业务逻辑，客户端只做展示与交互。

## 功能一览

| 模块 | 说明 |
|------|------|
| 用户系统 | 注册/登录/改密码，JWT 认证，PBKDF2 密码哈希，用户数据隔离 |
| 会话/消息 | 多会话创建/切换/重命名/软删除，消息持久化，自动标题 |
| 跨会话记忆 | 关键词规则提取（偏好/事实）、搜索、重要性评分、上下文注入 |
| 模型管理 | 扫描/登记/删除，HF 模型搜索与后台下载（GGUF 等） |
| 推理运行时 | Ollama（SSE 流式）、本地 transformers/GGUF（需 requirements-ai.txt）、OpenAI 兼容接口 |
| 聊天 | 统一 chat service（历史+记忆注入+持久化），**SSE 流式输出** |
| Agent | 真 LangGraph 工具循环（读文件/搜代码/执行命令/联网搜索/知识库检索） |
| 知识库 | 文档上传/持久化/分块查看/检索/**RAG 问答**（带引用来源） |
| 数据集 | jsonl/csv/json/txt 上传、解析、预览、训练预检 |
| 微调训练 | 全参/LoRA，子进程隔离执行，进度/loss 上报，SSE 日志流，产物注册到模型列表 |
| OpenAI 兼容 | `/v1/chat/completions`（含流式）+ `/v1/models` |
| 系统监控 | CPU/GPU/内存/磁盘/日志/健康检查 |

## 快速开始

### 1. 启动后端（需 Python 3.10+）

```bash
pip install -r requirements.txt -r requirements-dev.txt
uvicorn backend.app.main:app --reload --port 8000
```

API 文档（Swagger）：http://localhost:8000/docs

### 2. 启动桌面客户端（可选）

```bash
pip install -r requirements-gui.txt
python client/pyside6/main.py
```

启动后先注册/登录，即可使用：聊天（SSE 流式）、会话管理、数据集上传、微调训练、知识库 RAG 问答。

### 3. AI 推理 / 训练能力（按需安装）

```bash
pip install -r requirements-ai.txt   # torch / transformers / llama-cpp-python / peft / datasets ...
```

> 不安装 AI 依赖也能启动后端与客户端（Ollama 推理、认证、会话、数据集、知识库检索均可用）。

## API 概览（58 条路由，前缀 /api/v1）

| 模块 | 端点 |
|------|------|
| 认证 | auth/register · login · me · change-password |
| 会话 | sessions（CRUD）· sessions/{id}/messages · title |
| 记忆 | memories · memories/search |
| 模型 | models（list/scan/install）· models/search · models/download |
| 运行时 | runtime/start · chat · stop · status |
| 聊天 | chat · **chat/stream（SSE 流式）** |
| 数据集 | datasets/upload · datasets · datasets/{id}/validate |
| 训练 | train/start · status · **stream（SSE 日志）** · stop · templates · tasks · {id}/register-model |
| 知识库 | knowledge/upload · documents · query · **answer（RAG）** · stats |
| Agent | agent/create · list · {name}/chat |
| OpenAI 兼容 | /v1/chat/completions（含流式）· /v1/models |
| 系统 | system/status · system/logs · /healthz |

## 测试

```bash
pytest tests/ -v    # 152 个用例（单元 + API 集成 + 数据集/训练/知识库）
```

## 目录结构

```
ModelForge
├── backend/app/            # FastAPI 后端
│   ├── api/                # 路由：auth/models/runtime/chat/sessions/memories/agent/
│   │                       #       knowledge/datasets/train/plugins/system/openai
│   ├── core/               # 配置/数据库/安全/日志
│   ├── models/             # SQLAlchemy 模型（11 张表）
│   ├── services/           # 业务层（15+ 服务）
│   └── plugins/            # SPI 插件包
├── client/pyside6/         # PySide6 瘦客户端
│   ├── api_client/         # REST + SSE 客户端
│   └── pages/              # 登录/数据集/训练/知识库页面
├── tests/                  # pytest（152 用例）
├── docs/                   # TECHNICAL_REPORT.md / DEVELOPMENT_PLAN.md
├── requirements*.txt       # base / dev / gui / ai 四层依赖
└── config.yaml             # 配置文件（支持环境变量覆盖）
```

## 配置

编辑 `config.yaml` 或通过环境变量覆盖（环境变量优先级最高）：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `MODEL_PATH` | 模型目录 | ./models |
| `DATABASE_PATH` | SQLite 路径 | ./data/modelforge.db |
| `JWT_SECRET` | JWT 签名密钥（生产必改） | dev-secret |
| `OLLAMA_BASE_URL` | Ollama 服务地址 | http://localhost:11434 |
| `HF_ENDPOINT` | HF 镜像 | https://hf-mirror.com |
| `DATASET_DIR` / `TRAIN_OUTPUT_DIR` | 数据集/训练产物目录 | ./data/datasets / ./outputs |
| `LOG_LEVEL` | 日志级别 | INFO |

## 分支说明

- **master**：当前版本。新版架构（FastAPI + 瘦客户端），功能完整，152 测试全绿。
- **gui_old**：旧版 v2.0 PySide6 桌面端存档分支（登录/会话/记忆/GGUF 下载/本地推理/微调脚本），不再维护，仅作参考。

## 文档

- [统一架构技术报告](docs/TECHNICAL_REPORT.md) —— 架构决策、模块设计、修复/优化/新增清单、实施状态
- [微调/数据集/知识库开发计划](docs/DEVELOPMENT_PLAN.md) —— 三大功能的设计与实施状态

## 版本历史

- **v2.1**（当前）：统一新版架构；认证/会话/记忆/模型/流式聊天/Agent/数据集/训练/知识库全部落地，58 条 API、152 测试。
- **v2.0**：旧版桌面端（已归档到 gui_old 分支）。
