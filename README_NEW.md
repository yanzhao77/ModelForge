# ModelForge 2.0

> 🚀 本地大模型推理与训练平台 - 现已支持多会话管理和智能记忆系统

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Educational-green.svg)](LICENSE)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-orange.svg)](https://www.qt.io/qt-for-python)

## ✨ 新版本亮点

ModelForge 2.0 是一个功能强大的本地大模型推理平台，专为 AI 开发者和研究者设计。新版本带来了革命性的用户体验升级：

### 🎯 核心特性

| 功能 | 描述 | 状态 |
|------|------|------|
| **用户管理** | 注册、登录、JWT 认证 | ✅ |
| **多会话管理** | 创建、切换、管理多个对话 | ✅ |
| **智能记忆** | 跨会话记住用户偏好和信息 | ✅ |
| **GGUF 支持** | 完整的 GGUF 模型下载和使用 | ✅ |
| **对话持久化** | 所有对话自动保存到数据库 | ✅ |
| **在线搜索** | 集成网络搜索增强回答 | ✅ |
| **模型自适应** | 自动识别 safetensors 和 gguf 格式 | ✅ |

### 🆕 2.0 版本新增功能

**用户体验升级**

ModelForge 2.0 实现了类似 ChatGPT 的用户体验，支持多会话管理和智能记忆系统。您可以在不同的对话中切换，系统会自动记住您的偏好和重要信息。

**智能记忆系统**

系统会自动从对话中提取关键信息：
- 当您说"我喜欢..."时，系统记录为偏好
- 当您说"我是..."时，系统记录为事实
- 在新对话中，系统自动注入相关记忆

**GGUF 模型下载**

专门优化的 GGUF 模型下载器，支持：
- 按作者筛选（TheBloke、lmstudio-community 等）
- 量化类型识别（Q4_K_M、Q5_K_M 等）
- 单文件下载
- HF-Mirror 镜像加速

## 📸 界面预览

```
┌─────────────────────────────────────────────────────────────┐
│  ModelForge - 用户名                                    [_][□][×]│
├─────────────────────────────────────────────────────────────┤
│  文件  模型  会话  帮助                                        │
├───────────────┬─────────────────────────────────────────────┤
│  对话列表      │  对话区域                                     │
│               │                                              │
│  + 新建对话    │  用户: 你好                                   │
│               │  助手: 你好！有什么可以帮您的吗？              │
│  ▼ 新对话      │                                              │
│  ▼ Python学习  │  用户: 推荐一些 Python 资源                   │
│  ▼ 工作讨论    │  助手: [记忆注入] 根据您之前提到的...          │
│               │                                              │
│               │  ┌──────────────────────────────────┐        │
│               │  │ 输入消息...                [发送]│        │
│               │  └──────────────────────────────────┘        │
└───────────────┴─────────────────────────────────────────────┘
```

## 🚀 快速开始

### 安装

```bash
# 克隆项目
git clone https://github.com/yanzhao77/ModelForge.git
cd ModelForge

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install sqlalchemy pyjwt PySide6
```

### 启动

```bash
python main_session.py
```

### 首次使用

1. **注册账户** - 启动后自动弹出登录窗口
2. **下载模型** - 使用内置的 GGUF 下载器
3. **加载模型** - 选择模型目录
4. **开始对话** - 享受智能对话体验

详细步骤请查看 [快速开始指南](QUICKSTART.md)

## 📚 文档

- [快速开始指南](QUICKSTART.md) - 5 分钟上手
- [完整使用指南](USAGE_GUIDE.md) - 详细功能说明
- [更新日志](CHANGELOG.md) - 版本更新记录
- [项目分析](ANALYSIS.md) - 技术架构分析

## 🏗️ 技术架构

### 技术栈

**前端**
- PySide6 - 现代化 GUI 框架
- Qt - 跨平台界面

**后端**
- PyTorch - 深度学习框架
- Transformers - HuggingFace 模型库
- llama-cpp-python - GGUF 模型支持

**数据库**
- SQLite - 轻量级数据库
- SQLAlchemy - ORM 框架

**认证**
- JWT - Token 认证
- PBKDF2 - 密码哈希

### 项目结构

```
ModelForge/
├── main_session.py              # 新版主程序入口
├── gui/                         # GUI 组件
│   ├── SessionMainWindow.py     # 主窗口
│   ├── login_dialog.py          # 登录界面
│   ├── session_sidebar.py       # 会话侧边栏
│   └── dialog/
│       └── gguf_download_dialog.py  # GGUF 下载器
├── database/                    # 数据库层
│   └── db_manager.py
├── models/                      # 数据模型
│   └── database_models.py
├── api/                         # 服务层
│   ├── auth_service.py          # 认证服务
│   ├── session_service.py       # 会话服务
│   └── memory_service.py        # 记忆服务
├── pytorch/                     # 推理引擎
│   ├── model_generate.py        # 基础模型生成器
│   └── session_model_generate.py  # 会话模型生成器
└── test/                        # 测试脚本
    ├── test_database_auth.py
    └── test_session_model.py
```

## 🧪 测试

### 运行测试

```bash
# 数据库和认证测试
python test/test_database_auth.py

# 会话模型测试（需要模型文件）
python test/test_session_model.py
```

### 测试结果

所有核心功能已通过测试：
- ✅ 数据库初始化
- ✅ 用户注册和登录
- ✅ JWT Token 验证
- ✅ 会话管理
- ✅ 消息存储
- ✅ 记忆提取和检索

## 🎯 使用场景

### 个人 AI 助手

创建多个专用会话：
- 工作助手 - 处理工作相关问题
- 学习助手 - 帮助学习新知识
- 生活助手 - 日常生活建议

系统会记住每个场景的上下文和您的偏好。

### AI 开发和研究

- 本地部署，数据安全
- 支持多种模型格式
- 完整的对话历史记录
- 便于实验和调试

### 模型测试和评估

- 快速切换不同模型
- 对比不同量化版本
- 记录测试对话
- 分析模型表现

## 🔧 高级功能

### 自定义记忆提取

编辑 `api/memory_service.py` 自定义记忆提取规则：

```python
PREFERENCE_KEYWORDS = ["喜欢", "不喜欢", "偏好", ...]
FACT_KEYWORDS = ["我是", "我在", "我的", ...]
```

### 调整模型参数

```python
generator = SessionModelGenerate(
    user_id=user_id,
    session_id=session_id,
    model_path=model_path,
    max_new_tokens=2048,
    temperature=0.7,
    top_k=50
)
```

### 数据备份

```bash
# 备份数据库
cp ~/.modelforge/modelforge.db ~/backup/

# 恢复数据库
cp ~/backup/modelforge.db ~/.modelforge/
```

## 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📝 许可证

本项目仅供学习与研究使用，禁止用于商业用途。

## 🙏 致谢

- HuggingFace - 模型和工具
- llama.cpp - GGUF 模型支持
- Qt/PySide6 - GUI 框架
- SQLAlchemy - ORM 框架

## 📮 联系方式

- GitHub: [yanzhao77/ModelForge](https://github.com/yanzhao77/ModelForge)
- Issues: [提交问题](https://github.com/yanzhao77/ModelForge/issues)

---

⭐ 如果这个项目对您有帮助，请给个 Star！
