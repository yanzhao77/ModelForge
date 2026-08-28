# ModelForge 服务端部署说明

本文定义了 **本地单用户档** 与 **私有化服务端档** 的运行边界。SQLite 继续仅支持可信单用户、本机访问与单进程运行。任何多用户、网络可达或多副本部署必须使用 PostgreSQL，并通过 Alembic 管理模式版本。

## 环境变量

| 变量 | 本地单用户档 | 服务端档 |
|---|---|---|
| `DATABASE_PATH` | 可选；SQLite 文件路径 | 不使用 |
| `DATABASE_URL` | 不设置 | 必填；`postgresql+psycopg://...` |
| `JWT_SECRET` | 开发环境可使用本地值 | 必填；至少 32 个高熵字符 |
| `CORS_ALLOW_ORIGINS` | 明确的本地前端来源 | 必填；明确的 HTTPS 来源，逗号分隔 |
| `RUNTIME_ADMIN_USERNAMES` | 可选 | 必填；以逗号分隔的运维管理员账号 |

> 服务端启动会验证 `alembic_version` 是否存在。若未迁移，应用会拒绝启动，而不会在生产库中隐式执行 `create_all`。

## 服务端启动顺序

先复制环境示例并填入密钥。随后执行：

```bash
docker compose -f docker-compose.server.yml up --build
```

编排会等待 PostgreSQL 健康检查完成，再由一次性 `migrate` 服务执行 `alembic upgrade head`，最后启动非 root 的 `app` 服务。部署前应在 CI 或预发布环境执行 `alembic -c alembic.ini upgrade head` 与应用 `/healthz` 冒烟检查。

## 迁移治理

Alembic 基线版本为 `0001_server_baseline`。新的服务端模式变更应通过 `alembic revision --autogenerate -m "..."` 生成候选迁移，经人工审查后提交。每个迁移必须在空 PostgreSQL 数据库、已升级数据库及回滚演练中验证。SQLite 的增量升级仍由 `core.database._MIGRATIONS` 管理；同一功能的两类迁移应在同一变更中声明兼容策略。

## 可观测性与运行限制

SSE 以数据库持久化 cursor 为权威状态，单进程内事件通知仅用于加速唤醒。下载任务、任务中心、Agent Run 与调度任务均应以持久化记录作为查询来源。未接入外部队列前，服务端部署必须保持单应用副本；扩展为多副本前应实现并验证外部任务队列和事件通知适配器。
