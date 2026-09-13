# V1.1 → V2.0 测试报告

执行日期：2026-09-13（Asia/Shanghai）。

## 汇总

| 套件 | 命令 | 结果 |
|---|---|---|
| 后端全量（非 desktop/network/gpu/real_model） | `.venv\Scripts\python.exe -m pytest -q -m "not desktop and not network and not gpu and not real_model"` | **1183 passed, 1 skipped, 3 deselected**（306.66s） |
| 桌面端（离屏 Qt） | `.venv-gui\Scripts\python.exe -m pytest -q -m desktop` | **60 passed**（42.78s） |
| 静态检查 | `.venv\Scripts\python.exe -m ruff check .` | All checks passed |
| 路由统计 | `.venv\Scripts\python.exe scripts\api_route_stats.py --check` | 203 paths / 245 operations，README 已同步 |
| 平台基准 | `.venv\Scripts\python.exe scripts\benchmark_platform.py` | 见下 |

基线对比：本次路线开始前为 1111 后端 / 59 桌面；结束后 **+72 后端用例、+1 桌面用例**。

## 新增用例

| 版本 | 文件 | 用例数 |
|---|---|---|
| V1.1 | `tests/test_agent_definition_api.py` | 7 |
| V1.2 | `tests/test_multi_runtime.py` | 6 |
| V1.3 | `tests/test_multi_model_runtime.py` | 8 |
| V1.4 | `tests/test_knowledge_rag_v14.py` | 10 |
| V1.5 | `tests/test_workflow_engine.py`、`tests/test_workflow_api.py` | 8 + 6 |
| V1.6 | `tests/test_developer_platform.py` | 6 |
| V1.7 | `tests/test_packages_v17.py` | 5 |
| V1.8 | `tests/test_observability_v18.py` | 5 |
| V1.9 | `tests/test_hardening_v19.py` | 6 |
| V2.0 | `tests/test_platform_e2e.py` | 5 |
| 桌面 | `tests/test_desktop_model_runtime_pages.py`（新增工作流页面用例） | 1 |

## 基准（本机，仅供参考）

```text
model.register           72.81 ms
model.list                1.48 ms
model.refresh             2.90 ms
embedding.cold            9.33 ms
embedding.warm            3.90 ms
embedding.cache          64 entries / 256, hit_rate 见运行输出
workflow.sequential       1.38 ms
workflow.20_nodes         3.30 ms
recovery.pass           344.42 ms
```

## 过程中修复的真实缺陷

| 问题 | 影响 | 修复 |
|---|---|---|
| Agent 定义查找未按用户作用域 | 同名 Agent 时，另一个账号的 Run 可能命中错误定义 | `DBAgentStore.get(name, user_id)` 使用 `user_id = 调用者 OR 全局` |
| Agent Run 推理租约在终态之后才释放 | 客户端看到 `COMPLETED` 后立刻发起下一次运行偶发 `RUNTIME_BUSY` | 运行进入终态时立即释放租约 |
| 启动恢复扫描模型根目录会创建全局模型记录 | 多账号下共享目录中的模型对所有账号可见 | 恢复只校验既有记录，发现新文件仍是用户显式 `POST /models/scan` |
| 本地模型无原生 tool 通道 | Agent 无法在 GGUF 上调用工具 | JSON 信封协议（注入 + 解析，`services/tool_call_parser.py`） |

## 已知限制

1. TTFT 未采集（接口显式返回 `null` + 原因）；
2. 向量检索默认是词袋相似度，真实语义向量需注册 `EMBEDDING` 模型并安装 AI 依赖；
3. LoRA Adapter 仍不做 Base + Adapter 挂载；
4. 工作流暂无可视化节点编辑器；
5. 资源采样在缺少 `psutil`/`torch` 时报告 unknown 而不是估算值。
