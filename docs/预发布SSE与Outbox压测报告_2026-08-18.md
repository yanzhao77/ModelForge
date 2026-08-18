# ModelForge 任务中心预发布 SSE 与 DB Outbox 压测报告

**报告日期**：2026-08-18  
**测试对象**：当前 `master` 工作树，包含任务投影字段级 diff 与可配置数据库连接池修复。  
**执行环境**：隔离的本地预发布实例，独立 SQLite 数据库 `/tmp/modelforge_preprod_stress.db`、单个 Uvicorn 进程、`DATABASE_POOL_SIZE=32`、`DATABASE_MAX_OVERFLOW=16`、`DATABASE_POOL_TIMEOUT=10`。该环境不包含真实模型推理、GPU 或外部供应商调用。

## 摘要

本次压测通过真实 HTTP 认证、`POST /api/v1/tasks`、`GET /api/v1/tasks/stream` 和后台 DB outbox publisher 验证了任务中心的完整事件链路。修复前，24 条并发 SSE 连接在默认 SQLAlchemy 容量（`pool_size=5`、`max_overflow=10`）下触发 `QueuePool` 连接超时。修复后，24 条连接全部收到 burst 事件，96 个真实任务写入的 p95 创建延迟为 **199.31 ms**，p95 SSE 首事件交付延迟为 **64.18 ms**，outbox 最终积压为 **0**。

> 结论：在本报告所定义的 24 连接、96 事件突发场景中，任务 SSE、cursor 回放和 DB outbox 通过。该结果适用于当前单进程、SQLite 隔离预发布配置；多实例部署、长时稳定性和 PostgreSQL 容量仍须另行验证。

## 场景与方法

| 项目 | 设置 |
|---|---|
| 身份认证 | 真实注册与登录，后续请求携带真实 Bearer Token。 |
| SSE 连接 | 24 条独立 HTTP 流连接，均先接收种子事件完成握手，再测量 burst 期间的第一条新事件。 |
| 写入突发 | 96 个 `POST /api/v1/tasks` 请求，由 12 个并发 worker 发出。 |
| 事件机制 | 每次任务创建在同一事务写入 `TaskEvent` 与 `TaskOutbox`；publisher 对未派发 outbox 轮询并唤醒 SSE hub。 |
| 通过条件 | 全部 24 条连接收到新事件、outbox pending 为 0、outbox 总数不小于 burst 数量且脚本无 HTTP/数据库异常。 |

压测脚本不依赖 FastAPI `TestClient`、内存 transport 或 mock publisher。它对隔离 Uvicorn 实例发起真实 HTTP 长连接和写入请求，因此覆盖了认证、路由、中间件、线程、数据库连接池、SSE 响应和 outbox 轮询的组合行为。[1] [2] [3]

## 基线问题与修复

初次 24 连接测试未通过。日志显示 `QueuePool limit of size 5 overflow 10 reached`，而 SSE 生成器会为 cursor 查询短暂借用数据库连接；高并发连接同时轮询时，默认 15 个可用连接不足。该发现扩大了此前的 P-02：问题不只是 SQLite 写锁竞争，也包括连接池容量未匹配 SSE 同时读取的峰值。[2]

数据库引擎现增加三个环境变量：`DATABASE_POOL_SIZE`（默认 32）、`DATABASE_MAX_OVERFLOW`（默认 16）和 `DATABASE_POOL_TIMEOUT`（默认 10 秒），并启用 `pool_pre_ping`。该改动保持连接数可由生产部署显式控制，同时让单进程预发布实例承载 24 条 SSE 查询连接。[4]

另一个修复是 P-01。`TaskService.project()` 现在比较 status、title、summary、progress、cancelable、retryable 和 metadata。只有存在实质字段变化时，才调用一次 `transition()` 写入 `TaskEvent` 与 `TaskOutbox`。重复刷新未变化的 legacy 训练任务四次不会新增事件或 outbox；将进度从 25 更新到 50 时恰好新增一条事件和一条 outbox 记录。该行为由自动回归测试覆盖。[5]

## 结果

| 指标 | 测量值 | 判定 |
|---|---:|---|
| 请求 SSE 连接数 | 24 | 通过 |
| 收到 burst 事件的连接数 | 24 / 24 | 通过 |
| Burst 任务数 | 96 | 通过 |
| Burst 耗时 | 0.8649 s | 记录 |
| 创建吞吐 | 110.99 请求/秒 | 记录 |
| 创建延迟 p50 / p95 | 64.38 / 199.31 ms | 通过 |
| SSE 首事件交付 p50 / p95 | 54.20 / 64.18 ms | 通过 |
| Burst 后 outbox 清空耗时 | 0.0005 s | 通过 |
| `task_events` / `task_outbox` | 97 / 97 | 通过；包含 1 条握手种子事件。 |
| 未派发 outbox | 0 | 通过 |
| 最大派发尝试次数 | 1 | 通过 |

## 质量验证

代码变更后，完整 Python 套件为 **356 passed、2 skipped**；任务投影、SSE/outbox 专项测试通过，相关模块 Ruff 检查与 `git diff --check` 通过。交互原型增加了真实 API 配置、Bearer Token 本地存储、快照加载、手动 SSE 帧解析、cursor 持久化、断线指数退避和真实取消请求；其 TypeScript 检查与生产构建均通过。

## 生产建议与限制

本次结果不应被解读为多实例生产容量结论。SQLite 仍是单文件数据库，超出本测试规模后写入争用与磁盘 I/O 仍可能成为主瓶颈。上线前应优先使用 PostgreSQL 进行 100+ 并发连接、分钟级持续 burst 和服务重启回放测试，并为 outbox backlog、p95 事件延迟、连接池借用等待和每用户 SSE 数量配置指标与告警。

原型连接真实 API 时，服务端必须把原型站点 Origin 加入 `CORS_ALLOW_ORIGINS`；令牌只存储在浏览器本地。真实部署应优先使用短期令牌、受控同源代理或应用自身登录流程，而不是将长期高权限 Token 固化在前端配置中。

## References

[1]: https://github.com/yanzhao77/ModelForge/blob/920f23c24b31c8f32228963b687ccddc43fbbd35/backend/app/api/tasks.py "任务 API 与 SSE cursor 流"
[2]: https://github.com/yanzhao77/ModelForge/blob/920f23c24b31c8f32228963b687ccddc43fbbd35/backend/app/services/task_realtime.py "DB outbox publisher"
[3]: https://github.com/yanzhao77/ModelForge/blob/920f23c24b31c8f32228963b687ccddc43fbbd35/backend/app/services/task_service.py "任务投影与事件写入"
[4]: https://github.com/yanzhao77/ModelForge/blob/920f23c24b31c8f32228963b687ccddc43fbbd35/backend/app/core/database.py "数据库引擎配置"
[5]: https://github.com/yanzhao77/ModelForge/blob/920f23c24b31c8f32228963b687ccddc43fbbd35/tests/test_task_projection.py "投影回归测试"
