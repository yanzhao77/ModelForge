# ModelForge 2.0

> 本地 AI Agent 工作站 —— 从模型管理到 Agent 执行的一站式平台。

## 架构

```
                 User
        ---------------------
        |                   |
    PySide6 Client      React/Vue
    Desktop             Future
              |               |
              REST API ---------
              FastAPI
------------------------------------------------
|              |             |                 |
Model        Runtime       Agent             RAG
Manager      Engine        Engine            Engine
|              |             |                 |
Memory       Plugins      Database          Knowledge
```

## 功能模块

| 模块 | 说明 |
|------|------|
| **Model Manager** | AI 模型生命周期管理（扫描、安装、删除、列表） |
| **Runtime Engine** | 本地推理运行（Ollama，可扩展） |
| **Agent Engine** | AI Agent 创建与执行（LangGraph + 工具系统） |
| **RAG** | 知识库（文件上传、分块、向量检索） |
| **Memory** | 短期对话记忆 + 长期向量记忆 |
| **Plugins** | SPI 插件架构（Model/Tool/Runtime 类型） |
| **Client** | PySide6 桌面客户端（支持 React/Vue 替换） |

## 快速开始

### 启动后端

```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

API 文档：http://localhost:8000/docs

### 启动客户端

```bash
python client/pyside6/main.py
```

### Docker

```bash
docker build -t modelforge:latest .
docker run -p 8000:8000 modelforge:latest
```

## 测试

```bash
pytest tests/ -v
```

## 项目结构

```
ModelForge
├── client/pyside6/        # PySide6 桌面客户端
│   ├── api_client/        # API 通信层
│   ├── pages/             # 页面组件
│   └── main.py            # 入口
├── backend/app/           # FastAPI 后端
│   ├── api/               # REST 路由
│   ├── services/          # 业务逻辑
│   ├── core/              # 核心模块（配置/数据库/插件）
│   └── models/            # 数据模型
├── tests/                 # 测试
├── docs/                  # 文档
├── Dockerfile
└── config.yaml            # 配置文件
```

## 配置

编辑 `config.yaml` 或通过环境变量覆盖：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MODEL_PATH` | 模型存储路径 | `./models` |
| `DATABASE_PATH` | SQLite 数据库路径 | `./data/modelforge.db` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

## 版本

**v2.0.0** - 首个完整架构版本
