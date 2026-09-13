# ModelForge Python SDK

Thin, typed wrapper over the ModelForge REST and OpenAI-compatible API.

```bash
pip install ./sdk/python
```

```python
from modelforge import ModelForge

client = ModelForge("http://127.0.0.1:8000")
client.login("alice", "secret123")           # or ModelForge(..., api_key="<jwt>")

# 模型
for model in client.models.list(capability="CHAT"):
    print(model["name"], model["status"], model["capabilities"])
client.models.load(3, context_length=4096)
print(client.models.runtime(3)["status"])

# 对话（OpenAI 兼容）
reply = client.chat.completions.create(
    model="qwen2.5-0.5b",
    messages=[{"role": "user", "content": "你好"}],
)
print(reply["choices"][0]["message"]["content"])

# 向量
vectors = client.embeddings.create(["hello", "world"])

# Agent
run = client.agents.run("writer", "写一段产品介绍", wait=True)
print(run["status"], client.agents.trace(run["run_id"])["summary"])

# 知识库
hits = client.knowledge.search("统一模型生命周期", top_k=3, retrieval_mode="hybrid")

# 工作流
wf_run = client.workflows.run("<workflow_id>", {"question": "你好"}, wait=True)
```

Errors raise `ModelForgeError` with `.status`, `.code`, `.message` and
`.correlation_id`, so callers can branch on the stable code instead of parsing
messages.
