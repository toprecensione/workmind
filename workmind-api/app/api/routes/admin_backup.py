"""
WorkMind API — Admin Backup Routes
GET  /api/admin/backup                  — list last 20 backups
POST /api/admin/backup/trigger          — start pg_dump in background
GET  /api/admin/backup/{backup_id}/status — status of a specific backup
"""
from __future__ import annotations

import asyncio
import os
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session, get_session_factory
from app.db.models import BackupLog
from app.dependencies import AdminUser

log = structlog.get_logger("workmind.admin_backup")
router = APIRouter()

BACKUP_DIR = Path("/home/emanuele/workmind-v2/backups")


# ── Background task ────────────────────────────────────────────────────────────

async def _run_pg_dump(
    backup_id: uuid.UUID,
    org_id: uuid.UUID,
    db_url: str,
    backup_dir: Path,
    filename: str,
) -> None:
    """Execute pg_dump and update BackupLog with result."""
    file_path = backup_dir / filename
    started = time.monotonic()

    # Convert asyncpg URL to plain PostgreSQL URL for pg_dump
    pg_url = db_url
    for asyncpg_prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if pg_url.startswith(asyncpg_prefix):
            pg_url = "postgresql://" + pg_url[len(asyncpg_prefix):]
            break

    # Parse connection parts to build pg_dump arguments
    parsed = urllib.parse.urlparse(pg_url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or ""
    password = parsed.password or ""
    dbname = parsed.path.lstrip("/")

    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        "pg_dump",
        f"--host={host}",
        f"--port={port}",
        f"--username={user}",
        f"--dbname={dbname}",
        f"--file={str(file_path)}",
        "--format=custom",
        "--no-password",
    ]

    log.info(
        "pg_dump_started",
        backup_id=str(backup_id),
        file=str(file_path),
        host=host,
        dbname=dbname,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        duration_s = round(time.monotonic() - started)

        if proc.returncode == 0:
            size_bytes = file_path.stat().st_size if file_path.exists() else None
            final_status = "success"
            error_msg = None
            log.info("pg_dump_success", backup_id=str(backup_id), duration_s=duration_s, size_bytes=size_bytes)
        else:
            size_bytes = None
            final_status = "failed"
            error_msg = stderr.decode(errors="replace")[:2000]
            log.error("pg_dump_failed", backup_id=str(backup_id), stderr=error_msg)
    except Exception as exc:
        duration_s = round(time.monotonic() - started)
        size_bytes = None
        final_status = "failed"
        error_msg = str(exc)
        log.error("pg_dump_exception", backup_id=str(backup_id), error=error_msg)

    # Update the BackupLog record with a fresh session
    try:
        session_factory = get_session_factory()
        async with session_factory() as fresh_db:
            result = await fresh_db.execute(
                select(BackupLog).where(BackupLog.id == backup_id)
            )
            bl = result.scalar_one_or_none()
            if bl:
                bl.status = final_status
                bl.size_bytes = size_bytes
                bl.duration_s = duration_s
                bl.error_msg = error_msg
                bl.completed_at = datetime.now(timezone.utc)
                await fresh_db.commit()
    except Exception as exc:
        log.error("backup_log_update_failed", backup_id=str(backup_id), error=str(exc))


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/backup")
async def list_backups(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List the 20 most recent backups for this organisation."""
    result = await db.execute(
        select(BackupLog)
        .where(BackupLog.org_id == user.org_id)
        .order_by(BackupLog.created_at.desc())
        .limit(20)
    )
    backups = result.scalars().all()
    return [
        {
            "id": str(bl.id),
            "filename": bl.filename,
            "file_path": bl.file_path,
            "size_bytes": bl.size_bytes,
            "status": bl.status,
            "error_msg": bl.error_msg,
            "duration_s": bl.duration_s,
            "triggered_by": str(bl.triggered_by) if bl.triggered_by else None,
            "created_at": bl.created_at.isoformat(),
            "completed_at": bl.completed_at.isoformat() if bl.completed_at else None,
        }
        for bl in backups
    ]


@router.post("/backup/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_backup(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Trigger a pg_dump backup in the background."""

    # Ensure backup directory exists
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.error("backup_dir_create_failed", path=str(BACKUP_DIR), error=str(exc))
        raise HTTPException(status_code=500, detail=f"Cannot create backup directory: {exc}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"workmind_backup_{timestamp}.dump"
    file_path = str(BACKUP_DIR / filename)

    bl = BackupLog(
        org_id=user.org_id,
        filename=filename,
        file_path=file_path,
        status="running",
        triggered_by=user.user_id,
    )
    db.add(bl)
    await db.commit()
    await db.refresh(bl)

    backup_id = bl.id
    log.info("backup_triggered", backup_id=str(backup_id), filename=filename, triggered_by=str(user.user_id))

    asyncio.create_task(
        _run_pg_dump(
            backup_id=backup_id,
            org_id=user.org_id,
            db_url=settings.database_url,
            backup_dir=BACKUP_DIR,
            filename=filename,
        )
    )

    return {"backup_id": str(backup_id), "status": "queued"}


@router.get("/backup/{backup_id}/status")
async def get_backup_status(
    backup_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get the status of a specific backup job."""
    result = await db.execute(
        select(BackupLog).where(
            BackupLog.id == backup_id,
            BackupLog.org_id == user.org_id,
        )
    )
    bl = result.scalar_one_or_none()
    if not bl:
        raise HTTPException(status_code=404, detail="Backup non trovato")

    return {
        "id": str(bl.id),
        "filename": bl.filename,
        "file_path": bl.file_path,
        "size_bytes": bl.size_bytes,
        "status": bl.status,
        "error_msg": bl.error_msg,
        "duration_s": bl.duration_s,
        "triggered_by": str(bl.triggered_by) if bl.triggered_by else None,
        "created_at": bl.created_at.isoformat(),
        "completed_at": bl.completed_at.isoformat() if bl.completed_at else None,
    }
