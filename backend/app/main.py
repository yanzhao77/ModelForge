"""ModelForge 3.0 FastAPI Backend.

Wires all API routers and injects service singletons on startup (2.1 features
stay untouched; the 3.0 Agent Runtime is layered on top).
"""
import hmac
from contextlib import asynccontextmanager

from api import (
    providers,
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
    tasks,
    train,
)
from core.config import settings
from core.database import init_db
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from services.agent_engine import get_engine
from services.agent_runtime_service import build_agent_runtime, init_agent_runtime
from services.knowledge_base import get_global_kb
from services.plugin_manager import get_manager
from services.runtime_registry import get_runtime
from services.task_execution import RetryTaskMonitor
from services.task_realtime import task_outbox_publisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and inject service singletons."""
    init_db()
    task_outbox_publisher.start()
    task_retry_monitor.start()
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
        task_retry_monitor.stop()
        task_outbox_publisher.stop()
        await agent_runtime.shutdown()



task_retry_monitor = RetryTaskMonitor(nudge=task_outbox_publisher.nudge)
app = FastAPI(title="ModelForge", version="3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    allow_credentials=True,
)

@app.middleware("http")
async def csrf_protect_cookie_session(request: Request, call_next):
    """Require a nonce for unsafe browser-cookie requests; Bearer clients remain compatible."""
    unsafe = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    exempt = {"/api/v1/auth/login", "/api/v1/auth/register"}
    has_cookie_session = bool(request.cookies.get(settings.session_cookie_name))
    has_bearer = bool(request.headers.get("Authorization"))
    if unsafe and request.url.path.startswith("/api/v1/") and request.url.path not in exempt and has_cookie_session and not has_bearer:
        provided = request.headers.get("X-CSRF-Token", "")
        expected = request.cookies.get(settings.csrf_cookie_name, "")
        if not expected or not provided or not hmac.compare_digest(provided, expected):
            return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
    return await call_next(request)

for _router in (
    auth.router,
    datasets.router,
    models.router,
    providers.router,
    runtime.router,
    chat.router,
    sessions.router,
    memories.router,
    agent.router,
    knowledge.router,
    plugin.router,
    train.router,
    system.router,
    tasks.router,
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
