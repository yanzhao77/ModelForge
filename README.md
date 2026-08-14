# ModelForge 旧版桌面端（gui_old 分支）

> ⚠️ 本分支是 **ModelForge 旧版 v2.0 桌面端** 的存档分支（快照）。
> 新版（FastAPI 后端 + PySide6 瘦客户端，功能完整、152 测试全绿）在 **master** 分支。

## 本分支内容

旧版为 **PySide6 单体桌面应用**，业务逻辑与 UI 一体，包含：

| 模块 | 说明 |
|------|------|
| 用户系统 | 注册/登录、JWT 认证、PBKDF2 密码哈希（api/auth_service.py） |
| 多会话 | 创建/删除/切换/重命名/清空会话、自动标题、消息持久化（gui/session_sidebar.py、api/session_service.py） |
| 跨会话记忆 | 关键词提取偏好/事实、重要性评分、搜索、上下文注入（api/memory_service.py） |
| 模型下载 | GGUF 下载对话框：HF 搜索、作者筛选、量化识别、hf-mirror（gui/dialog/gguf_download_dialog.py） |
| 本地推理 | transformers + llama-cpp-python，支持深度思考/快速模式、OOM 降级（pytorch/model_generate.py） |
| 接口对话 | OpenAI 兼容接口（含讯飞星火）与 /v1/chat/completions 兼容服务（pytorch/interface_generate.py、interface/） |
| 微调脚本 | 全参微调（pytorch/trainer_model.py）、LoRA 微调（pytorch/loRA_model.py） |
| 在线搜索 | DuckDuckGo 搜索（pytorch/webSearcher.py） |
| 数据库 | SQLite + SQLAlchemy（database/db_manager.py、models/database_models.py） |

## 运行旧版

```bash
# 依赖（注意：torch 版本为 +cu118，仅 Linux；macOS 请自行调整）
pip install -r requirements_new.txt

# 会话版入口（会话 + 记忆 + GGUF 下载，推荐）
python main_session.py

# 原始入口（基础桌面端）
python main.py
```

## 目录

```
ModelForge (gui_old)
├── gui/           # PySide6 界面（主窗口/登录/会话侧边栏/对话框/菜单）
├── pytorch/       # 推理与微调（model_generate / trainer / LoRA / 接口）
├── api/           # 服务层（auth / session / memory）
├── database/      # SQLite 数据库管理器
├── models/        # SQLAlchemy 数据模型
├── interface/     # 独立接口服务（FastAPI / Falcon chat completions）
├── common/        # 常量与 UI 工具
├── test/          # 手工测试脚本
├── icon/ model/   # 资源
├── main.py        # 原始入口
├── main_session.py # 会话版入口（推荐）
├── requirements_new.txt  # 依赖
└── docs/screenshots/     # 界面截图
```

## 与新版的关系

- 旧版功能已**全部迁移**到 master 的新版架构（认证/会话/记忆/GGUF 下载/本地推理/微调脚本等），并补充了数据集、训练任务化、知识库持久化、SSE 流式、真 LangGraph Agent 等能力。
- 本分支仅用于**存档/参考**，不再维护。需要对比或找回旧代码时切换到此分支即可。
