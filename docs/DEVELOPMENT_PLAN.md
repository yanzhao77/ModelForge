# ModelForge 微调 / 数据集 / 知识库 —— 功能开发计划

> 目标：把「模型微调」从脚本级做成完整的可用功能，补齐**数据集管理界面**并实现与训练界面的**联动**，同时把**知识库**从"上传+问答对话框"升级为完整的管理界面，并与聊天 / Agent / 训练打通。
>
> 依据：本文是**开发计划**，按模块给出接口定义、实现方案、UI 设计、联动关系与分阶段排期。
>
> ✅ **计划已按 Phase 1→2→3 全部执行完毕**（数据集/训练/知识库已实现，详见文末附录与 [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md) 的当前状态）；本文保留作为设计依据与排期参考。
>
> 🚀 **ModelForge 3.0 已另行执行完毕**：Agent Run / Event System / Tool Registry / Context Engine / Policy / MCP / Client / Scheduler / Multi-Agent 十个 Phase 全部落地（287 测试全绿）。
>
> 🧩 **3.x Composable Agent & Tool Plugin 已按审计路线图执行完毕**（P0 加固 → P6 Capability Discovery，339 测试全绿）：
> 见 [MODELFORGE_3_RUNTIME_ARCHITECTURE_AUDIT.md](MODELFORGE_3_RUNTIME_ARCHITECTURE_AUDIT.md)（结论 B，已落地）与 [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md)。
> 实施规范见 [AGENT_RUNTIME_DEVELOPMENT.md](AGENT_RUNTIME_DEVELOPMENT.md)，架构见 [AGENT_RUNTIME.md](AGENT_RUNTIME.md)，API 见 [API_REFERENCE.md](API_REFERENCE.md)。
> 本文（2.0 功能开发计划）继续作为设计依据保留。

---

## 目录

1. [背景与现状](#1-背景与现状)
2. [目标与联动总览](#2-目标与联动总览)
3. [数据库设计（新增/变更表）](#3-数据库设计新增变更表)
4. [后端 API 设计](#4-后端-api-设计)
5. [后端实现方案（分模块）](#5-后端实现方案分模块)
6. [客户端 UI 设计](#6-客户端-ui-设计)
7. [页面联动设计](#7-页面联动设计)
8. [分阶段实施路线图](#8-分阶段实施路线图)
9. [测试计划与 CI](#9-测试计划与-ci)
10. [风险与注意事项](#10-风险与注意事项)
11. [附录：关键接口 JSON 示例](#11-附录关键接口-json-示例)

---

## 1. 背景与现状

### 1.1 现状盘点（代码级，已实测核对）

| 模块 | 已有什么 | 缺什么 |
|---|---|---|
| 微调训练 | 脚本：legacy `pytorch/trainer_model.py`（全参）、`loRA_model.py`（LoRA）；后端 `services/training.py`（TrainingService 后台线程任务）+ `runtimes/training_jobs.py`（full/lora 执行）+ `api/train.py`（start/status/stop 三个端点） | 无可用 UI；无进度/epoch/loss 上报；日志不流式；取消不可靠；产物不注册到模型列表；配置无模板；依赖数据集管理 |
| 数据集 | 无任何代码；训练脚本里写死 `load_dataset('json', data_files='...')` | 上传/列表/预览/删除/校验全缺；格式支持单一；无库表 |
| 知识库 | 后端 `services/knowledge_base.py`（上传/检索/统计/文档列表/删除方法齐备，但**内存存储**）；`api/knowledge.py` 只暴露 upload/query/stats 三个端点；客户端 `KnowledgeDialog`（上传+检索） | 无文档管理 API（documents/delete 在 service 层但没接路由）；无持久化（重启即丢）；无 RAG 问答（检索+LLM 生成）；无分块查看；无来源高亮联动 |

### 1.2 为什么现在做

1. 训练代码已就绪但**无法从界面使用**：用户无法选数据集、看不到进度、无法取消、训练完的模型不会出现在模型列表里。
2. 数据集是训练的**前置依赖**：没有数据集管理，训练表单就无法"选数据"。
3. 知识库目前只算"演示级"，要做成真实功能必须持久化 + 文档管理 + RAG 问答。

---

## 2. 目标与联动总览

### 2.1 三个功能、两条联动主线

```
  ┌────────────┐  1.选数据集    ┌──────────────┐  2.产物注册    ┌────────────┐
  │ 数据集管理  │ ────────────▶ │  微调训练     │ ────────────▶ │  模型列表   │
  │ DatasetPage│   (训练表单    │ TrainingPage │   (train_tasks│ ModelCenter │
  │  上传/预览  │    下拉选择)   │  配置+进度+日志│    完成自动/  │   可加载推理 │
  └────────────┘               └──────────────┘    手动注册)  └────────────┘
         │                           │                          │
         └──────────┬────────────────┘                          │
                    ▼                                           │
  ┌─────────────────────────┐           3.知识库检索/问答         │
  │       知识库管理         │ ──────────────────────────────────┼──▶ 聊天 / Agent
  │ KnowledgePage           │   (RAG: 上传→分块→向量→检索→LLM 回答) │   (knowledge_search 工具已就绪)
  │  文档管理/分块查看/问答    │                                  │
  └─────────────────────────┘                                  │
```

### 2.2 联动点清单

| # | 联动 | 机制 |
|---|---|---|
| 1 | 数据集 → 训练 | 训练表单的"数据集"下拉直接读 `GET /api/v1/datasets`；提交 `train/start` 时传 `dataset_id`，后端查库取文件路径 |
| 2 | 训练 → 模型列表 | 训练完成（或用户点"注册模型"）→ 写 `models` 表（provider=training, path=输出目录）→ 模型中心/聊天可选 |
| 3 | 知识库 → 聊天 | ChatPage 增加"启用知识库"开关：开启时走 `POST /api/v1/knowledge/answer`（检索+生成）或注入检索结果 |
| 4 | 知识库 → Agent | `web_search` 同级的 `knowledge_search` 工具已存在，接入全局 KB 即可用 |
| 5 | 知识库 → 训练（可选） | 训练数据集也可来自知识库文档导出（后续增强，本期不做） |

---

## 3. 数据库设计（新增/变更表）

在现有 `backend/app/models/records.py` 基础上新增 4 张表，全部带 user_id 隔离；引入 Alembic 生成首个基线迁移（或先沿用 create_all，见 5.7）。

### 3.1 datasets（数据集）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | |
| user_id | Integer FK users | 隔离 |
| name | String(200) | 用户命名，默认取文件名 |
| file_path | String(1024) | 服务端存储路径 |
| original_name | String(255) | 原始文件名 |
| format | String(20) | jsonl / csv / json / txt（自动识别） |
| row_count | Integer | 样本数 |
| file_size | Integer | 字节 |
| columns | Text(JSON) | 列名预览（csv/jsonl） |
| sample | Text(JSON) | 前 5 行预览快照 |
| status | String(20) | uploaded / parsed / error |
| error | Text | 解析失败原因 |
| created_at | DateTime | |

### 3.2 train_tasks（训练任务，持久化）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | |
| task_id | String(32) unique | 对外 ID（沿用现有 uuid） |
| user_id | Integer FK | |
| dataset_id | Integer FK datasets | 关联数据集 |
| base_model | String(255) | |
| method | String(10) | full / lora |
| config | Text(JSON) | 全部超参快照 |
| status | String(20) | pending / running / stopping / done / error |
| progress | Float | 0-100（按 epoch/step 估算） |
| current_epoch | Integer | |
| total_epochs | Integer | |
| loss | Float | 最近一次 loss |
| output_dir | String(1024) | 产物目录 |
| log_path | String(1024) | 日志文件路径 |
| error | Text | |
| created_at / updated_at | DateTime | |

### 3.3 knowledge_documents + knowledge_chunks（知识库持久化）

| 表 | 字段 | 说明 |
|---|---|---|
| knowledge_documents | id, user_id, filename, filetype, chunk_count, doc_meta(JSON), created_at | 文档索引 |
| knowledge_chunks | id, doc_id FK, chunk_index, content, embedding(BLOB, 可选), metadata(JSON) | 向量块（向量可存 BLOB 或每次重算） |

> 存储策略：文档少时（<200 块）向量**不落库、每次加载时重算**（TF-IDF 很快）；量大再启用 embedding BLOB / faiss-cpu。实现里做一个 `VectorIndex` 抽象，两种实现可切换。

### 3.4 变更说明

- `models` 表新增语义：`provider='training'` 表示训练产物，`path` 指向输出目录，`format='safetensors'（全参）/ 'peft-adapter'（LoRA）`。
- 索引：datasets(user_id, created_at)、train_tasks(user_id, created_at)、knowledge_documents(user_id)、knowledge_chunks(doc_id)。

---

## 4. 后端 API 设计

统一前缀 `/api/v1`，除注明外均需 Bearer Token。

### 4.1 数据集 /api/v1/datasets

| 方法与路径 | 功能 | 说明 |
|---|---|---|
| POST /api/v1/datasets/upload | 上传数据集 | multipart：file + name?；扩展名白名单 jsonl/csv/json/txt；大小上限（默认 200MB，`max_dataset_size` 配置）；上传后**同步解析**（小文件）或后台任务（大文件） |
| GET /api/v1/datasets | 数据集列表 | 返回 name/format/row_count/file_size/status/created_at |
| GET /api/v1/datasets/{id} | 详情+预览 | 返回 sample（前 5 行）+ columns |
| GET /api/v1/datasets/{id}/stats | 统计 | row_count、列类型分布、缺失值 |
| POST /api/v1/datasets/{id}/validate | 训练前预检 | 校验是否为可训练格式（文本列探测、最小行数） |
| DELETE /api/v1/datasets/{id} | 删除 | 删库记录+服务端文件 |

### 4.2 训练 /api/v1/train（增强）

| 方法与路径 | 功能 | 现状 → 目标 |
|---|---|---|
| POST /api/v1/train/start | 启动训练 | 已有 → 增加 dataset_id、配置模板校验；写 train_tasks 表 |
| GET /api/v1/train/status/{task_id} | 任务详情 | 已有 → 增加 progress/current_epoch/loss/log_tail |
| GET /api/v1/train/stream/{task_id} | **SSE 日志流** | 新增：实时推送日志行 + 进度事件 |
| POST /api/v1/train/stop/{task_id} | 停止 | 已有（标记）→ 子进程 terminate + 状态落库 |
| POST /api/v1/train/{task_id}/register-model | 注册产物 | 新增：训练产物 → models 表 |
| GET /api/v1/train/templates | 超参模板 | 新增：full / lora 两套默认配置，前端表单初始化 |
| GET /api/v1/train/tasks | 我的任务列表 | 新增 |

### 4.3 知识库 /api/v1/knowledge（增强）

| 方法与路径 | 功能 | 现状 → 目标 |
|---|---|---|
| POST /api/v1/knowledge/upload | 上传文档 | 已有 → 持久化到 knowledge_documents/chunks |
| GET /api/v1/knowledge/documents | 文档列表 | 新增路由（service 已有 documents()） |
| DELETE /api/v1/knowledge/documents/{filename} | 删除文档 | 新增路由（service 已有 delete_document()） |
| GET /api/v1/knowledge/documents/{filename}/chunks | 分块查看 | 新增 |
| POST /api/v1/knowledge/query | 检索 | 已有 → 返回带来源+分块索引 |
| POST /api/v1/knowledge/answer | **RAG 问答** | 新增：检索 top_k → 拼上下文 → 调 chat_service 生成 → 返回答案+引用 |
| GET /api/v1/knowledge/stats | 统计 | 已有 |
| POST /api/v1/knowledge/rebuild | 重建索引 | 新增（可选） |

### 4.4 联动相关（复用现有）

- `GET /api/v1/models`：训练产物注册后在此可见（provider=training）。
- Agent：`services/agent_tools.py` 的 `knowledge_search` 工具已接 `get_global_kb()`，KB 持久化后自动生效。

---

## 5. 后端实现方案（分模块）

### 5.1 services/dataset_service.py（新）

- **上传**：`UploadFile` → 存 `settings.data_dir/datasets/{user_id}/{uuid}_{name}`；扩展名白名单 + 大小限制（`max_dataset_size`）。
- **解析器**（`DatasetParser`）：
  - jsonl：逐行 `json.loads`，探测文本列（str 类型列），行数统计；
  - csv：`csv.DictReader` 探测表头与列；
  - json：`{"text": ...}` / `{"messages": [...]}` 两种结构适配（对齐 legacy `preprocess_function` 的"所有列拼文本"逻辑）；
  - txt：每行一条样本。
- **预览**：解析时缓存前 5 行到 `sample` 字段（JSON），详情接口直接返回。
- **校验**（validate）：行数 ≥ 1、存在可训练文本列、jsonl/json 可逐行解析，返回校验报告供前端预检。

### 5.2 services/training.py 增强

- `TrainTask` → 持久化：启动时写 `train_tasks` 表，状态/进度/loss 每次更新落库（短事务）。
- **进度上报**：训练在**子进程**执行（`multiprocessing` 或 `subprocess` 跑一个 `python -m modelforge_train --config ...` 入口），父进程轮询共享状态文件/队列；日志写 `log_path` 文件。
  - 理由：torch 训练无法安全地在 FastAPI 进程内跑（GIL/显存/取消），子进程隔离最稳，取消=terminate。
- **取消**：`stop` → 状态置 stopping → terminate 子进程 → 落库 error('stopped by user') 或 status='stopped'。
- **SSE 日志流**：`stream/{task_id}` 用 StreamingResponse 尾读 log 文件（`seek/tell` 增量），关闭连接即停止。
- **产物注册**：`register-model` → `ModelManager.install(name, provider='training', path=output_dir, ...)`；全参产物 `format='safetensors'`，LoRA 产物 `format='peft-adapter'`（加载时 base+adapter 组合，实现里注明）。
- **模板**：`templates` 返回 `{full: {...}, lora: {...}}` 默认超参（epochs=3, lr=2e-5, batch=2, lora_r=8, lora_alpha=32...）。

### 5.3 runtimes/training_jobs.py 重写

- 入口改为命令行可执行（`if __name__ == '__main__':` + argparse），供子进程调用；
- 支持 `dataset_id`：从 DB 取 `file_path` 后 `load_dataset`；
- 注册 `TrainerCallback`（`on_log`）把 loss/step 写入状态文件；
- 输出统一到 `outputs/{task_id}/`；训练结束自动写 `train_tasks.status=done`。

### 5.4 services/knowledge_base.py 持久化

- `KnowledgeBase` 增加 DB 后端：`upload` 时同时写 `knowledge_documents` + `knowledge_chunks`；启动时 `load_index()` 从库重建内存向量索引；
- `documents()/delete_document()` 改为走库（同时清理 chunks 与内存索引）；
- `answer(question, top_k)`：检索 → 拼接 `[知识库内容]...\n\n{问题}` → `chat_service.run_chat`（匿名）→ 返回 `{answer, sources: [{source, score, text}]}`。

### 5.5 api 层新增/增强

- 新增 `api/datasets.py`；增强 `api/train.py`（status 加字段、stream、register-model、templates、tasks）；增强 `api/knowledge.py`（documents/delete/chunks/answer/rebuild）；
- `main.py` 挂载 `datasets.router`；
- 上传与训练端点需要 `python-multipart`（已在 requirements.txt）。

### 5.6 配置项（config.yaml 新增）

```yaml
max_dataset_size: 209715200        # 200MB
dataset_dir: ./data/datasets
train_output_dir: ./outputs
train_max_workers: 1               # 同一时刻最多 1 个训练任务（显存安全）
kb_persist: true
```

### 5.7 数据库迁移策略

- 推荐：引入 Alembic，`alembic revision --autogenerate` 生成基线（含新增 4 张表）；CI 加 `alembic upgrade head` 校验。
- 过渡方案（若暂缓 Alembic）：`init_db()` 的 create_all 会自动建新表（旧表不动），兼容现有库；在计划中标注"下一里程碑补迁移"。

---

## 6. 客户端 UI 设计

在 `client/pyside6/pages/` 新增三个页面（QWidget，可嵌入主窗口标签页或独立对话框，建议做成**主窗口标签页**便于联动）。

### 6.1 DatasetPage（数据集管理）

- **上传区**：文件选择 + 名称输入 + 上传按钮；支持拖拽（可选）；提示支持格式。
- **数据集列表**（QTableWidget）：名称 / 格式 / 行数 / 大小 / 状态 / 时间；操作列：预览、校验、删除。
- **预览对话框**：前 5 行（csv/jsonl 用表格，txt 用文本）。
- **校验结果**：通过显示"可用于训练"，失败显示原因。

### 6.2 TrainingPage（微调训练）

- **左侧配置表单**（QFormLayout）：
  - 基础模型：下拉（来自模型列表）+ 手动输入 HF id；
  - 方法：单选 full / lora（切换时显示/隐藏 lora 参数组）；
  - **数据集**：下拉（来自 `GET /datasets`，联动 DatasetPage；显示"名称(行数)"）；无数据集时提示先去数据集页上传；
  - 超参：epochs / learning_rate / batch_size / lora_r / lora_alpha / 输出目录（默认 `./outputs`）；
  - "加载模板"按钮（full/lora）。
  - 启动按钮（启动前自动调 `validate`）。
- **右侧任务区**：
  - 我的任务列表（QTableWidget：任务 ID / 方法 / 数据集 / 状态 / 进度）；
  - 详情面板：进度条（progress）、epoch 计数、当前 loss、**日志滚动区**（SSE `train/stream` 实时追加）；
  - 操作：停止、训练完成后"注册到模型列表"（→ 刷新模型中心）。

### 6.3 KnowledgePage（知识库管理）

- **文档管理区**：上传按钮 + 文档列表（文件名 / 类型 / 分块数 / 时间）+ 删除 + "查看分块"。
- **检索测试区**：输入问题 → `/knowledge/query` → 结果列表（来源 + score + 文本高亮）。
- **RAG 问答区**：输入问题 → `/knowledge/answer` → 答案显示 + 引用来源列表。

### 6.4 主窗口导航

把三个页面接入主窗口：建议改成 `QTabWidget` 或左侧导航（聊天 / 模型 / 数据集 / 训练 / 知识库 / 设置），当前"工具"菜单里的对话框保留为快捷入口。

---

## 7. 页面联动设计

### 7.1 数据集 ↔ 训练
- TrainingPage 数据集下拉实时读 `GET /datasets`（含 DatasetPage 上传后的刷新信号）；
- 数据集删除时若有任务引用，提示确认（任务保留 dataset_path 快照，删除不中断已启动任务）。

### 7.2 训练 ↔ 模型列表
- 训练 done → TrainingPage 显示"注册到模型列表"按钮 → `POST train/{task_id}/register-model` → ModelCenter 下次打开可见 → ChatPage 可输入该模型名。
- （可选自动注册：`train_tasks` 配置 `auto_register=true`。）

### 7.3 知识库 ↔ 聊天 / Agent
- ChatPage 增加"知识库"开关：开 → 发送走 `POST /api/v1/knowledge/answer`（先检索再生成），关闭走普通 `/api/v1/chat`；
- Agent 的 `knowledge_search` 工具直接可用（同一全局 KB）；
- 知识库文档上传/删除后，聊天侧无需重启（共享 `get_global_kb()`）。

### 7.4 信号/刷新约定（客户端）
- 页面间用主窗口持有的单例 `ModelForgeClient` + Qt 信号（如 `datasets_changed`）触发刷新；
- 训练任务状态用 QTimer 轮询（2s，比 SSE 简单）或 SSE 流式二选一，本期建议：日志用 SSE，状态字段用轮询兜底。

---

## 8. 分阶段实施路线图

### Phase 1 —— 后端能力（约 1 周）

- [ ] 数据库新增 4 张表（+ Alembic 基线或 create_all 过渡）
- [ ] `dataset_service.py`：上传/解析/预览/校验/删除 + `api/datasets.py`
- [ ] `training.py` 增强：任务持久化、子进程执行、进度/loss 上报、取消、SSE 日志流、register-model、templates、tasks
- [ ] `training_jobs.py` 重写为可执行入口 + TrainerCallback
- [ ] 知识库持久化（documents/chunks 表 + 启动重建索引）+ `answer` 端点 + documents/delete/chunks 路由
- [ ] 配套单元/集成测试（mock torch，不真跑训练）
- **验证**：`pytest tests/` 全绿（新增 30+ 用例）；curl 走通 上传数据集 → 预检 → 启动任务（mock） → 状态 → 日志流 → 停止 → 注册模型

### Phase 2 —— 客户端三页面 + 联动（约 1 周）

- [ ] `pages/dataset_page.py`：上传/列表/预览/校验/删除
- [ ] `pages/training_page.py`：配置表单（数据集下拉联动）+ 任务列表 + 进度/loss + SSE 日志 + 停止 + 注册模型
- [ ] `pages/knowledge_page.py`：文档管理 + 检索 + RAG 问答
- [ ] 主窗口导航改造（标签页）+ ChatPage 知识库开关
- [ ] `api_client` 补齐 datasets/train-stream/knowledge 新端点
- **验证**：真实启动后端+客户端，无 GPU 用 CPU 小模型（如 Qwen2.5-0.5B 或 tiny）跑通一轮 LoRA：上传数据集 → 训练 → 看日志/进度 → 注册模型 → 模型中心可见

### Phase 3 —— 打磨与交付（3-5 天）

- [ ] 错误提示与边界（数据集损坏、磁盘不足、显存不足提示）
- [ ] 训练产物加载说明（LoRA adapter 与 base 模型组合）
- [ ] 文档更新（README/USAGE_GUIDE/TECHNICAL_REPORT 附录 C）
- [ ] CI 增加训练/知识库集成测试 job（标 slow 或 mock）
- **验证**：全流程演示可用；文档与实现一致

---

## 9. 测试计划与 CI

| 层 | 内容 | 说明 |
|---|---|---|
| 单元 | dataset_service 解析（jsonl/csv/json/txt 各造 1 个 fixture）；training 状态机（mock Trainer 子进程）；knowledge 持久化（upload→documents→chunks→delete） | 不依赖 torch |
| API 集成 | datasets CRUD、train start/status/stop（mock 执行器）、knowledge documents/delete/answer（mock 运行时） | httpx TestClient |
| 客户端 | api_client 新方法 mock 测试（沿用 phase6 风格） | |
| 端到端（slow） | 真实 CPU 小模型 lora 训练 1 个 epoch（用 100 行小数据集），验证"上传→训练→注册→加载"闭环 | 标 `@pytest.mark.slow`，默认跳过，CI 单独 job 可选 |

**CI**：
- 常规 job 不装 torch（沿用 requirements base/dev）；
- 新增 `integration-ai` job（可选手动触发）：装 requirements-ai，跑 slow 端到端。

---

## 10. 风险与注意事项

1. **训练进程隔离**：torch 训练必须子进程执行，禁止在 FastAPI 事件循环内跑（阻塞+不可取消）；取消靠 terminate，注意清理 GPU 显存。
2. **数据集安全**：扩展名白名单 + 大小限制 + 只解析文本；csv/json 解析加异常兜底，防止恶意/损坏文件拖垮进程。
3. **SQLite 并发**：训练子进程写状态、API 读 → 开启 WAL（`PRAGMA journal_mode=WAL`）+ 短事务；训练状态更新用"状态文件 + 定时落库"双通道，避免高频写库。
4. **peft/transformers 版本兼容**：`lora target_modules` 因模型而异（q_proj/v_proj 是 llama 系约定），配置里开放自定义；requirements-ai 锁版本。
5. **显存**：`train_max_workers=1` 强制串行；batch_size 默认小值；OOM 时捕获并提示调参。
6. **向量索引一致性**：知识库持久化后，chunks 与内存索引必须同步增删（封装在一个事务/方法里）；TF-IDF 词表变化时全量重建（文档量小，可接受）。
7. **LoRA 产物加载**：注册为 `peft-adapter` 时，加载需 base+adapter（`PeftModel.from_pretrained`），LocalRuntime 需支持该分支——在 Phase 3 一并实现并注明。

---

## 11. 附录：关键接口 JSON 示例

### POST /api/v1/datasets/upload（multipart）

```json
{
  "id": 1, "name": "ruozhiba_qa", "format": "jsonl",
  "row_count": 12034, "file_size": 2457600, "status": "parsed",
  "columns": ["question", "answer"],
  "sample": [{"question": "为什么天是蓝的", "answer": "..."}]
}
```

### POST /api/v1/train/start

```json
// 请求
{
  "dataset_id": 1,
  "base_model": "Qwen2.5-0.5B",
  "method": "lora",
  "epochs": 3, "learning_rate": 2e-5, "batch_size": 2,
  "lora_r": 8, "lora_alpha": 32, "output_dir": "./outputs"
}
```

```json
// 响应
{
  "task_id": "a1b2c3d4e5f6", "status": "running", "progress": 0,
  "current_epoch": 0, "total_epochs": 3, "loss": null, "log_path": "./outputs/a1b2c3d4e5f6/train.log"
}
```

### GET /api/v1/train/stream/{task_id}（SSE）

```text
data: {"type": "log", "data": "epoch 1/3 - loss: 1.2345"}
data: {"type": "progress", "data": {"progress": 33.3, "epoch": 1, "loss": 1.2345}}
data: {"type": "done", "data": {"task_id": "a1b2c3d4e5f6", "status": "done"}}
```

### POST /api/v1/knowledge/answer

```json
// 请求
{"question": "ModelForge 如何加载 GGUF 模型？", "top_k": 3}
```

```json
// 响应
{
  "answer": "在模型中心登记 GGUF 路径后即可加载...",
  "sources": [
    {"source": "usage_guide.md", "score": 0.87, "text": "GGUF 模型支持..."}
  ]
}
```

---

## 附录：实施状态（已按本计划全部执行）

> 本次已按 Phase 1 → 2 → 3 顺序执行完毕，全部功能已实现并有测试覆盖。

### ✅ Phase 1 —— 后端能力（已完成）
- 数据库：datasets / train_tasks / knowledge_documents / knowledge_chunks 四张新表（records.py）
- 数据集：DatasetParser（jsonl/csv/json/txt）+ DatasetService（上传/解析/预览/校验/删除）+ /api/v1/datasets/*（含 Form 名称参数、大小/扩展名校验）
- 训练：TrainingService 重写（任务持久化、子进程执行、状态轮询落库、停止=terminate）、training_jobs.py 重写为 CLI 入口 + TrainerCallback（进度/loss 上报）、SSE 日志流 /train/stream/{task_id}、register-model、templates、tasks
- 知识库：持久化（upload 写文档+分块，启动懒加载重建索引）+ documents/chunks/delete/answer（RAG 问答）路由
- 配置：config.yaml 新增 max_dataset_size/dataset_dir/train_output_dir/train_max_workers/kb_persist
- 测试：新增 20 个用例（数据集解析单测 + 训练流/知识库集成测试），全套 152 通过

### ✅ Phase 2 —— 客户端三页面 + 联动（已完成）
- DatasetPage（上传/列表/预览/训练预检/删除）
- TrainingPage（配置表单含数据集下拉联动、模板、任务列表、进度条/epoch/loss、日志轮询、停止、注册模型）
- KnowledgePage（文档管理/分块查看/仅检索/RAG 问答）
- 主窗口改为标签页：聊天 / 数据集 / 训练 / 知识库；聊天页增加"知识库(RAG)"开关（开启走 /knowledge/answer）

### ✅ Phase 3 —— 打磨（已完成）
- 实况验证：数据集上传（中文名/列探测/行数）、train templates、知识库上传/文档列表/检索全部通过
- 已知边界：训练真机执行需安装 requirements-ai.txt（torch/transformers/peft）；LoRA 产物（peft-adapter）加载需 base+adapter 组合，待真机验证
