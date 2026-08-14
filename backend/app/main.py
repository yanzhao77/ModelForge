"""ModelForge 3.0 FastAPI Backend.

Wires all API routers and injects service singletons on startup (2.1 features
stay untouched; the 3.0 Agent Runtime is layered on top).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import init_db
from services.agent_engine import AgentEngine, get_engine
from services.agent_runtime_service import build_agent_runtime, init_agent_runtime
from services.knowledge_base import KnowledgeBase, get_global_kb
from services.plugin_manager import PluginManager, get_manager
from services.runtime_registry import get_runtime

from api import (
    agent,
    auth,
    chat,
    datasets,
    knowledge,
    memories,
    models,
    openai_api,
    plugin,
    runtime,
    sessions,
    system,
    train,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and inject service singletons."""
    init_db()
    runtime.set_runtime(get_runtime())
    agent.set_agent_engine(get_engine())
    knowledge.set_knowledge_base(get_global_kb())
    plugin.set_plugin_manager(get_manager())

    # 3.0 Agent Runtime
    agent_runtime = build_agent_runtime()
    init_agent_runtime(agent_runtime)
    agent.set_agent_runtime(agent_runtime)
    agent_runtime.start()
    try:
        yield
    finally:
        await agent_runtime.shutdown()


app = FastAPI(title="ModelForge", version="3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in (
    auth.router,
    datasets.router,
    models.router,
    runtime.router,
    chat.router,
    sessions.router,
    memories.router,
    agent.router,
    knowledge.router,
    plugin.router,
    train.router,
    system.router,
):
    app.include_router(_router, prefix="/api/v1")

# OpenAI-compatible endpoints keep their standard paths (/v1/...)
app.include_router(openai_api.router)


@app.get("/")
async def root():
    """Root endpoint returning service info.

    version stays "2.1" for backward compatibility with existing clients;
    edition reflects the 3.0 platform.
    """
    return {"name": "ModelForge", "version": "2.1", "edition": "3.0", "status": "ok"}


@app.get("/healthz")
async def healthz():
    """Health check for Docker/k8s."""
    return {"status": "ok"}