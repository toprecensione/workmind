"""
WorkMind API — FastAPI Application Factory
Production-ready with lifespan management, structured logging, CORS (internal only),
and versioned API router registration.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.deps.limiter import limiter

from app.config import get_settings
from app.db.engine import close_db_engine, init_db_engine
from app.api.routes import health, chat, teach, conversations, admin, auth, auth_reset, auth_2fa
from app.api.routes.channels import telegram, whatsapp
from app.api.routes import admin_connectors, admin_skills, admin_users, admin_ai_actions
from app.api.routes import admin_system, admin_kb, admin_audit, admin_backup
from app.api.routes import kb as kb_route

# ── Structured logging setup ──────────────────────────────────────────────────

settings = get_settings()

log_renderer = (
    structlog.processors.JSONRenderer()
    if settings.log_format == "json"
    else structlog.dev.ConsoleRenderer()
)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        log_renderer,
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger("workmind.api")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown resources."""
    log.info(
        "WorkMind API starting",
        node_id=settings.workmind_node_id,
        profile=settings.workmind_profile.value,
        environment=settings.workmind_env.value,
    )

    # Initialize async PostgreSQL connection pool
    await init_db_engine(settings)
    log.info("Database engine initialized")

    # Start skill scheduler and load jobs from DB
    from app.services.skills import start_scheduler, reload_skill_jobs
    from app.db.engine import get_session_factory as _gsf
    await start_scheduler()
    try:
        await reload_skill_jobs(_gsf())
    except Exception as _exc:
        log.warning("skill_scheduler_reload_failed_at_startup", error=str(_exc))

    yield  # Application runs here

    # Graceful shutdown
    from app.services.skills import stop_scheduler
    await stop_scheduler()
    await close_db_engine()
    log.info("WorkMind API stopped cleanly")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    s = get_settings()

    app = FastAPI(
        title="WorkMind API",
        description="WorkMind Platform — Internal API. Not for public access.",
        version="2.0.0",
        docs_url="/docs" if not s.is_production else None,    # no Swagger in prod
        redoc_url="/redoc" if not s.is_production else None,
        openapi_url="/openapi.json" if not s.is_production else None,
        lifespan=lifespan,
    )

    # ── Rate limiting (SlowAPI) ───────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS: restrict to Tailscale domain and localhost ──────────────────────
    allowed_origins = [
        f"https://{s.workmind_node_id}.tail898ef4.ts.net",
        "http://localhost:3000",   # dev only
        "http://localhost:5173",   # Vite dev server
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", s.api_key_header],
    )

    # ── Request ID middleware ─────────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    # ── Security headers middleware ───────────────────────────────────────────
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    # ── Prometheus metrics middleware ─────────────────────────────────────────
    from app.api.routes.health import REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_CONNECTIONS

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        ACTIVE_CONNECTIONS.inc()
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        # Normalize path to avoid high cardinality from UUIDs / numeric IDs
        path = request.url.path
        segments = path.split("/")
        normalized = []
        for segment in segments:
            if len(segment) == 36 and segment.count("-") == 4:  # UUID
                normalized.append("{id}")
            elif segment.isdigit():
                normalized.append("{id}")
            else:
                normalized.append(segment)
        path = "/".join(normalized)
        REQUEST_COUNT.labels(
            method=request.method, endpoint=path, status=response.status_code
        ).inc()
        REQUEST_LATENCY.labels(method=request.method, endpoint=path).observe(duration)
        ACTIVE_CONNECTIONS.dec()
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.exception("unhandled_exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request.headers.get("X-Request-ID")},
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router, prefix="/api", tags=["auth"])
    app.include_router(auth_reset.router, prefix="/api", tags=["auth"])
    app.include_router(auth_2fa.router, prefix="/api", tags=["auth"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(teach.router, prefix="/api", tags=["knowledge"])
    app.include_router(conversations.router, prefix="/api", tags=["conversations"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    app.include_router(telegram.router, prefix="/api/channels", tags=["channels"])
    app.include_router(whatsapp.router, prefix="/api/channels", tags=["channels"])
    # ── Dynamic client router loader ─────────────────────────────────────
    # Each clients/<name>/routes.py with router + ROUTE_PREFIX is auto-loaded.
    # Add a new client: create clients/<name>/routes.py — no changes to main.py needed.
    import importlib
    from pathlib import Path
    _clients_dir = Path(__file__).parent.parent / 'clients'
    if _clients_dir.is_dir():
        for _cpkg in sorted(_clients_dir.iterdir()):
            if not _cpkg.is_dir() or _cpkg.name.startswith('_'):
                continue
            try:
                _cmod = importlib.import_module(f'clients.{_cpkg.name}.routes')
                _prefix = getattr(_cmod, 'ROUTE_PREFIX', f'/api/{_cpkg.name}')
                _sector = getattr(_cmod, 'SECTOR', _cpkg.name)
                app.include_router(_cmod.router, prefix=_prefix, tags=[_sector])
                log.info('client_router_loaded', client=_cpkg.name, prefix=_prefix)
            except (ImportError, AttributeError) as exc:
                log.warning('client_router_skip', client=_cpkg.name, reason=str(exc))
    app.include_router(admin_connectors.router, prefix="/api/admin", tags=["admin-connectors"])
    app.include_router(admin_skills.router, prefix="/api/admin", tags=["admin-skills"])
    app.include_router(admin_users.router, prefix="/api/admin", tags=["admin-users"])
    app.include_router(admin_ai_actions.router, prefix="/api/admin", tags=["admin-ai-actions"])
    app.include_router(admin_system.router, prefix="/api/admin", tags=["admin-system"])
    app.include_router(admin_kb.router, prefix="/api/admin", tags=["admin-kb"])
    app.include_router(admin_audit.router, prefix="/api/admin", tags=["admin-audit"])
    app.include_router(admin_backup.router, prefix="/api/admin", tags=["admin-backup"])
    app.include_router(kb_route.router, prefix="/api", tags=["knowledge-base"])

    # ── Static files (PWA) ────────────────────────────────────────────────────
    # In production, Nginx serves /static directly. This is the dev fallback.
    if not s.is_production:
        try:
            app.mount("/static", StaticFiles(directory="app/static"), name="static")
        except RuntimeError:
            pass  # static directory doesn't exist yet

    # ── SvelteKit SPA (served directly by FastAPI) ────────────────────────────
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse as _FileResponse

    _frontend = _Path(__file__).parent.parent.parent / "workmind-frontend" / "build"
    if _frontend.exists():
        _app_dir = _frontend / "_app"
        if _app_dir.exists():
            app.mount("/_app", StaticFiles(directory=str(_app_dir)), name="sveltekit_assets")

        @app.get("/{full_path:path}")
        async def _serve_spa(full_path: str):
            file_path = _frontend / full_path
            if file_path.is_file():
                return _FileResponse(str(file_path))
            return _FileResponse(str(_frontend / "index.html"))

    return app


app = create_app()
