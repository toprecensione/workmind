"""
WorkMind API — Admin System Routes
GET /api/admin/system/status   — health of all subsystems
GET /api/admin/system/metrics  — CPU / RAM / disk metrics
GET /api/admin/system/overview — aggregate DB statistics
"""
from __future__ import annotations

import asyncio
import shutil
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.health import _start_time
from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import (
    Conversation,
    Document,
    DocumentChunk,
    Memory,
    Message,
    User,
)
from app.dependencies import AdminUser

log = structlog.get_logger("workmind.admin_system")
router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _disk_info() -> dict[str, Any]:
    """Return disk usage for / — no psutil needed."""
    usage = shutil.disk_usage("/")
    used_pct = usage.used / usage.total * 100
    if used_pct >= 90:
        disk_status = "critical"
    elif used_pct >= 75:
        disk_status = "warning"
    else:
        disk_status = "ok"
    return {
        "status": disk_status,
        "used_pct": round(used_pct, 1),
        "used_gb": round(usage.used / 1024**3, 2),
        "total_gb": round(usage.total / 1024**3, 2),
    }


def _cpu_ram_from_proc() -> dict[str, float]:
    """
    Read CPU and RAM from /proc/stat and /proc/meminfo as a fallback
    when psutil is not installed. Takes a 100ms CPU sample.
    Returns cpu_pct, ram_pct, ram_used_gb, ram_total_gb.
    """
    # CPU — two samples 100ms apart
    def _read_cpu_times() -> tuple[int, int]:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()
        total = sum(int(x) for x in parts[1:])
        idle = int(parts[4])
        return idle, total

    idle1, total1 = _read_cpu_times()
    time.sleep(0.1)
    idle2, total2 = _read_cpu_times()
    delta_total = total2 - total1
    delta_idle = idle2 - idle1
    cpu_pct = 0.0 if delta_total == 0 else (1.0 - delta_idle / delta_total) * 100

    # RAM
    mem: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for raw in f:
                key, val_unit = raw.split(":", 1)
                mem[key.strip()] = int(val_unit.split()[0])
    except Exception:
        return {"cpu_pct": round(cpu_pct, 1), "ram_pct": 0.0, "ram_used_gb": 0.0, "ram_total_gb": 0.0}

    total_kb = mem.get("MemTotal", 0)
    available_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
    used_kb = total_kb - available_kb
    ram_pct = (used_kb / total_kb * 100) if total_kb else 0.0
    return {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(ram_pct, 1),
        "ram_used_gb": round(used_kb / 1024**2, 2),
        "ram_total_gb": round(total_kb / 1024**2, 2),
    }


def _collect_metrics_blocking() -> dict[str, Any]:
    """Blocking metrics collection — run via asyncio.to_thread."""
    disk = shutil.disk_usage("/")
    disk_used_gb = round(disk.used / 1024**3, 2)
    disk_total_gb = round(disk.total / 1024**3, 2)
    disk_pct = round(disk.used / disk.total * 100, 1)

    try:
        import psutil  # type: ignore[import-not-found]
        cpu_pct = round(psutil.cpu_percent(interval=0.1), 1)
        vm = psutil.virtual_memory()
        ram_pct = round(vm.percent, 1)
        ram_used_gb = round(vm.used / 1024**3, 2)
        ram_total_gb = round(vm.total / 1024**3, 2)
    except ImportError:
        proc_data = _cpu_ram_from_proc()
        cpu_pct = proc_data["cpu_pct"]
        ram_pct = proc_data["ram_pct"]
        ram_used_gb = proc_data["ram_used_gb"]
        ram_total_gb = proc_data["ram_total_gb"]

    return {
        "cpu_pct": cpu_pct,
        "ram_pct": ram_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_pct": disk_pct,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/system/status")
async def get_system_status(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Full subsystem health check. Admin only."""

    uptime = round(time.time() - _start_time)

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    pg_status: dict[str, Any] = {}
    try:
        from sqlalchemy import text as sa_text
        t0 = time.monotonic()
        await db.execute(sa_text("SELECT 1"))
        pg_latency = round((time.monotonic() - t0) * 1000, 1)
        pg_status = {"status": "ok", "latency_ms": pg_latency}
    except Exception as exc:
        log.warning("system_status_postgres_failed", error=str(exc))
        pg_status = {"status": "error", "latency_ms": None}

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_status: dict[str, Any] = {}
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]
        r = aioredis.from_url(settings.redis_url, socket_timeout=2)
        t0 = time.monotonic()
        await r.ping()
        r_latency = round((time.monotonic() - t0) * 1000, 1)
        await r.aclose()
        redis_status = {"status": "ok", "latency_ms": r_latency}
    except ImportError:
        redis_status = {"status": "disabled", "latency_ms": None}
    except Exception as exc:
        log.warning("system_status_redis_failed", error=str(exc))
        redis_status = {"status": "error", "latency_ms": None}

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_status: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                ollama_status = {
                    "status": "ok",
                    "model": settings.ollama_embed_model,
                }
            else:
                ollama_status = {"status": "error", "model": settings.ollama_embed_model}
    except Exception as exc:
        log.warning("system_status_ollama_failed", error=str(exc))
        ollama_status = {"status": "error" if settings.local_llm_enabled else "disabled", "model": settings.ollama_embed_model}

    # ── Disk ──────────────────────────────────────────────────────────────────
    disk_info = await asyncio.to_thread(_disk_info)

    return {
        "api": {"status": "ok", "uptime_seconds": uptime},
        "postgres": pg_status,
        "redis": redis_status,
        "ollama": ollama_status,
        "disk": disk_info,
    }


@router.get("/system/metrics")
async def get_system_metrics(
    user: AdminUser,
) -> dict[str, Any]:
    """System resource usage (CPU, RAM, disk). Admin only."""
    return await asyncio.to_thread(_collect_metrics_blocking)


@router.get("/system/overview")
async def get_system_overview(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Aggregate statistics from the database. Admin only."""

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Active users
    active_users_res = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == user.org_id,
            User.is_active,
        )
    )
    active_users = active_users_res.scalar() or 0

    # Total documents
    total_docs_res = await db.execute(
        select(func.count(Document.id)).where(Document.org_id == user.org_id)
    )
    total_documents = total_docs_res.scalar() or 0

    # Documents indexed
    docs_indexed_res = await db.execute(
        text("SELECT count(id) FROM documents WHERE org_id = :org_id AND status = 'indexed'"),
        {"org_id": user.org_id},
    )
    documents_indexed = docs_indexed_res.scalar() or 0

    # Documents failed
    docs_failed_res = await db.execute(
        text("SELECT count(id) FROM documents WHERE org_id = :org_id AND status = 'failed'"),
        {"org_id": user.org_id},
    )
    documents_failed = docs_failed_res.scalar() or 0

    # Conversations today
    convs_today_res = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.org_id == user.org_id,
            Conversation.created_at >= today_start,
        )
    )
    conversations_today = convs_today_res.scalar() or 0

    # Messages today (join through conversation)
    msgs_today_res = await db.execute(
        select(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.org_id == user.org_id,
            Message.created_at >= today_start,
        )
    )
    messages_today = msgs_today_res.scalar() or 0

    # KB chunks
    kb_chunks_res = await db.execute(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.org_id == user.org_id
        )
    )
    kb_chunks = kb_chunks_res.scalar() or 0

    # Memories
    memories_res = await db.execute(
        select(func.count(Memory.id)).where(
            Memory.org_id == user.org_id,
        )
    )
    memories = memories_res.scalar() or 0

    return {
        "active_users": active_users,
        "total_documents": total_documents,
        "documents_indexed": documents_indexed,
        "documents_failed": documents_failed,
        "conversations_today": conversations_today,
        "messages_today": messages_today,
        "kb_chunks": kb_chunks,
        "memories": memories,
    }
