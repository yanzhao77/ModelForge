# ModelForge V3.1 → V4.0 Master Development Plan

## 1. 总目标

在已经完成 V1.1 → V2.0 的基础上，将 ModelForge 从 Local AI Platform 演进为 AI Agent Operating System。

路线：

```text
V2.0
 ↓
V3.1 Multi-Agent Team
 ↓
V3.2 Agent Marketplace
 ↓
V3.3 Agent Learning
 ↓
V3.4 Autonomous Agent
 ↓
V4.0 AI Operating System
```

最终：

```text
Model OS + Agent OS + Knowledge OS + Task OS + Developer Platform + Marketplace
```

---

# 2. 总体原则

1. 不推倒 V2.0，优先复用现有 Model Registry、Runtime、Agent、Tool、Memory、RAG、Workflow、Training、API、SDK、Plugin、Package、Evaluation、Observability、Security。
2. 所有跨模块关联使用稳定 ID，例如 `model_id`、`agent_id`、`team_id`、`task_id`、`run_id`、`goal_id`、`experience_id`。
3. Agent 不得直接实例化 llama.cpp/Transformers，必须经过统一 Runtime。
4. 所有后台执行统一进入 Task OS。
5. 所有高风险 Tool/Agent 行为必须经过 Permission。
6. 每个版本都必须完成 Backend → API → UI → Test → Documentation → E2E。
7. 新功能优先增量实现，禁止无必要的大范围重构。

---

# 3. V3.1 — Multi-Agent Team

## 目标

从单 Agent：

```text
User → Agent → Result
```

升级为：

```text
User
 ↓
Manager Agent
 ├── Research Agent
 ├── Coding Agent
 ├── Testing Agent
 ├── Reviewer Agent
 └── Writer Agent
```

## 3.1 数据模型

新增：

- `AgentTeam`
- `AgentTeamMember`
- `AgentDelegation`
- `AgentTeamTask`
- `AgentTeamRun`
- `AgentTeamMessage`
- `AgentTeamEvent`

`AgentTeam` 至少包含：

```text
id
name
description
manager_agent_id
strategy
max_concurrency
timeout
retry_policy
shared_memory_id
permission_policy_id
created_at
updated_at
```

成员角色：

```text
MANAGER
RESEARCHER
CODER
TESTER
REVIEWER
WRITER
SPECIALIST
```

## 3.2 Team Strategy

支持：

```text
SEQUENTIAL
PARALLEL
PIPELINE
HIERARCHICAL
DELEGATION
CONSENSUS
```

## 3.3 Agent Delegation

实现：

```http
POST /api/v1/agents/{agent_id}/delegate
GET /api/v1/agent-tasks/{task_id}
POST /api/v1/agent-tasks/{task_id}/cancel
```

流程：

```text
Manager
 ↓
分析任务
 ↓
选择 Agent
 ↓
创建 AgentTask
 ↓
Member Agent
 ↓
Execute
 ↓
Result
 ↓
Manager
```

## 3.4 Agent Communication

支持：

```text
REQUEST
RESPONSE
RESULT
ERROR
STATUS
HANDOFF
CANCEL
```

消息包含：

```text
message_id
team_id
run_id
task_id
from_agent_id
to_agent_id
message_type
content
created_at
```

## 3.5 Shared Memory

形成：

```text
User Memory
 ↓
Project Memory
 ↓
Team Memory
 ↓
Agent Memory
 ↓
Task Memory
```

必须进行权限隔离。

## 3.6 UI

新增：

```text
Agent Teams
Team Detail
Team Builder
Team Run
Team Trace
```

支持可视化 Agent 拓扑、运行状态、任务、Tool、Memory、Trace。

## 3.7 验收

完成：

```text
Manager
 ↓
Researcher
 ↓
Coder
 ↓
Tester
 ↓
Reviewer
 ↓
Final Result
```

并能查看完整 Team Trace。

---

# 4. V3.2 — Agent Marketplace

## 目标

将 V2.0 Package System 升级为 AI Marketplace。

支持：

```text
Agent
Agent Team
Workflow
Tool
Knowledge Pack
Prompt Pack
```

## 4.1 统一 Package

支持：

```text
Model Package
Agent Package
Team Package
Workflow Package
Tool Package
Knowledge Package
```

统一 Manifest。

## 4.2 Agent Manifest

示例：

```yaml
id: python-coding-agent
name: Python Coding Agent
version: 1.0.0
type: agent

model:
  capabilities:
    - chat
    - tool_calling

tools:
  - file_read
  - file_search
  - python
  - shell

memory:
  enabled: true

permissions:
  - filesystem.read
  - process.execute
```

## 4.3 Marketplace Backend

实现：

```text
Marketplace Service
Package Registry
Package Resolver
Dependency Resolver
Package Installer
Package Updater
Package Security Scanner
```

支持：

```text
搜索
分类
详情
版本
安装
更新
卸载
依赖
兼容性
评分
评论
```

## 4.4 安全

安装流程：

```text
Package
 ↓
Manifest Validation
 ↓
Dependency Check
 ↓
Permission Review
 ↓
Signature Check
 ↓
Security Scan
 ↓
Install
```

重点检查：

```text
恶意脚本
路径穿越
危险 Shell
SSRF
凭据读取
Prompt Injection
恶意 Plugin
依赖污染
```

## 4.5 UI

页面：

```text
Marketplace
├── Featured
├── Agents
├── Teams
├── Workflows
├── Tools
├── Knowledge
├── Installed
└── Updates
```

安装前必须显示权限和依赖。

## 4.6 验收

完成：

```text
ModelForge A
 ↓
创建 Agent
 ↓
Package
 ↓
发布

ModelForge B
 ↓
搜索
 ↓
安装
 ↓
运行
```

---

# 5. V3.3 — Agent Learning

## 目标

从：

```text
每次任务都从零开始
```

升级为：

```text
历史经验
 ↓
当前任务
 ↓
策略选择
 ↓
执行
 ↓
评估
 ↓
新经验
```

## 5.1 Experience System

新增：

```text
AgentExperience
ExperienceEpisode
ExperienceStep
ExperienceOutcome
ExperienceEvaluation
```

Experience 至少记录：

```text
experience_id
agent_id
task_id
goal
context
strategy
steps
tools
result
outcome
score
failure_reason
reflection
created_at
```

## 5.2 Experience Pipeline

```text
Task
 ↓
Agent
 ↓
Execution
 ↓
Evaluation
 ↓
Reflection
 ↓
Experience
 ↓
Memory
```

## 5.3 Success / Failure Learning

支持：

```text
SUCCESS
FAILURE
PARTIAL_SUCCESS
```

失败经验必须记录失败原因和应该避免的策略。

## 5.4 Reflection Engine

输出：

```text
What worked?
What failed?
Why?
What should change?
What should be remembered?
```

Reflection 不得直接修改系统代码。

## 5.5 Experience Retrieval

```text
Current Task
 ↓
Embedding
 ↓
Experience Search
 ↓
Rank
 ↓
Context
 ↓
Agent
```

优先选择：

```text
相似任务
高成功率
高评分
近期经验
项目相关经验
```

## 5.6 Evaluation

指标：

```text
Task Success Rate
Tool Success Rate
Quality Score
Latency
Cost
Error Rate
Human Rating
```

## 5.7 Learning Policy

第一阶段只允许：

```text
Experience Learning
Memory Learning
Strategy Recommendation
```

禁止自动：

```text
修改系统代码
修改权限
自动发布 Package
自动修改核心 Prompt
自动训练模型
```

## 5.8 验收

连续执行相似任务，必须通过 Trace 证明历史经验真正影响后续策略。

---

# 6. V3.4 — Autonomous Agent

## 目标

从：

```text
User → Agent → Result
```

升级为：

```text
Goal
 ↓
Observe
 ↓
Plan
 ↓
Execute
 ↓
Evaluate
 ↓
Reflect
 ↓
Learn
 ↓
Repeat
```

## 6.1 Goal System

新增：

```text
Goal
SubGoal
Objective
Constraint
SuccessCriteria
```

Goal 至少包含：

```text
goal_id
agent_id
title
description
priority
deadline
constraints
success_criteria
status
created_at
updated_at
```

## 6.2 Goal Decomposition

例如：

```text
Goal
 ↓
分析项目
 ↓
检查依赖
 ↓
制定方案
 ↓
修改代码
 ↓
测试
 ↓
修复
 ↓
Reviewer
 ↓
完成
```

## 6.3 Autonomous Loop

```text
Observe
 ↓
Understand
 ↓
Plan
 ↓
Execute
 ↓
Evaluate
 ↓
Reflect
 ↓
Learn
 ↓
Observe
```

支持：

```text
暂停
恢复
取消
重试
回滚
超时
人工接管
```

## 6.4 Planning Engine

支持：

```text
Goal Decomposition
Task Planning
Dependency Resolution
Priority
Deadline
Retry
Rollback
```

## 6.5 Scheduler

支持：

```text
一次性
周期性
Cron
事件触发
Webhook
条件触发
```

## 6.6 Trigger System

支持：

```text
TIME_TRIGGER
EVENT_TRIGGER
FILE_TRIGGER
WEBHOOK_TRIGGER
TASK_TRIGGER
AGENT_TRIGGER
```

## 6.7 Autonomous Permission

风险等级：

```text
LOW
MEDIUM
HIGH
CRITICAL
```

例如：

```text
读取文件 → LOW
搜索代码 → LOW
修改代码 → MEDIUM
删除文件 → HIGH
执行 Shell → HIGH
发布软件 → CRITICAL
支付 → CRITICAL
```

规则：

```text
LOW → 自动
MEDIUM → 可配置
HIGH → 默认确认
CRITICAL → 强制 Human Approval
```

## 6.8 Human-in-the-Loop

新增：

```text
ApprovalRequest
ApprovalPolicy
ApprovalDecision
```

流程：

```text
Agent
 ↓
高风险操作
 ↓
Approval Request
 ↓
User
 ├── Approve
 ├── Reject
 └── Modify
 ↓
Continue
```

## 6.9 UI

新增：

```text
Autonomous Agents
Goals
Tasks
Approvals
Schedules
Agent Activity
```

## 6.10 验收

完成长期任务：

```text
创建 Goal
 ↓
Scheduler
 ↓
Research Agent
 ↓
Tools
 ↓
Knowledge
 ↓
Reviewer
 ↓
Writer
 ↓
Evaluation
 ↓
Experience
 ↓
Report
 ↓
Notification
 ↓
等待下一周期
```

用户无需每次重新输入任务。

---

# 7. V4.0 — AI Operating System

## 目标

V4.0 不是继续堆功能，而是统一架构。

定位：

> ModelForge = AI Model + Agent + Task + Knowledge + Tool + Workflow + Event 的统一操作系统。

---

# 8. V4.0 Core Objects

统一核心对象：

```text
Resource
Process
Task
Agent
Model
Tool
Knowledge
Event
Goal
Package
```

---

# 9. Resource OS

统一管理：

```text
Model
Runtime
Agent
Tool
Knowledge
Workflow
Package
```

Resource：

```text
resource_id
type
owner
permissions
status
metadata
created_at
updated_at
```

---

# 10. Process OS

统一执行：

```text
Agent Run
Workflow Run
Training
Evaluation
Autonomous Goal
Team Run
```

统一：

```text
Process ID
Status
Priority
Resource
Runtime
Logs
Trace
Cancel
Pause
Resume
```

---

# 11. Task OS

统一：

```text
Task
 ↓
Queue
 ↓
Scheduler
 ↓
Worker
 ↓
Runtime
 ↓
Result
```

支持：

```text
Priority
Concurrency
Retry
Timeout
Dependency
Cancellation
Pause
Resume
Dead Letter Queue
```

---

# 12. Event OS

统一 Event Bus。

事件包括：

```text
model.loaded
model.unloaded
agent.started
agent.completed
agent.failed
team.started
team.completed
task.created
task.completed
task.failed
workflow.completed
training.completed
evaluation.completed
package.installed
goal.created
goal.completed
```

---

# 13. Event Rule Engine

```text
Event
 ↓
Rule
 ↓
Condition
 ↓
Action
```

例如：

```text
training.completed
 ↓
Evaluation
 ↓
score > threshold
 ↓
Register Model
 ↓
Deploy Runtime
```

---

# 14. AI Resource Scheduler

统一调度：

```text
CPU
RAM
GPU
VRAM
Disk
Runtime
Model
Agent
Task
```

根据：

```text
Priority
Resource Availability
Model Capability
Agent Requirement
Task Deadline
Cost
```

进行调度。

---

# 15. Agent OS

最终 Agent 具备：

```text
Identity
Memory
Goals
Skills
Tools
Permissions
Experience
Schedule
Knowledge
Team
Runtime
```

生命周期：

```text
CREATE
INSTALL
CONFIGURE
RUN
PAUSE
LEARN
SLEEP
RESUME
UPDATE
ARCHIVE
DELETE
```

Agent 不再只是 Prompt，而是完整系统资源。

---

# 16. Agent Skill System

建立：

```text
Skill
 ├── Tools
 ├── Prompt
 ├── Knowledge
 ├── Workflow
 └── Evaluation
```

例如：

```text
Python Development Skill
```

包含：

```text
file_search
file_read
python
shell
pytest
Git
```

---

# 17. Marketplace V4

升级为：

```text
AI Marketplace
```

提供：

```text
Models
Agents
Agent Teams
Skills
Tools
Workflows
Knowledge
Plugins
```

安装 Agent 时自动解决：

```text
Model Dependency
Tool Dependency
Knowledge Dependency
Skill Dependency
Runtime Dependency
```

---

# 18. Knowledge OS

统一：

```text
Documents
Chunks
Embeddings
Knowledge Base
RAG
Graph
Memory
Experience
```

关系：

```text
Knowledge
 ├── Document
 ├── Chunk
 ├── Entity
 ├── Relation
 ├── Memory
 └── Experience
```

---

# 19. Unified Context Engine

建立统一 Context Engine。

输入：

```text
User Context
Project Context
Task Context
Knowledge
Memory
Experience
Tool Result
Team Context
```

输出：

```text
Optimized Context
```

再交给 Runtime。

---

# 20. Developer Platform V4

提供统一 API：

```http
/v1/models
/v1/chat/completions
/v1/embeddings

/v1/agents
/v1/agent-runs

/v1/teams
/v1/team-runs

/v1/tasks
/v1/goals

/v1/tools
/v1/skills

/v1/knowledge

/v1/workflows

/v1/events
```

同时提供：

```text
Python SDK
TypeScript SDK
CLI
Webhook
Plugin API
```

---

# 21. CLI

实现：

```bash
modelforge model list
modelforge model load

modelforge agent list
modelforge agent run

modelforge team list
modelforge team run

modelforge task list

modelforge goal create

modelforge workflow run

modelforge marketplace search
modelforge marketplace install
```

---

# 22. V4 Dashboard

首页统一展示：

```text
Models
Agents
Teams
Tasks
Running
Goals
Knowledge
```

同时显示：

```text
Active Agents
Recent Activity
Task Queue
Runtime Status
Resource Usage
Approvals
```

---

# 23. V4 System Monitor

监控：

```text
CPU
RAM
GPU
VRAM
Disk
Runtime
Agent
Task
Queue
Tool
Network
```

指标：

```text
Throughput
Latency
TTFT
Tokens/sec
Task Success Rate
Agent Success Rate
Tool Error Rate
Queue Time
Runtime Load Time
```

---

# 24. V4 Security

必须具备：

```text
Authentication
Authorization
RBAC
Resource Permission
Agent Permission
Tool Permission
Package Permission
Secret Management
Audit Log
Sandbox
Network Policy
Filesystem Policy
Process Policy
```

防御：

```text
Prompt Injection
Tool Injection
Command Injection
Path Traversal
SSRF
Secret Leakage
Malicious Package
Privilege Escalation
Agent Loop
Resource Exhaustion
```

---

# 25. Agent Loop Protection

必须限制：

```text
Max Steps
Max Runtime
Max Tool Calls
Max Tokens
Max Cost
Max Retries
Max Delegation Depth
```

超过限制进入：

```text
PAUSED
```

等待用户处理。

---

# 26. Reliability

V4 必须支持：

```text
Crash Recovery
Task Recovery
Agent Recovery
Runtime Recovery
Queue Recovery
Scheduler Recovery
State Recovery
```

重启流程：

```text
Persistent State
 ↓
Scheduler Recovery
 ↓
Task Recovery
 ↓
Agent Recovery
 ↓
Runtime Check
 ↓
Continue
```

---

# 27. Database

所有新版本必须：

```text
Migration
Rollback
Index
Constraint
Data Validation
```

禁止无迁移直接修改已有结构。

---

# 28. 测试体系

每个版本至少：

```text
Unit Test
Integration Test
API Test
Runtime Test
Agent Test
Security Test
UI Test
E2E Test
Recovery Test
```

Multi-Agent：

```text
Sequential
Parallel
Delegation
Failure
Retry
Timeout
Cancellation
Memory Isolation
Permission
```

Marketplace：

```text
Install
Update
Remove
Dependency
Conflict
Permission
Signature
Security Scan
Rollback
```

Learning：

```text
Experience Save
Search
Ranking
Reflection
Evaluation
Memory Injection
Isolation
```

Autonomous：

```text
Goal
Planning
Execution
Retry
Loop
Timeout
Approval
Pause
Resume
Cancel
Recovery
```

---

# 29. 固定开发流程

每个版本严格执行：

```text
1. 阅读现有代码
2. Architecture Review
3. Database Design
4. Service Layer
5. API
6. UI
7. Integration
8. Tests
9. Security Review
10. Documentation
11. E2E
12. Release
```

Codex 开发时必须：

```text
先检查现有实现
先搜索是否已有类似能力
优先复用
禁止重复造轮子
禁止无必要删除已有能力
禁止无必要大范围重构
```

---

# 30. Definition of Done

任何功能必须同时满足：

```text
[ ] Backend
[ ] Database Migration
[ ] API
[ ] Frontend UI
[ ] Permission
[ ] Error Handling
[ ] Logging
[ ] Trace
[ ] Unit Test
[ ] Integration Test
[ ] E2E Test
[ ] Documentation
[ ] Regression
```

---

# 31. 版本完成顺序

严格：

```text
V3.1
 ↓
Multi-Agent Team
 ↓
完整测试
 ↓
Release

V3.2
 ↓
Marketplace
 ↓
完整测试
 ↓
Release

V3.3
 ↓
Agent Learning
 ↓
完整测试
 ↓
Release

V3.4
 ↓
Autonomous Agent
 ↓
完整测试
 ↓
Release

V4.0
 ↓
AI Operating System
 ↓
系统级整合
 ↓
完整测试
 ↓
Release
```

不要跨版本并行开发核心架构。

---

# 32. 最终 V4.0 验收场景

必须支持：

```text
用户：

“建立一个长期运行的 AI Research Team，
每周自动研究指定领域，
分析最新资料，
交给 Reviewer 审核，
生成报告，
发现重要事件时立即通知我。”
```

系统执行：

```text
Goal
 ↓
Agent Team
 ↓
Manager
 ↓
Researcher
 ↓
Analyst
 ↓
Reviewer
 ↓
Writer
 ↓
Knowledge
 ↓
Tools
 ↓
Memory
 ↓
Experience
 ↓
Evaluation
 ↓
Scheduler
 ↓
Event
 ↓
Notification
 ↓
下一周期
```

全部过程必须可追踪、可暂停、可恢复、可审计。

---

# 33. 最终产品定位

```text
ModelForge V2.0
= Local AI Platform

ModelForge V3.1
= Multi-Agent Platform

ModelForge V3.3
= Learning Agent Platform

ModelForge V3.4
= Autonomous Agent Platform

ModelForge V4.0
= AI Operating System
```

最终：

```text
ModelForge
=
Model OS
+
Agent OS
+
Knowledge OS
+
Task OS
+
Developer Platform
+
Marketplace
```

这份文档作为 V3.1 → V4.0 的 Master Plan。实际开发时，再把每个版本拆成独立的 Codex 执行计划，细化到具体文件、类、数据库表、字段、API、前端页面、测试和验收条件。
