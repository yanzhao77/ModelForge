# 行为变更说明（2026-09-13）

> 范围：第三轮全项目复审判定并修复的缺陷，以及**使用者可感知**的语义变化。
> 纯内部重构、日志措辞与测试改动未列入。GUI/桌面端问题由另一处并行处理，不在本文范围。

本轮为后端与服务层修复，涉及 `backend/app/services/knowledge_base.py`、
`backend/app/api/knowledge.py`、`backend/app/services/runtimes/local_runtime.py`。

---

## 1. 知识库上传不再卡死整个服务（P0）

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| 切块循环必定推进 | 段落内最后一个空格落在重叠窗口之前时，`current` 切片原地不动 → 死循环 | 每轮至少消费一个字符；无法在重叠窗口内断句时按 `chunk_size` 硬切 |
| 段落合并计分隔符 | 合并两段的 chunk 可超出 `chunk_size` 两个字符（`\n\n` 未计入） | 分隔符计入上限，chunk 严格不超过 `chunk_size` |
| `chunk_overlap >= chunk_size` | 可再次导致循环不推进 | 构造时收敛到 `chunk_size - 1` 以内 |
| 空白 chunk | 纯空白切片也会进入索引 | 纯空白 chunk 不入库 |
| 上传执行位置 | `async def` 端点在事件循环线程内做解析、切块、向量化与提交 → 一个上传冻结全进程 | 上传在线程池执行，事件循环继续服务健康检查、任务流与取消 |

**触发条件（修复前）**：单段超过 500 字符、且最后一个空格位于前 450 字符内、其后无空格。
中文文档（`摘要: ` + 长中文段落）、PDF 提取文本极易命中。

**复现与验证**

| 场景 | 修复前 | 修复后 |
|---|---|---|
| `TextChunker().split("a " + "x"*1000)` | 挂死 | 3 个 chunk 返回 |
| 真实文件走 `KnowledgeBase().upload()`（2.7KB 中文 md） | 8 秒无返回、CPU 空转 | 立即返回 `ingested` |
| 隔离实例上传该文件后 `GET /healthz` | `ReadTimeout`（整个服务停止响应） | 上传期间 `healthz` 0.031s 返回 200 |
| 随机边界扫描（500 例，`chunk_size` 1–60、`overlap` 0–120、中英混排） | — | 无挂死、无超长、无空白 chunk |

## 2. 知识库不再把每个账户的正文留在进程里（P1）

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| 进程级单例的内存边界 | `_ensure_loaded` 把每个账户的 chunk 正文与向量追加进同一个 `vector_store` 且从不释放；账户越多内存越大，且第 N 个账户首次检索会重嵌全部累计语料 | 持久化内容只从数据库读取用于本次查询；单例只预热共享词表（上限 5 万） |
| 本地（无会话）模式 | 内存索引同时承载 DB 与本地文档，`query(db=None)` 可能读到其他账户的已加载内容 | 内存索引只服务本地模式；DB 模式与本地模式互不混用 |

**验证**：`tests/test_knowledge_memory_boundary.py` 断言 DB 查询后
`vector_store.documents == []`、两个账户各自检索仍命中且互不可见、本地模式上传/删除/统计保持原行为。

## 3. 检索质量下降改为可观测（P1）

| 变更 | 说明 |
|---|---|
| 词表上限 | 触达 `MAX_VOCAB` 时统计未能索引的词条并输出一次 WARNING；`stats()` 新增 `vocab_capped`、`vocab_dropped_terms` |
| 零命中提问 | 提问不含任何已索引词条时输出 WARNING（此前静默返回 0 条，看起来像"知识库里没有"） |
| 词表预热失败 | 数据库不可用时记录 WARNING 与堆栈，不再静默吞掉 |

## 4. 本地模型加载与推理不再冻结进程（P1）

| 变更 | 旧行为 | 新行为 |
|---|---|---|
| `LocalRuntime.load` | 在事件循环线程读取 GB 级权重并搬运到设备，加载期间全部端点无响应 | 在线程池执行；实例锁保证加载/卸载不会与生成并发改动模型 |
| `LocalRuntime.chat` | `.generate()` 与 GGUF 推理直接在事件循环线程执行，生成期间全进程冻结 | 在线程池执行 |
| `LocalRuntime.stop` | 释放显存同样阻塞事件循环 | 在线程池执行 |

## 5. 本轮未改动（明确排除）

1. 桌面客户端（关闭线程回收、异步请求代次等）——由另一处并行修复。
2. 多副本部署下的进程级状态（下载串行锁、资源租约、限流器）：当前部署边界仍为单副本。
3. provider 目标校验与 httpx 建连之间的 DNS-rebinding TOCTOU 窗口（需按部署环境做 IP 固定与活体测试）。
4. 训练、Agent Run、任务中心等其余 `async def` 端点中的轻量同步数据库调用（毫秒级，不构成长时间冻结）。

---

## 验证基线（2026-09-13）

| 验证项 | 命令 | 结果 |
|---|---|---|
| 新增回归用例 | `.venv\Scripts\python.exe -m pytest tests/test_knowledge_chunking.py tests/test_knowledge_upload_liveness.py tests/test_knowledge_memory_boundary.py tests/test_knowledge_vocab_cap.py tests/test_local_runtime_offload.py -q` | 18 passed |
| 知识库/运行时相关用例 | 上述 5 个文件并入 `test_local_runtime`、`test_model_loading_security`、`test_phase8_rag`、`test_knowledge_chinese_recall`、`test_knowledge_document_lifecycle`、`test_knowledge_tool_isolation` | 79 passed |
| 静态检查 | `ruff check backend client tests scripts`、`git diff --check` | 全绿 |
| 非 GUI 全量 | 忽略 8 个既知 GUI 文件的 `pytest tests/ -q` | 1029 passed / 4 skipped / 5 failed（见下） |

全量运行的 5 个失败均与本轮改动无关：

1. `tests/test_desktop_process_exit.py` × 4：并行进行中的桌面端修复新增的 GUI 探针用例，
   `subprocess` 用 `.venv`（Anaconda 基座）启动，`PySide6.QtCore` 在该解释器下 DLL 加载失败；
   属于另一处 GUI 工作范围。
2. `tests/test_scheduler_phase9.py::test_schedule_interval_fires_repeatedly`（以及单独复跑时的
   `test_runtime_scheduler_creates_run`）：0.05s 间隔时序断言。当时本机 CPU 占用 100%
   （两个窗口并行跑测试），实测 1.0s 内只触发 7 次。在干净 `HEAD`（`e319f50`）的独立
   `git worktree` 中复现出完全相同的 2 个失败，故与本次改动无关。
