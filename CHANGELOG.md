# ModelForge 更新日志

## [2.0.0] - 2025-11-17

### 🎉 重大更新

#### 新增功能

1. **用户管理系统**
   - ✅ 用户注册和登录
   - ✅ JWT Token 认证
   - ✅ 密码哈希存储（PBKDF2-HMAC-SHA256）
   - ✅ 用户会话管理

2. **多会话管理**
   - ✅ 创建、删除、切换多个对话会话
   - ✅ 会话重命名
   - ✅ 会话消息清空
   - ✅ 自动生成会话标题
   - ✅ 会话列表侧边栏

3. **跨会话记忆系统**
   - ✅ 自动提取用户偏好记忆
   - ✅ 自动提取事实记忆
   - ✅ 智能记忆搜索和检索
   - ✅ 记忆重要性评分
   - ✅ 记忆访问统计
   - ✅ 自动记忆注入到新会话

4. **GGUF 模型下载优化**
   - ✅ 专用 GGUF 模型下载对话框
   - ✅ 支持按作者筛选（TheBloke、lmstudio-community 等）
   - ✅ 量化类型识别和显示
   - ✅ 单文件下载支持
   - ✅ HF-Mirror 镜像加速

5. **数据持久化**
   - ✅ SQLite 数据库存储
   - ✅ SQLAlchemy ORM
   - ✅ 对话历史自动保存
   - ✅ 用户数据隔离

6. **用户界面改进**
   - ✅ 现代化登录界面
   - ✅ 三栏布局（会话列表 | 对话区域）
   - ✅ 会话右键菜单
   - ✅ 实时消息显示
   - ✅ 加载动画和进度提示

#### 技术改进

1. **架构优化**
   - 引入服务层（Service Layer）
   - 数据库管理器单例模式
   - 模型生成器支持会话上下文

2. **代码组织**
   - 新增 `database/` 模块
   - 新增 `models/` 模块
   - 新增 `api/` 服务层
   - 改进的测试脚本

3. **性能优化**
   - 后台线程处理模型推理
   - 数据库连接池
   - 记忆缓存和访问统计

#### 新增文件

**核心模块**
- `models/database_models.py` - 数据库模型定义
- `database/db_manager.py` - 数据库管理器
- `api/auth_service.py` - 认证服务
- `api/session_service.py` - 会话服务
- `api/memory_service.py` - 记忆服务

**GUI 组件**
- `gui/SessionMainWindow.py` - 新主窗口
- `gui/login_dialog.py` - 登录对话框
- `gui/session_sidebar.py` - 会话侧边栏
- `gui/dialog/gguf_download_dialog.py` - GGUF 下载对话框

**推理引擎**
- `pytorch/session_model_generate.py` - 支持会话的模型生成器

**测试脚本**
- `test/test_database_auth.py` - 数据库和认证测试
- `test/test_session_model.py` - 会话模型测试

**文档**
- `USAGE_GUIDE.md` - 完整使用指南
- `CHANGELOG.md` - 更新日志
- `ANALYSIS.md` - 项目分析文档

**其他**
- `main_session.py` - 新的主程序入口
- `requirements_new.txt` - 更新的依赖列表

#### 依赖更新

新增依赖：
- `sqlalchemy>=2.0.0` - ORM 框架
- `pyjwt>=2.8.0` - JWT 认证
- `passlib>=1.7.4` - 密码哈希（可选）
- `bcrypt>=4.0.1` - 密码加密（可选）

#### Bug 修复

1. ✅ 修复记忆搜索的 SQL 查询问题
2. ✅ 修复模型加载时的资源释放问题
3. ✅ 改进错误处理和异常捕获
4. ✅ 修复会话切换时的上下文丢失问题

#### 已知问题

1. ⚠️ 密码重置功能尚未实现
2. ⚠️ 向量化记忆搜索为可选功能
3. ⚠️ 大规模会话可能影响性能

#### 迁移指南

**从 v1.0 升级到 v2.0**

1. 备份现有数据（如果有）
2. 安装新依赖：
   ```bash
   pip install sqlalchemy pyjwt
   ```
3. 使用新的入口文件：
   ```bash
   python main_session.py  # 新版本
   # 而不是
   python main.py  # 旧版本
   ```
4. 首次启动会自动创建数据库

**数据迁移**

如果您有旧版本的对话数据，需要手动迁移：
- 旧版本没有数据库，对话不持久化
- 新版本所有对话自动保存
- 无需迁移操作

---

## [1.0.0] - 初始版本

### 功能

- ✅ 支持 HuggingFace Transformers 格式模型
- ✅ 支持 GGUF 格式模型（llama-cpp-python）
- ✅ PySide6 图形界面
- ✅ 在线搜索增强
- ✅ 性能监控
- ✅ 模型自动识别
- ✅ 基础对话功能

### 限制

- ❌ 无用户管理
- ❌ 无会话持久化
- ❌ 无记忆功能
- ❌ 单会话模式
