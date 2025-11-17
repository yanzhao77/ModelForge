# ModelForge 使用指南

## 项目简介

ModelForge 是一个功能强大的本地大模型推理与训练平台，现已升级支持：

- ✅ **用户管理系统**：注册、登录、JWT 认证
- ✅ **多会话管理**：支持创建、切换、删除多个对话会话
- ✅ **跨会话记忆**：智能提取和注入用户记忆，实现类似 ChatGPT 的记忆功能
- ✅ **GGUF 模型支持**：完整支持 GGUF 格式模型的下载和使用
- ✅ **对话历史持久化**：所有对话自动保存到数据库
- ✅ **智能上下文管理**：自动管理对话历史和记忆注入

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/yanzhao77/ModelForge.git
cd ModelForge
```

### 2. 创建虚拟环境

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. 安装依赖

```bash
# 安装基础依赖
pip install -r requirements_new.txt

# 如果需要 GPU 支持（CUDA 11.8）
pip install torch==2.2.0+cu118 torchvision==0.17.0+cu118 torchaudio==2.2.0 --index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu118/
```

## 快速开始

### 启动应用（支持会话管理）

```bash
python main_session.py
```

### 首次使用

1. **注册账户**
   - 启动后会自动弹出登录/注册对话框
   - 点击"注册"标签页
   - 输入用户名、密码（可选邮箱）
   - 点击"注册"按钮

2. **登录**
   - 输入用户名和密码
   - 点击"登录"按钮

3. **下载模型**
   - 点击菜单栏"模型" -> "下载 GGUF 模型"
   - 选择作者（推荐 TheBloke）
   - 搜索模型（如 "llama"）
   - 选择模型和 GGUF 文件
   - 点击"下载"

4. **加载模型**
   - 点击"加载模型"按钮
   - 选择模型目录
   - 等待模型加载完成

5. **开始对话**
   - 在输入框中输入消息
   - 按回车或点击"发送"
   - AI 会自动记住对话历史和重要信息

## 核心功能详解

### 1. 多会话管理

**创建新会话**
- 点击左侧"+ 新建对话"按钮
- 或使用菜单 "文件" -> "新建对话"
- 快捷键：`Ctrl+N`

**切换会话**
- 在左侧会话列表中点击任意会话
- 对话区域会自动加载该会话的历史消息

**管理会话**
- 右键点击会话可以：
  - 重命名会话
  - 清空消息
  - 删除会话

### 2. 跨会话记忆系统

ModelForge 会自动从您的对话中提取关键信息并记住：

**自动记忆类型**
- **偏好记忆**：当您说"我喜欢..."、"我不喜欢..."时
- **事实记忆**：当您说"我是..."、"我的工作是..."时
- **上下文记忆**：重要的对话上下文

**记忆使用示例**

```
会话 1:
用户: 我喜欢使用 Python 编程，我是一名 AI 工程师
助手: 好的，我记住了您喜欢 Python 和您的职业

会话 2（新会话）:
用户: 推荐一些编程资源
助手: [系统会自动注入记忆]
      根据您之前提到的，您是 AI 工程师且喜欢 Python...
```

### 3. GGUF 模型下载

**推荐的 GGUF 模型来源**
- **TheBloke**：最大的 GGUF 模型提供者
- **lmstudio-community**：LM Studio 官方模型
- **QuantFactory**：高质量量化模型

**量化类型说明**
- `Q2_K`：最小体积，质量较低
- `Q4_K_M`：推荐，平衡质量和体积
- `Q5_K_M`：高质量
- `Q8_0`：接近原始质量，体积较大

**下载步骤**
1. 打开"下载 GGUF 模型"对话框
2. 选择作者或搜索模型
3. 点击模型查看可用的 GGUF 文件
4. 选择合适的量化版本
5. 点击"下载"

### 4. 模型加载

**支持的模型格式**
- **Safetensors**：HuggingFace Transformers 格式
- **GGUF**：llama.cpp 格式（推荐用于 CPU 推理）

**加载方式**
- 点击"加载模型"
- 选择模型目录（不是单个文件）
- 系统会自动识别模型格式

### 5. 对话功能

**基础对话**
- 输入消息后按回车或点击"发送"
- AI 会记住整个会话的上下文

**上下文记忆**
- 系统自动维护对话历史
- 支持多轮对话
- 自动注入相关记忆

**在线搜索增强**（如果配置）
- 当问题包含"最新"、"当前"等关键词时
- 系统会自动进行网络搜索并整合结果

## 数据存储

### 数据库位置

```
~/.modelforge/modelforge.db
```

### 数据库结构

- **users**：用户信息
- **sessions**：会话列表
- **messages**：对话消息
- **memories**：用户记忆
- **model_configs**：模型配置

### 备份数据

```bash
# 备份数据库
cp ~/.modelforge/modelforge.db ~/.modelforge/modelforge_backup.db

# 恢复数据库
cp ~/.modelforge/modelforge_backup.db ~/.modelforge/modelforge.db
```

## 测试

### 运行数据库测试

```bash
python test/test_database_auth.py
```

### 运行模型测试（需要模型文件）

```bash
python test/test_session_model.py
```

## 常见问题

### Q1: 如何重置密码？

目前需要直接操作数据库或重新注册。后续版本会添加密码重置功能。

### Q2: 记忆系统如何工作？

记忆系统通过关键词匹配自动提取重要信息：
- 当您说"我喜欢..."时，系统会记录为偏好
- 当您说"我是..."时，系统会记录为事实
- 在新对话中，系统会自动搜索相关记忆并注入

### Q3: GGUF 模型下载很慢？

- 使用 HF-Mirror 镜像站（已默认配置）
- 选择较小的量化版本（如 Q4_K_M）
- 检查网络连接

### Q4: 模型加载失败？

- 确认模型路径正确
- 检查是否安装了 llama-cpp-python（GGUF 模型需要）
- 查看错误信息，可能是内存不足

### Q5: 如何清理旧会话？

- 右键点击会话 -> 删除
- 或在数据库中手动清理

## 高级功能

### 1. 自定义记忆提取

编辑 `api/memory_service.py` 中的关键词列表：

```python
PREFERENCE_KEYWORDS = ["喜欢", "不喜欢", "偏好", ...]
FACT_KEYWORDS = ["我是", "我在", "我的", ...]
```

### 2. 调整模型参数

在加载模型时可以自定义参数：

```python
generator = SessionModelGenerate(
    user_id=user_id,
    session_id=session_id,
    model_path=model_path,
    max_new_tokens=2048,  # 最大生成长度
    temperature=0.7,      # 温度（创造性）
    top_k=50,             # Top-K 采样
    repetition_penalty=1.2  # 重复惩罚
)
```

### 3. 记忆清理

定期清理低重要性的记忆：

```python
from api.memory_service import MemoryService

with db_manager.get_session() as db:
    deleted = MemoryService.cleanup_old_memories(
        db, user_id, keep_count=100
    )
    print(f"清理了 {deleted} 条记忆")
```

## 开发指南

### 项目结构

```
ModelForge/
├── main_session.py           # 新的主程序入口
├── gui/
│   ├── SessionMainWindow.py  # 支持会话的主窗口
│   ├── login_dialog.py       # 登录对话框
│   ├── session_sidebar.py    # 会话侧边栏
│   └── dialog/
│       └── gguf_download_dialog.py  # GGUF 下载对话框
├── database/
│   └── db_manager.py         # 数据库管理器
├── models/
│   └── database_models.py    # 数据库模型定义
├── api/
│   ├── auth_service.py       # 认证服务
│   ├── session_service.py    # 会话服务
│   └── memory_service.py     # 记忆服务
├── pytorch/
│   └── session_model_generate.py  # 会话模型生成器
└── test/
    ├── test_database_auth.py  # 数据库测试
    └── test_session_model.py  # 模型测试
```

### 扩展功能

**添加新的记忆类型**

1. 在 `models/database_models.py` 中定义
2. 在 `api/memory_service.py` 中添加提取逻辑
3. 在 `pytorch/session_model_generate.py` 中使用

**集成向量化搜索**

```bash
pip install sentence-transformers faiss-cpu
```

然后在 `memory_service.py` 中实现向量化记忆检索。

## 许可证

本项目仅供学习与研究使用，禁止用于商业用途。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v2.0 (2025-11-17)
- ✅ 添加用户管理系统
- ✅ 实现多会话管理
- ✅ 实现跨会话记忆功能
- ✅ 优化 GGUF 模型下载
- ✅ 完整的数据库持久化

### v1.0
- 基础模型推理功能
- 支持 safetensors 和 gguf 格式
- PySide6 图形界面

## 联系方式

- GitHub: https://github.com/yanzhao77/ModelForge
- Issues: https://github.com/yanzhao77/ModelForge/issues
