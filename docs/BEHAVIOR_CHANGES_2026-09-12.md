# 行为变更说明（2026-09-12）

> 范围：本轮 bug 修复中**使用者可感知**的语义变化。每条都附了验证方式与提交号，
> 便于回溯。纯内部重构、日志措辞与测试改动未列入。

**验证基线：** 全量非 GUI 套件 `1000 passed / 0 failed / 4 skipped`；
`ruff check backend client tests scripts` 全绿；工作区与 `origin/master` 一致。

---

## 1. 模型下载

| 变更 | 旧行为 | 新行为 | 提交 |
|---|---|---|---|
| 暂停不再占用下载槽 | 暂停的 worker 原地等待 resume，同时持有全局下载槽；暂停两个后所有新下载永久排队 | 暂停让 worker 退出并归还槽位；"继续"按磁盘已有字节续传 | `92912be` |
| "重新开始"不再删文件 | `restart` 删除整个共享模型目录 | 只清除校验标记，重新做长度/SHA256 校验，仅补损坏或缺失部分 | `0a8ea2a` |
| 断点续传拒绝错误偏移 | 上游 206 若起始偏移不符，仍会 append 到本地文件 | 丢弃该残缺文件并整份重下 | `0a8ea2a` |
| 损坏的整长文件自动重下 | 校验失败直接标记任务 FAILED | 同一次运行内丢弃并重下 | `0a8ea2a` |
| 重启后任务不再假运行 | 重启后任务永远停在 RUNNING，取消也永久挂起 | 启动对账：无执行器的活跃任务置 PAUSED（可继续），重启前的取消请求置 CANCELLED | `0a8ea2a` |

同一物理模型目录被同一仓库的多个任务共享，本进程内按目录串行写入，清单改为原子落盘。

## 2. 推理与训练：单账户占用

| 变更 | 说明 |
|---|---|
| 同时只允许一个账户占用推理 | 占用从"启动/首次使用"开始保持到该账户停止；其他账户请求返回 `409 RUNTIME_BUSY`，消息中带占用者用户名 |
| 同时只允许一个账户训练 | 训练启动即占用，结束/停止/失败后释放；冲突返回 `409 TRAINING_BUSY` |
| 覆盖范围 | `/runtime/start`、`/chat`、`/chat/stream`、`/v1/chat/completions`、`/runtime/chat`、`/knowledge/answer`、Agent Run 执行期 |
| 纯聊天不永久占机 | 没有显式加载模型时，占用只在单次请求期间持有 |
| Agent Run | 执行期间（含等待人工审批）持有占用；拿不到占用时该 Run 以 `RUNTIME_BUSY` 结束并写明原因 |

提交：`f20e8f8`、`cf5a74c`、`b01e1ff`。

## 3. 任务中心

| 变更 | 旧行为 | 新行为 | 提交 |
|---|---|---|---|
| 取消直达执行器 | 只把任务行改成 `CANCEL_REQUESTED`，Agent 运行与训练子进程继续跑 | 训练 → 终止子进程；Agent Run → 取消运行；任务行收敛为 `CANCELLED` | `e879faf` |
| 排队任务可取消 | `QUEUED → CANCEL_REQUESTED` 被判定非法，返回 400 | 允许取消；无执行器的任务直接落为 `CANCELLED`，下载仍由 worker 确认 | `e700c05` |
| Agent 运行重试可执行 | 重试派发必定失败（`RETRY_DISPATCH_FAILED / no running event loop`） | 重试在请求事件循环上创建并执行新 Run | `4d5b5ac` |

## 4. 认证与安全

| 变更 | 说明 | 提交 |
|---|---|---|
| 改密码使旧 token 失效 | token 绑定当前口令指纹，改密（或哈希升级）后此前签发的 token 立即 401；升级后需重新登录一次 | `292bd5a` |
| Cookie 会话需要 CSRF nonce | 不再只保护 `/api/v1/`：`/v1/*` 的写请求同样要求 `X-CSRF-Token`（Bearer 客户端不受影响） | `0a0e90f` |
| 本地密钥文件权限 | `data/.dev_jwt_secret` 与 `data/.remote_provider_fernet.key` 在 Windows 上用 ACL 收紧到当前账户（此前仅 chmod，Windows 无效） | `2e225f8`、`fd33e27` |
| 脱敏覆盖裸密钥 | `sk-` / `hf_` / `ghp_` / `github_pat_` / `AKIA` / `xox*` / `AIza` / JWT 以及 JSON 引号键值都会脱敏 | `84e57e8` |
| 登录限流有界 | 探测不再分配内存，失败记录上限 10,000 条并淘汰过期项 | `92b3dd3` |
| 插件列表需鉴权 | `GET /api/v1/plugins` 由匿名可读改为 runtime admin | `6b39e2e` |

## 5. 对话、知识库与其他

| 变更 | 旧行为 | 新行为 | 提交 |
|---|---|---|---|
| 上下文窗口取最近消息 | 取对话最早的 50 条，长对话会"忘记刚才说的" | 取最近 50 条（时间正序） | `66cfb09` |
| 记忆检索 | 整段中文被当成一个检索词，句子含关键词也召回失败 | 中文按重叠二元组检索，记忆能真正进入下一轮上下文 | `77d0552` |
| 同名知识文档重传 | 留下多份记录，`chunks` 显示旧版本，删除删不掉 | 重传即替换；删除清理该文件名全部记录 | `94e5a38` |
| 数据集解析内存 | 每行都进内存（实测约 6.5 倍文件大小） | 流式计数，只保留 5 行样本 | `38c9c72` |
| 模型指标 | 每小时首个请求的指标被静默丢弃 | 计数器显式初始化，指标正常落库 | `66fee5e` |
| Web 搜索缓存 | 一次失败会被缓存，同一查询永久搜不到 | 只缓存成功结果 | `7275883` |
| 错误契约 | 知识库/数据集把原始异常文本放进 `detail` | 统一 `{code, message, correlation_id}` + `X-Correlation-ID` | `f079269` |

## 6. 启动对账（重启残留）

内存态执行器随进程消亡，以下记录在启动时统一结算，避免客户端长期显示"不会结束"的任务：

| 记录 | 结算结果 |
|---|---|
| `DownloadTaskRecord`（PENDING/RUNNING/PAUSED） | PAUSED（可继续）；重启前已请求取消的置 CANCELLED |
| `TrainTask`（pending/starting/running） | error +「训练进程随服务重启中断」 |
| `ApiInvocation`（PENDING/RUNNING） | FAILED / `PROCESS_RESTARTED`，释放预留额度与并发槽 |
| `AgentRun`（非终态） | FAILED / `PROCESS_RESTARTED` |

提交：`2e225f8` 之前的训练对账、`45d5093`、`bdb06c9`、`45d5093` 之后的 Run 对账。

## 7. 仍然存在的已知边界

这些是设计边界或环境限制，不是本轮修复范围内的 bug：

1. 7 个桌面 GUI 测试文件在本机因 Anaconda + PySide6 DLL 冲突无法运行，由 ubuntu CI 覆盖；Windows 未纳入 CI。
2. 多副本部署：下载串行锁、资源租约、限流器均为进程级状态；当前部署边界为单副本（见 `docs/SERVER_DEPLOYMENT.md`）。
3. provider 目标校验与 httpx 建连之间存在 DNS-rebinding TOCTOU 窗口（审计已记录，需按部署环境做 IP 固定与活体测试）。
4. `scripts/` 与一次性 UI 验证脚本是否纳入 Ruff 范围仍待决策。
