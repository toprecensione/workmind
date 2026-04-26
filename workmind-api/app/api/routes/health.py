"""Health checks and Prometheus metrics."""
from __future__ import annotations

import time
import os
import platform
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    Counter, Histogram, Gauge, Info,
    generate_latest, CONTENT_TYPE_LATEST,
)
from sqlalchemy import text

router = APIRouter(tags=["health"])

# ── Uptime tracking ─────────────────────────────────────────────────────────
_start_time: float = time.time()

# ── Prometheus metrics ──────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "workmind_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "workmind_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
ACTIVE_CONNECTIONS = Gauge("workmind_active_connections", "Active HTTP connections")
DB_POOL_SIZE = Gauge("workmind_db_pool_size", "SQLAlchemy DB pool size")
AI_CALLS_TOTAL = Counter(
    "workmind_ai_calls_total",
    "Total AI API calls",
    ["provider", "model_role", "status"],
)
AI_TOKENS_TOTAL = Counter(
    "workmind_ai_tokens_total",
    "Total AI tokens used",
    ["provider", "direction"],  # direction: input/output
)
AI_COST_TOTAL = Counter(
    "workmind_ai_cost_usd_total",
    "Total AI cost in USD",
    ["provider"],
)
DOCUMENTS_INDEXED = Gauge("workmind_documents_indexed_total", "Total indexed documents")
CELERY_TASKS_TOTAL = Counter(
    "workmind_celery_tasks_total",
    "Total Celery tasks",
    ["task_name", "status"],
)
APP_INFO = Info("workmind_app", "WorkMind application info")
APP_INFO.info({
    "version": "2.0.0",
    "environment": os.getenv("WORKMIND_ENV", "development"),
    "python": platform.python_version(),
})

START_TIME = time.time()
UPTIME = Gauge("workmind_uptime_seconds", "Application uptime in seconds")


def update_uptime():
    UPTIME.set(time.time() - START_TIME)


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/health", summary="Liveness probe")
async def liveness():
    """Always returns 200 if the process is alive."""
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1)}


@router.get("/health/ready", summary="Readiness probe")
async def readiness(request: Request):
    """Returns 200 only if DB and Redis are reachable."""
    from app.db.engine import get_engine
    import redis.asyncio as aioredis
    from app.config import get_settings

    checks: dict[str, Any] = {}
    healthy = True

    # PostgreSQL check
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {str(e)[:80]}"
        healthy = False

    # Redis check
    try:
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:80]}"
        healthy = False

    # Ollama check (non-fatal: embedder falls back gracefully)
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=3) as _c:
            _r = await _c.get(f"{settings.ollama_base_url}/api/tags")
        checks["ollama"] = "ok" if _r.status_code == 200 else f"http {_r.status_code}"
    except Exception as e:
        checks["ollama"] = f"unreachable: {str(e)[:60]}"
        # Ollama down → degraded but not fatal (no embedding new docs)

    # KB chunks available
    try:
        from app.db.engine import get_engine
        from sqlalchemy import text as _text
        engine = get_engine()
        async with engine.connect() as conn:
            row = await conn.execute(_text("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL"))
            n = row.scalar()
        checks["kb_chunks"] = n
    except Exception:
        checks["kb_chunks"] = "error"

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "service": "workmind-api",
            "checks": checks,
            "uptime_seconds": round(time.time() - START_TIME, 1),
        },
    )


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(request: Request):
    """Prometheus metrics endpoint. Restricted to internal network."""
    # Only allow Tailscale/localhost
    client_ip = request.client.host if request.client else ""
    allowed = client_ip.startswith(("127.", "100."))  # localhost + Tailscale CGNAT
    if not allowed:
        from fastapi import HTTPException
        raise HTTPException(403, "metrics only accessible from internal network")

    update_uptime()
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
