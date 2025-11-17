# ModelForge 快速开始指南

## 5 分钟上手 ModelForge 2.0

### 第一步：安装

```bash
# 克隆项目
git clone https://github.com/yanzhao77/ModelForge.git
cd ModelForge

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install sqlalchemy pyjwt PySide6
```

### 第二步：启动应用

```bash
python main_session.py
```

### 第三步：注册账户

启动后会自动弹出登录窗口：

1. 点击"注册"标签页
2. 输入用户名（至少 3 个字符）
3. 输入密码（至少 6 个字符）
4. 点击"注册"按钮
5. 注册成功后切换到"登录"标签页登录

### 第四步：下载模型（可选）

如果您还没有模型：

1. 点击菜单"模型" -> "下载 GGUF 模型"
2. 在"作者"下拉框选择 "TheBloke"
3. 在搜索框输入模型名称，如 "llama"
4. 点击一个模型查看可用的 GGUF 文件
5. 选择一个量化版本（推荐 Q4_K_M）
6. 点击"下载选中的 GGUF 文件"

**推荐的小模型**（适合测试）：
- `TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF`
- `TheBloke/Phi-2-GGUF`

### 第五步：加载模型

1. 点击工具栏的"加载模型"按钮
2. 选择模型所在的目录
3. 等待模型加载完成（会显示提示）

### 第六步：开始对话

1. 在底部输入框输入消息
2. 按回车或点击"发送"
3. 等待 AI 回复

### 第七步：体验多会话功能

**创建新会话**：
- 点击左侧"+ 新建对话"按钮

**切换会话**：
- 点击左侧会话列表中的任意会话

**管理会话**：
- 右键点击会话可以重命名、清空或删除

### 第八步：体验记忆功能

在对话中说：

```
我喜欢使用 Python 编程
我是一名 AI 工程师
```

然后创建一个新会话，问：

```
推荐一些编程资源
```

AI 会自动记住您之前说的偏好和职业信息！

## 常用快捷键

- `Ctrl+N` - 新建对话
- `Ctrl+Q` - 退出应用
- `Enter` - 发送消息

## 下一步

- 阅读完整的 [使用指南](USAGE_GUIDE.md)
- 查看 [更新日志](CHANGELOG.md)
- 运行测试脚本验证功能

## 需要帮助？

- 查看 [常见问题](USAGE_GUIDE.md#常见问题)
- 提交 [Issue](https://github.com/yanzhao77/ModelForge/issues)

祝您使用愉快！🎉
