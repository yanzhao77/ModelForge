"""ModelForge 3.0 FastAPI Backend.

Wires all API routers and injects service singletons on startup (2.1 features
stay untouched; the 3.0 Agent Runtime is layered on top).
"""
import hmac
from contextlib import asynccontextmanager

from api import (
    agent,
    agent_teams,
    agents,
    artifacts,
    attachments,
    auth,
    chat,
    dashboard,
    datasets,
    developer_api,
    goals,
    knowledge,
    learning,
    local_api,
    marketplace,
    memories,
    models,
    observability,
    openai_api,
    os_core,
    packages,
    platform_api,
    plugin,
    providers,
    runtime,
    runtimes,
    sandbox,
    sessions,
    system,
    tasks,
    train,
    videos,
    workflows,
    workspaces,
)
from core.api_contracts import correlation_id
from core.config import settings
from core.database import init_db
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from services.agent_engine import get_engine
from services.agent_runtime_service import build_agent_runtime, init_agent_runtime
from services.knowledge_base import get_global_kb
from services.plugin_manager import get_manager
from services.recovery_service import get_recovery_service
from services.runtime_registry import get_runtime
from services.task_execution import RetryTaskMonitor
from services.task_realtime import task_outbox_publisher
from services.video_generation_service import get_video_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and inject service singletons."""
    init_db()
    task_outbox_publisher.start()
    task_retry_monitor.start()
    get_video_queue().start()
    runtime.set_runtime(get_runtime())
    agent.set_agent_engine(get_engine())
    knowledge.set_knowledge_base(get_global_kb())
    plugin.set_plugin_manager(get_manager())

    # 3.0 Agent Runtime
    agent_runtime = build_agent_runtime()
    init_agent_runtime(agent_runtime)
    agent.set_agent_runtime(agent_runtime)
    # V1.9: one ordered recovery pass settles every subsystem that keeps its
    # executor in memory (models, downloads, training, agent/workflow runs,
    # API invocations) before the process starts serving.
    app.state.recovery_report = get_recovery_service().startup_recovery()
    agent_runtime.start()
    agent.restore_persistent_schedules()
    try:
        yield
    finally:
        task_retry_monitor.stop()
        get_video_queue().shutdown()
        task_outbox_publisher.stop()
        await agent_runtime.shutdown()



task_retry_monitor = RetryTaskMonitor(nudge=task_outbox_publisher.nudge)
app = FastAPI(title="ModelForge", version="3.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def openai_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert Pydantic validation errors to OpenAI-compatible error envelope for /v1/ paths."""
    # Only apply OpenAI error envelope to /v1/ paths
    if not request.url.path.startswith("/v1/"):
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, exc)

    correlation = correlation_id()[:64]
    errors = exc.errors()
    if errors:
        first_error = errors[0]
        loc = " -> ".join(str(x) for x in first_error.get("loc", []))
        msg = f"Invalid request: {first_error.get('msg', 'validation failed')} at {loc}"
    else:
        msg = "Invalid request: validation failed"

    def _openai_error(code: str, message: str, correlation: str) -> dict:
        return {
            "error": {
                "message": message,
                "type": "server_error",
                "code": code,
                "param": None,
            },
            "correlation_id": correlation,
        }

    return JSONResponse(
        _openai_error("REQUEST_INVALID", msg, correlation),
        status_code=422,
        headers={"X-Request-ID": correlation, "X-Correlation-ID": correlation},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-API-Key", "Idempotency-Key"],
    allow_credentials=True,
)

@app.middleware("http")
async def csrf_protect_cookie_session(request: Request, call_next):
    """Require a nonce for unsafe browser-cookie requests; Bearer clients remain compatible."""
    unsafe = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    exempt = {"/api/v1/auth/login", "/api/v1/auth/register"}
    has_cookie_session = bool(request.cookies.get(settings.session_cookie_name))
    has_bearer = bool(request.headers.get("Authorization"))
    # Cookie sessions authenticate the first-party /api/v1 control plane. The
    # external /v1 inference API requires a local API key and ignores cookies,
    # so CSRF protection is not the admission gate for that surface.
    covered = request.url.path.startswith("/api/v1/")
    if unsafe and covered and request.url.path not in exempt and has_cookie_session and not has_bearer:
        provided = request.headers.get("X-CSRF-Token", "")
        expected = request.cookies.get(settings.csrf_cookie_name, "")
        if not expected or not provided or not hmac.compare_digest(provided, expected):
            return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
    return await call_next(request)

for _router in (
    auth.router,
    dashboard.router,
    datasets.router,
    goals.router,
    learning.router,
    local_api.router,
    models.router,
    observability.router,
    os_core.router,
    providers.router,
    runtime.router,
    runtimes.router,
    chat.router,
    sandbox.router,
    sessions.router,
    memories.router,
    packages.router,
    agent.router,
    agent_teams.router,
    agents.router,
    artifacts.router,
    attachments.router,
    knowledge.router,
    marketplace.router,
    plugin.router,
    train.router,
    system.router,
    tasks.router,
    videos.desktop_router,
    workspaces.router,
    workflows.router,
):
    app.include_router(_router, prefix="/api/v1")

# OpenAI-compatible endpoints keep their standard paths (/v1/...)
app.include_router(openai_api.router)
app.include_router(developer_api.router)
app.include_router(videos.router)
# Commercial API control-plane and project-key invocation surface.
app.include_router(platform_api.router, prefix="/api/v2")


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
