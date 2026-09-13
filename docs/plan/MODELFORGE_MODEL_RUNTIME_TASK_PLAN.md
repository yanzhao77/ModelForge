# ModelForge 本地模型全生命周期联动改造任务计划

> 文档用途：作为 Codex / OpenCode 的完整开发任务书。
>
> 项目目标：把 ModelForge 从"模型下载器 +
> 若干相互独立的功能页面"，升级为类似 LM Studio
> 的"本地模型管理、加载、推理、对话、训练、模型产物回流"的统一本地 AI
> 推理端。
>
> 核心原则：**模型资产（Model Asset）与运行实例（Runtime
> Instance）分离；所有业务通过稳定的 `model_id`
> 联动，不允许页面之间通过文件路径、模型名称或临时对象直接耦合。**

------------------------------------------------------------------------

# 1. 项目背景

ModelForge 当前已经具备：

-   模型下载任务；
-   模型安装 / 扫描 / 模型记录；
-   本地模型运行时；
-   Chat / Session / Memory；
-   TrainingService；
-   LoRA 配置；
-   数据集管理；
-   推理 / 训练资源 Lease；
-   模型 Readiness 检查；
-   PySide6 桌面 UI。

当前核心问题不是"没有模型功能"，而是：

``` text
模型下载
   ↓
文件落盘
   ↓
没有形成完整的 Model Lifecycle
   ↓
聊天页面不知道这个模型
   ↓
运行时不知道应该加载哪个模型
   ↓
训练页面也无法可靠找到可训练 Base Model
```

因此本次改造不是重新实现下载、聊天或训练，而是建立统一的：

``` text
Model Registry
      ↓
Model Runtime Manager
      ↓
Runtime Instance
      ↓
Chat / Agent / OpenAI API
```

以及：

``` text
Training
   ↓
Training Artifact
   ↓
Register Model
   ↓
Model Registry
   ↓
Runtime
   ↓
Chat
```

------------------------------------------------------------------------

# 2. 最终产品目标

完成后，用户应能获得类似 LM Studio 的完整工作流：

``` text
┌──────────────────────────────────────────────────────────┐
│                      ModelForge                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  模型中心                                                 │
│    ↓                                                     │
│  下载模型                                                 │
│    ↓                                                     │
│  自动注册 / 扫描                                          │
│    ↓                                                     │
│  模型详情                                                 │
│    ↓                                                     │
│  加载模型                                                 │
│    ↓                                                     │
│  Runtime Manager                                         │
│    ↓                                                     │
│  Loaded Instance                                        │
│    ↓                                                     │
│  Chat ─────── Agent ─────── OpenAI Compatible API        │
│                                                          │
│  同时                                                     │
│                                                          │
│  Training                                                │
│    ↓                                                     │
│  Trainable Base Model                                    │
│    ↓                                                     │
│  LoRA / Fine-tune                                        │
│    ↓                                                     │
│  Training Artifact                                       │
│    ↓                                                     │
│  自动注册 Model                                          │
│    ↓                                                     │
│  Load                                                      │
│    ↓                                                     │
│  Chat                                                    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

------------------------------------------------------------------------

# 3. 本次改造必须解决的问题

## 3.1 下载模型后无法使用

当前：

``` text
Download
  ↓
文件存在
```

目标：

``` text
Download
  ↓
Install
  ↓
ModelRecord
  ↓
Capability Detection
  ↓
Ready
  ↓
Load
  ↓
Loaded
  ↓
Chat
```

------------------------------------------------------------------------

## 3.2 Chat 页面无法联动本地模型

当前 Chat 不应该自己猜模型路径。

目标：

``` text
Chat UI
  ↓
model_id
  ↓
Chat API
  ↓
ModelRuntimeManager
  ↓
RuntimeInstance
  ↓
实际模型
```

Chat 页面永远只认识：

``` text
model_id
```

不认识：

``` text
C:\xxx\model.gguf
```

也不应该自己操作：

``` text
llama_cpp.Llama(...)
```

------------------------------------------------------------------------

## 3.3 Training 页面无法找到 Base Model

Training 页面必须读取统一 Model Registry。

但必须区分：

``` text
Inference Model
Training Model
```

例如：

``` text
GGUF Q4_K_M
```

通常适合：

``` text
llama.cpp inference
```

不能因为它是"模型"就自动认为：

``` text
LoRA training capable
```

因此必须引入模型能力：

``` text
CHAT
INFERENCE
VISION
EMBEDDING
TRAINING
LORA
```

Training 页面只显示具备：

``` text
TRAINING
```

或：

``` text
LORA
```

能力的模型。

------------------------------------------------------------------------

## 3.4 Training 完成后的模型无法自动回流

目标：

``` text
Training
   ↓
Output
   ↓
Register Model
   ↓
ModelRegistry
   ↓
Model Center
   ↓
Load
   ↓
Chat
```

现有 `TrainingService.register_model()`
已经具备重要基础，应尽量复用，而不是重新实现。

------------------------------------------------------------------------

# 4. 核心架构

最终采用以下架构：

``` text
                        ┌─────────────────┐
                        │   Model Center  │
                        └────────┬────────┘
                                 │
                                 ↓
                        ┌─────────────────┐
                        │ Model Registry  │
                        └────────┬────────┘
                                 │
                 ┌───────────────┼────────────────┐
                 ↓               ↓                ↓
             Artifact        Capability        Metadata
                 │               │                │
          GGUF / HF / MLX    CHAT/INFERENCE    name
          LoRA / Safetensors TRAINING/LORA     size
                 │               │              format
                 └───────────────┼────────────────┘
                                 ↓
                    ┌────────────────────────┐
                    │ Model Runtime Manager  │
                    └────────────┬───────────┘
                                 │
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
               llama.cpp    Transformers   Future Runtime
                    │            │
                    └────────────┼────────────┘
                                 ↓
                        Runtime Instance
                                 │
                 ┌───────────────┼────────────────┐
                 ↓               ↓                ↓
               Chat            Agent        OpenAI API
                 │               │                │
                 └───────────────┼────────────────┘
                                 ↓
                         Session / Memory


Training:

Dataset + Base Model
          ↓
    TrainingService
          ↓
      Artifact
          ↓
   Model Registration
          ↓
      ModelRegistry
          ↓
   Runtime Manager
          ↓
        Chat
```

------------------------------------------------------------------------

# 5. 核心设计原则

## 5.1 Model Asset 与 Runtime Instance 必须分离

### Model Asset

表示磁盘上的模型。

例如：

``` text
Qwen2.5-0.5B-Instruct-Q4_K_M.gguf
```

包含：

``` text
id
name
path
format
size
source
capabilities
status
metadata
```

------------------------------------------------------------------------

### Runtime Instance

表示已经加载到内存中的模型。

包含：

``` text
instance_id
model_id
runtime_type
status
context_length
gpu_layers
threads
memory_usage
started_at
last_used_at
error
```

关系：

``` text
ModelRecord 1 ───── N RuntimeInstance
```

第一阶段可以只允许：

``` text
1 个 Active Local Runtime
```

后续再扩展多模型并存。

------------------------------------------------------------------------

# 6. Model Lifecycle

必须建立明确状态：

``` text
DISCOVERED
     ↓
INSTALLING
     ↓
INSTALLED
     ↓
READY
     ↓
LOADING
     ↓
LOADED
     ↓
UNLOADING
     ↓
READY
```

异常：

``` text
LOAD_FAILED
TRAIN_FAILED
INSTALL_FAILED
INVALID
```

建议模型状态至少包括：

``` text
discovered
installing
installed
ready
loading
loaded
unloading
load_failed
invalid
```

Runtime 状态：

``` text
idle
loading
loaded
unloading
error
```

------------------------------------------------------------------------

# 7. Model Capability

新增统一能力系统。

建议：

``` text
CHAT
INFERENCE
VISION
EMBEDDING
TRAINING
LORA
AUDIO
IMAGE
```

第一阶段至少实现：

``` text
CHAT
INFERENCE
TRAINING
LORA
```

示例：

``` json
{
  "model_id": "qwen2.5-0.5b-instruct-q4",
  "capabilities": [
    "CHAT",
    "INFERENCE"
  ]
}
```

训练模型：

``` json
{
  "model_id": "qwen2.5-7b-base",
  "capabilities": [
    "CHAT",
    "INFERENCE",
    "TRAINING",
    "LORA"
  ]
}
```

------------------------------------------------------------------------

# 8. Model ID 规则

整个项目统一使用：

``` text
model_id
```

作为跨页面唯一标识。

禁止：

``` text
model_name
file_name
absolute_path
display_name
```

作为业务关联 ID。

例如：

``` text
model_id:
01JXYZ...
```

或者项目已有 UUID 机制则继续使用已有机制。

要求：

``` text
Download → model_id
Model Center → model_id
Chat → model_id
Training → base_model_id
Runtime → model_id
API → model_id
```

全部一致。

------------------------------------------------------------------------

# 9. 后端任务拆分

------------------------------------------------------------------------

## Phase 0：代码基线与架构检查

### 目标

在修改代码前确认当前实现，避免重复造轮子。

### 必须检查

``` text
backend/app/services/model_manager.py
backend/app/services/runtime_registry.py
backend/app/services/chat_service.py
backend/app/services/training.py
backend/app/services/model_readiness_service.py
backend/app/services/runtimes/local_runtime.py
backend/app/api/models.py
```

同时检查：

``` text
ModelRecord
TrainTask
Dataset
Runtime
Lease
Session
```

相关数据库模型、Repository、API Schema、UI Model。

### 输出

新增：

``` text
docs/MODEL_RUNTIME_ARCHITECTURE.md
```

记录：

-   当前模型生命周期；
-   当前 Runtime 生命周期；
-   当前 Chat 调用链；
-   当前 Training 调用链；
-   当前问题；
-   改造后的目标链路。

### 验收

不能出现：

-   重复创建已经存在的 ModelRecord；
-   重复实现下载；
-   重复实现训练；
-   删除现有可工作的 ModelManager；
-   删除已有 TrainingService。

------------------------------------------------------------------------

# 10. Phase 1：统一 Model Registry

## 10.1 目标

让所有模块通过一个统一模型注册中心获取模型。

建议增加：

``` text
ModelRegistry
```

如果现有 `ModelManager` 已经承担 registry 职责，可以：

``` text
ModelManager = persistence/install/remove
ModelRegistry = lifecycle/query/capability
```

也可以不新增独立类，而增强现有 ModelManager。

原则：

**不要为了架构漂亮而重复一套数据库。**

------------------------------------------------------------------------

## 10.2 ModelRecord 增强

至少保证模型记录包含：

``` text
id
name
display_name
path
format
source
status
size_bytes
created_at
updated_at
capabilities
metadata
```

可选：

``` text
architecture
parameter_count
quantization
context_length
family
base_model_id
parent_model_id
training_artifact
```

------------------------------------------------------------------------

## 10.3 Capability Storage

如果数据库支持 JSON：

``` json
["CHAT", "INFERENCE"]
```

否则增加关联表：

``` text
model_capabilities
```

结构：

``` text
model_id
capability
```

------------------------------------------------------------------------

## 10.4 Model Query API

统一：

``` http
GET /api/v1/models
```

支持：

``` text
status
capability
format
source
```

例如：

``` http
GET /api/v1/models?capability=CHAT
```

训练：

``` http
GET /api/v1/models?capability=TRAINING
```

------------------------------------------------------------------------

# 11. Phase 2：模型下载 → 自动注册

## 目标

解决：

``` text
下载成功
但模型中心不知道
```

下载完成后必须自动：

``` text
Download
 ↓
Verify
 ↓
Install
 ↓
Register
 ↓
Detect Metadata
 ↓
Detect Capability
 ↓
READY
```

------------------------------------------------------------------------

## 11.1 下载完成事件

建议建立内部事件：

``` text
MODEL_DOWNLOAD_COMPLETED
```

事件 payload：

``` json
{
  "model_id": "...",
  "path": "...",
  "format": "gguf"
}
```

------------------------------------------------------------------------

## 11.2 自动扫描

调用现有：

``` text
ModelManager.scan()
```

但扫描后必须确保：

``` text
ModelRecord
```

真实存在。

------------------------------------------------------------------------

## 11.3 重复下载保护

相同模型：

``` text
hash
path
source
```

不能重复创建多个 ModelRecord。

------------------------------------------------------------------------

# 12. Phase 3：Model Runtime Manager

这是本次改造最重要的模块。

新增：

``` text
backend/app/services/model_runtime_manager.py
```

如果项目已有 Runtime Registry，则增强它，不要同时维护两套状态。

------------------------------------------------------------------------

## 12.1 核心 API

``` python
load(
    model_id,
    context_length=None,
    gpu_layers=None,
    threads=None,
    **kwargs
)

unload(model_id=None)

get_status(model_id)

get_current()

list_loaded()

chat(
    model_id,
    messages,
    **kwargs
)

stream_chat(
    model_id,
    messages,
    **kwargs
)
```

------------------------------------------------------------------------

## 12.2 load 流程

``` text
load(model_id)
       ↓
ModelRegistry.get(model_id)
       ↓
检查 ModelRecord
       ↓
检查 READY
       ↓
检查 capability
       ↓
获取 model path
       ↓
获取 format
       ↓
选择 runtime
       ↓
获取 inference lease
       ↓
LocalRuntime(model_path)
       ↓
load
       ↓
RuntimeInstance
       ↓
状态 LOADED
```

------------------------------------------------------------------------

## 12.3 必须解决现有 LocalRuntime 的问题

当前 LocalRuntime 支持：

``` text
GGUF / llama_cpp
Transformers / safetensors
```

必须保证：

``` text
model_id
```

最终能够解析到：

``` text
model_path
```

不能出现：

``` python
LocalRuntime()
```

然后内部无法知道加载哪个模型。

应该变成类似：

``` python
runtime = LocalRuntime(model_path=model.path)
```

或者：

``` python
runtime.load(model_path=model.path)
```

------------------------------------------------------------------------

# 13. Runtime Instance

建议建立：

``` python
RuntimeInstance
```

例如：

``` python
@dataclass
class RuntimeInstance:
    instance_id: str
    model_id: str
    runtime_type: str
    status: str
    model_path: str
    context_length: int | None
    gpu_layers: int | None
    threads: int | None
    memory_bytes: int | None
    started_at: datetime | None
    last_used_at: datetime | None
    error: str | None
```

第一阶段可以：

``` text
in-memory
```

不一定马上落库。

但 ModelRecord 必须持久化。

------------------------------------------------------------------------

# 14. Runtime API

增加：

``` http
GET /api/v1/runtime
```

返回：

``` json
{
  "active": true,
  "instance_id": "...",
  "model_id": "...",
  "status": "loaded",
  "runtime": "llama.cpp",
  "context_length": 4096,
  "gpu_layers": 0,
  "memory_bytes": 1234567890
}
```

------------------------------------------------------------------------

## Load

``` http
POST /api/v1/models/{model_id}/load
```

请求：

``` json
{
  "context_length": 4096,
  "gpu_layers": 0,
  "threads": 8
}
```

返回：

``` json
{
  "instance_id": "...",
  "model_id": "...",
  "status": "loading"
}
```

------------------------------------------------------------------------

## Unload

``` http
POST /api/v1/models/{model_id}/unload
```

------------------------------------------------------------------------

## Status

``` http
GET /api/v1/models/{model_id}/runtime
```

------------------------------------------------------------------------

# 15. Runtime 冲突策略

第一阶段只允许：

``` text
一个本地模型实例处于 LOADED
```

如果：

``` text
A 已加载
```

用户加载：

``` text
B
```

默认：

``` text
Unload A
↓
Load B
```

不要第一阶段做复杂的：

``` text
LRU
多模型并存
自动显存调度
```

这些属于后续版本。

------------------------------------------------------------------------

# 16. 内存释放

必须认真处理：

``` text
unload
```

确保：

``` text
引用释放
↓
llama object 释放
↓
GC
↓
runtime 状态清理
```

不能只是：

``` python
self.runtime = None
```

就认为已经释放。

需要测试：

``` text
Load A
Unload A
Load B
Unload B
Load A
```

连续循环至少：

``` text
5 次
```

不能：

-   OOM；
-   文件句柄泄漏；
-   线程泄漏；
-   Runtime 状态错误。

------------------------------------------------------------------------

# 17. Phase 4：Chat 联动

## 17.1 Chat API 必须接受 model_id

请求：

``` json
{
  "model_id": "xxx",
  "session_id": "xxx",
  "messages": [
    {
      "role": "user",
      "content": "你好"
    }
  ]
}
```

------------------------------------------------------------------------

## 17.2 ChatService 不负责模型加载细节

ChatService：

``` text
Session
Memory
History
Metrics
```

RuntimeManager：

``` text
Model
Load
Unload
Inference
```

分工：

``` text
ChatService
      ↓
RuntimeManager
      ↓
RuntimeInstance
```

------------------------------------------------------------------------

# 18. Chat 页面模型选择器

模型下拉框必须来自：

``` text
GET /api/v1/models?capability=CHAT
```

同时显示状态：

``` text
Qwen2.5-0.5B
● 已加载
```

或者：

``` text
Qwen2.5-7B
○ 未加载
```

------------------------------------------------------------------------

## 18.1 用户选择未加载模型

Chat 页面可以：

``` text
选择模型
↓
发现未加载
↓
调用 load
↓
等待 LOADED
↓
发送消息
```

但模型加载逻辑必须通过：

``` text
RuntimeManager
```

而不是 Chat UI 自己加载。

------------------------------------------------------------------------

# 19. Chat 首次发送流程

``` text
用户选择模型
      ↓
检查 runtime
      ↓
已加载？
 ┌────┴────┐
是         否
│           │
↓           ↓
直接使用   load(model_id)
             ↓
          LOADED
             ↓
          Chat
```

------------------------------------------------------------------------

# 20. Chat Streaming

Streaming 必须保持：

``` text
model_id
session_id
request_id
```

上下文完整。

不要为了 Runtime 改造破坏现有：

``` text
SSE
streaming
history
metrics
memory
```

------------------------------------------------------------------------

# 21. Phase 5：Training 联动

Training 页面必须从：

``` text
ModelRegistry
```

读取 Base Model。

------------------------------------------------------------------------

## 21.1 Training Base Model

接口：

``` http
GET /api/v1/models?capability=TRAINING
```

UI：

``` text
Base Model
┌───────────────────────────┐
│ Qwen2.5-1.5B Base         │
│ Qwen2.5-7B Base           │
└───────────────────────────┘
```

不能显示纯：

``` text
GGUF inference-only model
```

------------------------------------------------------------------------

# 22. GGUF 与 Training 的重要限制

必须在 UI 和后端同时防御。

例如：

``` text
Qwen2.5-0.5B-Q4_K_M.gguf
```

可以：

``` text
INFERENCE
CHAT
```

但不能自动：

``` text
TRAINING
```

除非明确存在对应训练能力和训练格式。

训练一般需要：

``` text
Hugging Face Transformers
Safetensors
Base model
```

或项目训练器明确支持的格式。

因此：

``` text
format
+
capabilities
```

共同决定是否可训练。

后端必须最终校验，不能只依赖 UI 过滤。

------------------------------------------------------------------------

# 23. Training API

训练任务请求：

``` json
{
  "base_model_id": "...",
  "dataset_id": "...",
  "config": {
    "method": "lora",
    "epochs": 3,
    "learning_rate": 0.0002
  }
}
```

后端：

``` text
base_model_id
↓
ModelRegistry.get()
↓
capability TRAINING?
↓
path
↓
TrainingService
```

------------------------------------------------------------------------

# 24. TrainingService 改造要求

尽量保留现有：

``` text
TrainingService.start()
TrainingService.register_model()
TrainTask
resource lease
subprocess
polling
```

重点修改：

``` text
base_model
```

从：

``` text
path / name
```

逐渐统一为：

``` text
base_model_id
```

然后由 Registry 解析：

``` text
base_model_id
 ↓
ModelRecord
 ↓
model.path
```

------------------------------------------------------------------------

# 25. Training 完成后的 Model Registration

现有：

``` text
TrainingService.register_model()
```

已经是正确方向。

需要确保最终：

``` text
training output
↓
ModelManager.install()
↓
ModelRecord
↓
capabilities
↓
READY
```

并返回：

``` json
{
  "model_id": "...",
  "name": "...",
  "status": "ready"
}
```

------------------------------------------------------------------------

# 26. Training Artifact Metadata

训练产物建议记录：

``` text
base_model_id
training_task_id
dataset_id
method
created_at
output_path
format
```

例如：

``` json
{
  "base_model_id": "qwen-base",
  "training_task_id": "task-123",
  "method": "lora",
  "format": "safetensors"
}
```

------------------------------------------------------------------------

# 27. LoRA 模型处理

第一阶段：

``` text
LoRA Adapter
```

注册为：

``` text
LORA
TRAINING
```

或者：

``` text
LORA
CHAT
```

取决于项目实际 Runtime 是否已经支持 Adapter 加载。

**不能声称 LoRA 已经可以聊天，除非 Runtime 真正实现了 Base + Adapter
加载。**

如果当前 Runtime 尚未支持：

``` text
Base Model + LoRA Adapter
```

那么本次第一阶段：

``` text
训练完成
↓
注册
↓
展示
```

但不能虚假显示：

``` text
已可聊天
```

可以显示：

``` text
LoRA Adapter
需要 Base Model
```

第二阶段再实现：

``` text
Base + Adapter Runtime
```

------------------------------------------------------------------------

# 28. Phase 6：Model Center UI

模型页面最终需要展示：

``` text
模型名称
格式
大小
来源
能力
状态
运行状态
```

例如：

``` text
Qwen2.5-0.5B-Instruct

GGUF
Q4_K_M
520 MB

能力：
✓ Chat
✓ Inference

状态：
● Loaded

Runtime：
llama.cpp

Context：
4096

[卸载] [设为默认]
```

未加载：

``` text
○ Ready

[加载] [设为默认]
```

------------------------------------------------------------------------

# 29. 下载完成后的 UI 联动

下载任务完成：

``` text
Download 100%
↓
Install
↓
Register
↓
Refresh Model Registry
↓
Model Center 自动出现
```

不需要用户：

``` text
手动重启
手动扫描
手动输入路径
```

------------------------------------------------------------------------

# 30. Phase 7：Runtime 页面

利用现有：

``` text
运行时
```

页面。

第一阶段展示：

``` text
当前模型
运行时
状态
上下文长度
GPU Layers
线程数
内存
加载时间
最后使用时间
```

按钮：

``` text
卸载
```

后续：

``` text
重新加载
```

------------------------------------------------------------------------

# 31. Phase 8：Default Model

实现：

``` http
GET /api/v1/models/default
```

和：

``` http
POST /api/v1/models/{id}/default
```

默认模型应该是：

``` text
用户偏好
```

而不是：

``` text
当前 Loaded Model
```

两者必须区分：

``` text
Default Model
≠
Loaded Model
```

例如：

``` text
默认模型：Qwen2.5-7B
当前加载：Qwen2.5-1.5B
```

完全合法。

------------------------------------------------------------------------

# 32. Phase 9：统一事件系统

页面之间不能依赖：

``` text
刷新按钮
```

作为主要同步手段。

建议至少定义：

``` text
MODEL_INSTALLED
MODEL_REMOVED
MODEL_LOADING
MODEL_LOADED
MODEL_UNLOADING
MODEL_LOAD_FAILED

TRAINING_STARTED
TRAINING_PROGRESS
TRAINING_COMPLETED
TRAINING_FAILED
```

第一阶段可以采用简单：

``` text
polling
```

例如：

``` text
Runtime 页面每 1 秒刷新状态
Training 页面每 1 秒刷新任务
```

第二阶段再考虑：

``` text
SSE / WebSocket
```

不要为了事件系统拖慢第一阶段。

------------------------------------------------------------------------

# 33. Phase 10：OpenAI Compatible Local API

为了真正接近 LM Studio，增加：

``` http
GET /v1/models
POST /v1/chat/completions
```

例如：

``` http
POST http://127.0.0.1:7783/v1/chat/completions
```

请求：

``` json
{
  "model": "qwen2.5-0.5b",
  "messages": [
    {
      "role": "user",
      "content": "你好"
    }
  ],
  "stream": true
}
```

后端：

``` text
model
↓
resolve model_id
↓
RuntimeManager
↓
loaded runtime
↓
stream response
```

------------------------------------------------------------------------

# 34. OpenAI API 与内部 API 的关系

不要让：

``` text
OpenAI API
```

绕过：

``` text
RuntimeManager
```

正确：

``` text
OpenAI API
    ↓
Model Resolver
    ↓
Runtime Manager
    ↓
Runtime
```

这样：

``` text
Chat UI
Agent
OpenAI API
```

全部使用同一个模型运行实例。

------------------------------------------------------------------------

# 35. Model Resolver

建议增加：

``` text
ModelResolver
```

负责：

``` text
model_id
model name
model alias
```

解析到：

``` text
ModelRecord
```

例如：

``` python
resolve("qwen2.5-0.5b")
```

得到：

``` text
ModelRecord
```

但内部最终仍然统一使用：

``` text
model_id
```

------------------------------------------------------------------------

# 36. Resource Lease 联动

已有：

``` text
inference lease
training lease
```

必须继续使用。

规则：

``` text
Inference
    ↕
Training
```

默认互斥。

训练开始：

``` text
获取 training lease
```

模型推理：

``` text
获取 inference lease
```

如果资源冲突：

``` text
返回明确错误
```

例如：

``` text
当前正在训练模型，请等待训练结束后再进行推理。
```

------------------------------------------------------------------------

# 37. 推荐的资源状态机

``` text
IDLE
 │
 ├──── LOAD MODEL ────→ LOADING
 │                         │
 │                         ↓
 │                       LOADED
 │                         │
 │                 ┌───────┴────────┐
 │                 ↓                ↓
 │               CHAT             UNLOAD
 │                                  ↓
 │                              UNLOADING
 │                                  ↓
 └──────────────────────────────── IDLE


IDLE
 │
 └──── TRAIN ────→ TRAINING
                      │
              ┌───────┴───────┐
              ↓               ↓
          COMPLETED          FAILED
              │
              ↓
        REGISTER MODEL
```

------------------------------------------------------------------------

# 38. 数据库迁移

如果现有 ModelRecord 缺字段：

新增 migration。

可能需要：

``` text
capabilities
status
format
metadata
parent_model_id
base_model_id
```

如果使用关系表：

``` text
model_capabilities
```

不要直接修改生产数据库结构而没有 migration。

------------------------------------------------------------------------

# 39. API Schema 统一

建议新增：

``` text
ModelResponse
ModelCapability
RuntimeResponse
LoadModelRequest
LoadModelResponse
UnloadModelResponse
TrainingStartRequest
TrainingResultResponse
```

避免：

``` text
models.py
chat.py
training.py
runtime.py
```

各自定义不同的 model/path/name 字段。

------------------------------------------------------------------------

# 40. 错误处理

统一错误类型。

至少：

``` text
MODEL_NOT_FOUND
MODEL_NOT_READY
MODEL_FORMAT_UNSUPPORTED
MODEL_CAPABILITY_UNSUPPORTED
MODEL_ALREADY_LOADING
MODEL_ALREADY_LOADED
RUNTIME_LOAD_FAILED
RUNTIME_NOT_LOADED
RUNTIME_BUSY
TRAINING_MODEL_UNSUPPORTED
TRAINING_BUSY
MODEL_PATH_INVALID
```

错误必须包含：

``` text
code
message
details
```

例如：

``` json
{
  "code": "TRAINING_MODEL_UNSUPPORTED",
  "message": "该 GGUF 模型仅支持推理，不支持 LoRA 训练",
  "details": {
    "model_id": "xxx",
    "format": "gguf"
  }
}
```

------------------------------------------------------------------------

# 41. 日志

统一日志：

``` text
[ModelRegistry]
[ModelRuntime]
[Runtime]
[Chat]
[Training]
```

例如：

``` text
[ModelRuntime] loading model_id=xxx
[ModelRuntime] resolved path=...
[ModelRuntime] runtime=llama.cpp
[ModelRuntime] load completed
```

禁止：

``` text
打印 API Key
打印用户敏感信息
打印完整 prompt
```

------------------------------------------------------------------------

# 42. 测试计划

这是本次任务的强制部分。

------------------------------------------------------------------------

## 42.1 Model Registry 测试

必须测试：

``` text
注册模型
查询模型
按 capability 查询
删除模型
重复注册
非法路径
模型状态
```

------------------------------------------------------------------------

## 42.2 Download → Registry

测试：

``` text
下载
↓
完成
↓
自动注册
↓
Model API 可查询
```

------------------------------------------------------------------------

## 42.3 Runtime 测试

至少：

``` text
Load
Status
Chat
Unload
Reload
```

完整：

``` text
A Load
A Chat
A Unload
B Load
B Chat
B Unload
A Load
A Chat
```

------------------------------------------------------------------------

## 42.4 Runtime 异常测试

模拟：

``` text
文件不存在
模型格式错误
内存不足
模型加载失败
重复 Load
重复 Unload
```

确保：

``` text
不会卡死
不会留下错误状态
不会永久占用 Lease
```

------------------------------------------------------------------------

# 43. Chat 测试

必须测试：

``` text
选择模型
发送消息
Streaming
Session
History
Memory
切换模型
```

重点：

``` text
A 模型 → Chat
B 模型 → Chat
```

切换后不能继续使用 A。

------------------------------------------------------------------------

# 44. Training 测试

必须测试：

``` text
可训练模型出现
GGUF inference-only 模型不出现
训练开始
训练进行
训练完成
模型注册
模型中心出现
```

------------------------------------------------------------------------

# 45. Training → Chat 集成测试

最终必须做到：

``` text
选择 Base Model
↓
创建 Dataset
↓
LoRA Training
↓
Training Completed
↓
Artifact Registered
↓
Model Center 出现
↓
Runtime Load
↓
Chat
```

如果 LoRA Adapter Runtime 尚未实现：

``` text
Training
↓
Register Adapter
↓
明确显示需要 Base Model
```

不能伪装成完整 Chat Model。

------------------------------------------------------------------------

# 46. OpenAI API 测试

测试：

``` text
GET /v1/models
POST /v1/chat/completions
stream=false
stream=true
```

确保：

``` text
OpenAI API
```

和：

``` text
Chat UI
```

使用同一 Runtime。

------------------------------------------------------------------------

# 47. UI 测试

## Model Center

检查：

``` text
下载
安装
加载
卸载
删除
默认模型
状态刷新
```

## Chat

检查：

``` text
模型列表
Loaded 状态
自动加载
消息发送
Streaming
切换模型
```

## Training

检查：

``` text
Base Model
Dataset
LoRA Config
Training
Progress
Result
```

## Runtime

检查：

``` text
当前模型
Runtime
状态
内存
Unload
```

------------------------------------------------------------------------

# 48. E2E 验收场景

必须实现以下完整场景：

## 场景 A：下载 → Chat

``` text
1. 下载 Qwen GGUF
2. 下载完成
3. Model Center 自动出现
4. 显示 Ready
5. 点击 Load
6. 状态 Loading
7. 状态 Loaded
8. 打开 Chat
9. 模型下拉框出现
10. 发送“你好”
11. 正常返回
12. Streaming 正常
```

------------------------------------------------------------------------

## 场景 B：切换模型

``` text
1. Load A
2. Chat A
3. Load B
4. A Unload
5. B Load
6. Chat B
7. 确认 B 的回复来自 B
```

------------------------------------------------------------------------

## 场景 C：Training

``` text
1. 选择 TRAINING Base Model
2. 选择 Dataset
3. 配置 LoRA
4. 开始训练
5. Training Lease 获取成功
6. Training Progress
7. Training 完成
8. Artifact 注册
9. Model Center 出现
```

------------------------------------------------------------------------

## 场景 D：训练产物回流

``` text
Training
↓
Artifact
↓
ModelRegistry
↓
Model Center
↓
Load
↓
Runtime
↓
Chat
```

如果是 Adapter：

``` text
Model Center
↓
显示 LoRA Adapter
↓
显示 Base Model
↓
明确标注是否可直接 Chat
```

------------------------------------------------------------------------

## 场景 E：OpenAI API

``` text
外部客户端
↓
http://127.0.0.1:<port>/v1/models
↓
看到模型
↓
/v1/chat/completions
↓
正常返回
```

------------------------------------------------------------------------

# 49. UI 状态规范

统一：

``` text
● Loaded
◐ Loading
○ Ready
× Error
```

禁止不同页面出现：

``` text
Loaded
已加载
Running
运行中
Active
```

表示同一个状态却各自不同。

后端状态统一，UI 负责翻译。

------------------------------------------------------------------------

# 50. 不做的事情

本次任务明确禁止范围：

## 不重写模型下载系统

已有下载能力可用就保留。

## 不重写 TrainingService

只改接口和模型绑定。

## 不重写 ChatService

只增加 Runtime Manager 接入。

## 不第一阶段实现多模型并存

先：

``` text
single active runtime
```

## 不第一阶段实现 LRU

以后再做。

## 不第一阶段实现复杂 GPU 调度

先保证：

``` text
CPU / GPU layers
```

基本参数可用。

## 不把 GGUF 自动变成可训练模型

必须区分 inference / training capability。

## 不为了"LM Studio"而复制 LM Studio

目标是：

``` text
LM Studio 类产品体验
```

不是：

``` text
复制 LM Studio 内部实现
```

------------------------------------------------------------------------

# 51. 推荐文件结构

根据当前项目结构，建议最终接近：

``` text
backend/
└── app/
    ├── api/
    │   ├── models.py
    │   ├── runtime.py
    │   ├── chat.py
    │   ├── training.py
    │   └── openai.py
    │
    ├── services/
    │   ├── model_manager.py
    │   ├── model_registry.py
    │   ├── model_resolver.py
    │   ├── model_runtime_manager.py
    │   ├── runtime_registry.py
    │   ├── chat_service.py
    │   ├── training.py
    │   └── model_readiness_service.py
    │
    ├── runtimes/
    │   ├── local_runtime.py
    │   ├── llama_cpp_runtime.py
    │   └── transformers_runtime.py
    │
    ├── schemas/
    │   ├── model.py
    │   ├── runtime.py
    │   ├── chat.py
    │   └── training.py
    │
    └── models/
        ├── model.py
        ├── training.py
        └── ...
```

如果当前项目结构不同，以现有架构为准，不要机械移动文件。

------------------------------------------------------------------------

# 52. Runtime Adapter 设计

为了未来支持：

``` text
llama.cpp
Transformers
Ollama
MLX
vLLM
```

建议抽象：

``` python
class RuntimeAdapter:
    def load(self, model_path, config):
        ...

    def unload(self):
        ...

    def chat(self, messages, **kwargs):
        ...

    def stream_chat(self, messages, **kwargs):
        ...

    def status(self):
        ...
```

当前先实现：

``` text
LocalRuntime / llama.cpp
```

未来：

``` text
TransformersRuntime
OllamaRuntime
MLXRuntime
```

------------------------------------------------------------------------

# 53. 不要过度抽象

第一阶段不要建立：

``` text
20 个 Interface
10 个 Factory
6 个 Strategy
```

只需要保证：

``` text
Model Registry
Model Resolver
Runtime Manager
Runtime Adapter
```

职责清楚即可。

------------------------------------------------------------------------

# 54. Runtime 配置

建议保存用户最后使用的 Runtime 配置：

``` text
context_length
gpu_layers
threads
temperature
top_p
max_tokens
```

但区分：

``` text
Model Load Config
```

和：

``` text
Generation Config
```

不要混在 ModelRecord。

------------------------------------------------------------------------

# 55. Model Metadata

建议支持：

``` json
{
  "architecture": "qwen2",
  "parameters": "0.5B",
  "quantization": "Q4_K_M",
  "context_length": 32768,
  "family": "Qwen"
}
```

metadata 获取失败时：

``` text
不能阻塞模型安装
```

只标记：

``` text
metadata incomplete
```

------------------------------------------------------------------------

# 56. Readiness

已有：

``` text
ModelReadinessService
```

应继续使用。

Readiness 至少检查：

``` text
path exists
file exists
format supported
runtime supported
capability
```

返回：

``` json
{
  "ready": true,
  "model_id": "...",
  "issues": []
}
```

------------------------------------------------------------------------

# 57. 并发控制

必须避免：

``` text
Thread A: Load model
Thread B: Unload model
Thread C: Chat
```

同时操作同一个 Runtime。

RuntimeManager 必须有：

``` text
Lock
```

或者等价并发控制。

状态迁移必须原子化。

例如：

``` text
READY → LOADING
```

不能出现两个 Load 同时进入。

------------------------------------------------------------------------

# 58. Chat 与 Unload 的竞争

如果当前正在：

``` text
Chat
```

用户点击：

``` text
Unload
```

不能立即销毁 Runtime。

策略：

``` text
active_requests > 0
```

则：

``` text
等待请求完成
```

或者返回：

``` text
RUNTIME_BUSY
```

第一阶段推荐：

``` text
RUNTIME_BUSY
```

简单可靠。

------------------------------------------------------------------------

# 59. Training 与 Runtime 冲突

如果模型正在：

``` text
Training
```

不允许：

``` text
Inference
```

如果模型正在：

``` text
Inference
```

TrainingService 应等待或返回：

``` text
RUNTIME_BUSY
```

具体策略沿用现有 Lease 机制。

------------------------------------------------------------------------

# 60. 安全要求

模型路径必须经过：

``` text
ModelManager
```

验证。

禁止 API 用户直接传入：

``` text
任意绝对路径
```

例如：

``` text
C:\Windows\...
```

API 只接受：

``` text
model_id
```

后端自己解析路径。

------------------------------------------------------------------------

# 61. 删除模型保护

如果模型：

``` text
LOADED
```

不能直接删除。

必须：

``` text
Unload
↓
确认没有 active request
↓
Delete
```

------------------------------------------------------------------------

# 62. 默认模型保护

如果：

``` text
删除 Default Model
```

则：

``` text
Default = null
```

或者自动选择下一个可用模型。

不能留下：

``` text
default_model_id
```

指向不存在的记录。

------------------------------------------------------------------------

# 63. 数据一致性

任何模型文件存在：

``` text
但 ModelRecord 不存在
```

都可以通过：

``` text
scan
```

重新发现。

任何 ModelRecord：

``` text
但文件不存在
```

必须：

``` text
INVALID
```

而不是：

``` text
READY
```

------------------------------------------------------------------------

# 64. Migration 策略

开发顺序：

``` text
1. 增加字段
2. migration
3. 兼容旧记录
4. 自动补齐 capabilities
5. 验证旧数据
```

旧模型如果无法自动判断：

``` text
capabilities = INFERENCE
```

然后由用户/系统进一步补充。

不要猜：

``` text
TRAINING
```

------------------------------------------------------------------------

# 65. 第一阶段 Runtime 实现选择

优先复用当前：

``` text
llama_cpp.Llama
```

因为 ModelForge 已经有 LocalRuntime。

不要一开始就整体替换成：

``` text
llama-server subprocess
```

但代码结构必须允许未来替换。

如果后续发现：

``` text
内存释放不可靠
崩溃影响主程序
多模型切换困难
```

再增加：

``` text
llama-server subprocess Runtime Adapter
```

作为第二阶段。

------------------------------------------------------------------------

# 66. 开发顺序

严格按照以下顺序实施：

``` text
Phase 0
架构检查
   ↓
Phase 1
Model Registry
   ↓
Phase 2
Download → Registry
   ↓
Phase 3
Runtime Manager
   ↓
Phase 4
Chat
   ↓
Phase 5
Training
   ↓
Phase 6
Model Center UI
   ↓
Phase 7
Runtime UI
   ↓
Phase 8
Default Model
   ↓
Phase 9
事件 / 状态同步
   ↓
Phase 10
OpenAI Compatible API
   ↓
Phase 11
E2E / Regression
```

不要反过来先改 UI。

------------------------------------------------------------------------

# 67. 每个 Phase 必须满足"可运行"

每完成一个 Phase：

``` text
代码
+
测试
+
API
+
UI（如果涉及）
+
文档
```

必须可以运行。

禁止：

``` text
连续改 20 个文件
最后一起测试
```

------------------------------------------------------------------------

# 68. Codex 执行策略

Codex 执行时：

## 第一步

先阅读：

``` text
README
现有 docs
ModelManager
RuntimeRegistry
LocalRuntime
ChatService
TrainingService
ModelReadinessService
Models API
Chat API
Training API
数据库 ModelRecord
前端 Model 页面
前端 Chat 页面
前端 Training 页面
Runtime 页面
```

------------------------------------------------------------------------

## 第二步

建立：

``` text
docs/MODEL_RUNTIME_ARCHITECTURE.md
```

确认架构。

------------------------------------------------------------------------

## 第三步

实现后端核心：

``` text
Registry
Resolver
RuntimeManager
RuntimeInstance
```

------------------------------------------------------------------------

## 第四步

API。

------------------------------------------------------------------------

## 第五步

Chat。

------------------------------------------------------------------------

## 第六步

Training。

------------------------------------------------------------------------

## 第七步

UI。

------------------------------------------------------------------------

## 第八步

OpenAI API。

------------------------------------------------------------------------

## 第九步

E2E。

------------------------------------------------------------------------

# 69. Codex 修改原则

必须遵守：

``` text
先读后改
先测试后重构
复用现有 Service
最小侵入
保持现有 API 兼容
数据库必须 migration
不删除现有功能
不改变已有训练算法
不改变已有 Chat Memory 逻辑
不改变已有 Dataset 逻辑
```

------------------------------------------------------------------------

# 70. Definition of Done

本项目只有在以下全部满足时，才算完成。

## 模型

-   [ ] 下载完成自动注册
-   [ ] ModelRecord 正确
-   [ ] capability 正确
-   [ ] readiness 正确
-   [ ] 模型可以 Load
-   [ ] 模型可以 Unload
-   [ ] 模型可以重新 Load
-   [ ] 删除保护正确

## Runtime

-   [ ] RuntimeManager 完成
-   [ ] model_id → path 正确
-   [ ] RuntimeInstance 正确
-   [ ] 状态正确
-   [ ] 内存释放正确
-   [ ] 并发安全
-   [ ] Lease 正确

## Chat

-   [ ] Chat 模型列表来自 Registry
-   [ ] Chat 支持 model_id
-   [ ] 未加载模型可以自动 Load
-   [ ] Streaming 正常
-   [ ] Session 正常
-   [ ] Memory 正常
-   [ ] 切换模型正常

## Training

-   [ ] Base Model 来自 Registry
-   [ ] capability 过滤
-   [ ] GGUF inference-only 模型不会被误当训练模型
-   [ ] Training 使用 base_model_id
-   [ ] Training 完成自动注册
-   [ ] Artifact metadata 完整
-   [ ] Training Lease 正常

## UI

-   [ ] Model Center 正确
-   [ ] Chat 正确
-   [ ] Training 正确
-   [ ] Runtime 正确
-   [ ] 状态同步正确
-   [ ] 错误提示正确

## OpenAI API

-   [ ] `/v1/models`
-   [ ] `/v1/chat/completions`
-   [ ] streaming
-   [ ] model resolver
-   [ ] 与内部 Runtime 共用

## 测试

-   [ ] Unit Test
-   [ ] Service Test
-   [ ] API Test
-   [ ] Runtime Test
-   [ ] Training Test
-   [ ] Chat Test
-   [ ] E2E Test
-   [ ] Regression Test

------------------------------------------------------------------------

# 71. 最终用户体验

完成后用户操作应该非常简单：

``` text
① 模型中心

下载 Qwen2.5-0.5B
        ↓
下载完成
        ↓
自动安装
        ↓
自动出现在模型列表
```

然后：

``` text
② 点击“加载”

Loading...
        ↓
Loaded
```

然后：

``` text
③ 打开 Chat

模型：
Qwen2.5-0.5B ● Loaded

输入：
你好

输出：
你好，我是……
```

训练：

``` text
④ Training

Base Model：
Qwen2.5-1.5B Base

Dataset：
my_dataset

LoRA：
r=16

开始训练
        ↓
完成
        ↓
模型中心自动出现训练产物
```

然后：

``` text
⑤ 加载训练产物

Load
 ↓
Runtime
 ↓
Chat
```

最终：

``` text
Download
   ↓
Install
   ↓
Register
   ↓
Load
   ↓
Runtime
   ↓
Chat
   ↓
Training
   ↓
Artifact
   ↓
Register
   ↓
Load
   ↓
Chat
```

这条链路才是本次改造的最终目标。

------------------------------------------------------------------------

# 72. 最终架构判断标准

完成后检查整个项目：

如果出现：

``` text
Model Center 有自己的模型列表
Chat 有自己的模型列表
Training 又有自己的模型列表
Runtime 又有自己的模型对象
```

说明改造失败。

正确状态必须是：

``` text
                 Model Registry
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
        Model        Runtime      Training
        Center       Manager      Service
          │            │            │
          └────────────┼────────────┘
                       ↓
                     Chat
```

**Model Registry 是唯一模型事实来源（Single Source of Truth）。**

------------------------------------------------------------------------

# 73. 最终核心原则

整个 ModelForge 的模型链路必须统一成：

``` text
                    ┌──────────────┐
                    │ Model Asset  │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ ModelRecord  │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │  Capability  │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ModelResolver │
                    └──────┬───────┘
                           ↓
                 ┌─────────────────────┐
                 │ ModelRuntimeManager │
                 └──────────┬──────────┘
                            ↓
                    RuntimeInstance
                            ↓
             ┌──────────────┼──────────────┐
             ↓              ↓              ↓
           Chat           Agent        OpenAI API

Training
   ↓
Artifact
   ↓
ModelRecord
   ↓
Runtime
   ↓
Chat
```

**一句话总结：**

> 不要继续给"下载、聊天、训练"分别打补丁；这次要把 ModelForge
> 的核心模型生命周期真正建立起来，让"模型"成为整个系统的一等公民，而
> Chat、Training、Agent、OpenAI API
> 都只是使用这个统一模型生命周期的上层功能。

------------------------------------------------------------------------

# 74. 给 Codex 的执行指令

执行本计划时，Codex 必须遵守：

1.  先完整阅读现有代码，不要直接修改。
2.  先输出当前架构与本计划的差异。
3.  如果现有实现已经具备某项能力，优先复用。
4.  不得为了实现本计划删除已有功能。
5.  每个 Phase 单独完成、测试、提交结果。
6.  每次修改后运行相关测试。
7.  数据库结构变化必须创建 migration。
8.  所有跨模块模型关联使用 `model_id`。
9.  禁止让 UI 直接持有或传递模型绝对路径作为业务 ID。
10. 禁止把 GGUF inference-only 模型自动标记为 TRAINING。
11. Runtime 必须由统一 RuntimeManager 管理。
12. ChatService 不得自行创建 LocalRuntime。
13. TrainingService 不得自己通过文件名猜 Base Model。
14. DownloadService 不得成为第二套 Model Registry。
15. ModelRegistry 必须成为模型状态和元数据的唯一事实来源。
16. 保留现有 Resource Lease。
17. 保留现有 Session / Memory / Chat History。
18. 保留现有 Training / Dataset / LoRA 配置。
19. 不要第一阶段实现多模型并存、LRU、复杂 GPU 调度。
20. 如果某项功能当前 Runtime 尚不支持，必须明确标记为 TODO / capability
    unavailable，而不是伪造"已支持"。
21. 完成后必须提供：

-   修改文件列表；
-   数据库 migration 列表；
-   API 列表；
-   测试结果；
-   E2E 测试结果；
-   已知限制；
-   后续建议。

------------------------------------------------------------------------

# 75. 最终交付物

最终至少交付：

``` text
docs/
├── MODEL_RUNTIME_ARCHITECTURE.md
├── MODEL_LIFECYCLE.md
├── MODEL_RUNTIME_API.md
└── MODEL_RUNTIME_TEST_PLAN.md
```

代码：

``` text
Model Registry
Model Resolver
Model Runtime Manager
Runtime Instance
Runtime API
Model API enhancement
Chat integration
Training integration
OpenAI-compatible API
UI integration
Database migration
Tests
```

最终达到：

``` text
ModelForge
=
Local Model Manager
+
Local Runtime
+
Chat
+
Training
+
Agent-ready Runtime
+
OpenAI Compatible Local API
```

而不是：

``` text
Model Download Tool
+
Chat Tool
+
Training Tool
```

------------------------------------------------------------------------

# 76. 版本建议

建议作为：

``` text
ModelForge V1.0 — Unified Model Runtime
```

第一阶段版本：

``` text
V1.0
单模型 Runtime
GGUF inference
Chat
Training registry
OpenAI API
```

后续：

``` text
V1.1
LoRA Adapter Runtime

V1.2
多模型并存

V1.3
LRU / Memory Manager

V1.4
llama-server subprocess isolation

V1.5
Ollama / MLX / Transformers 多 Runtime

V2.0
完整 Agent Runtime
```

------------------------------------------------------------------------

# 77. 成功标准

最终用户不需要知道：

``` text
模型文件在哪里
llama.cpp 怎么加载
Runtime 怎么创建
TrainingService 怎么注册
ModelRecord 怎么保存
```

用户只需要：

``` text
下载模型
↓
加载模型
↓
聊天
```

以及：

``` text
选择 Base Model
↓
选择 Dataset
↓
训练
↓
使用训练结果
```

**如果用户仍然需要手动"导入模型路径""扫描模型""重新启动""在 Chat
页面重新配置模型""训练完成后手动复制模型"，则本任务没有完成。**
