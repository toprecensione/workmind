"""Maintenance tasks: stale conversation cleanup, daily backup."""
from __future__ import annotations
import asyncio
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.maintenance.close_stale_conversations")
def close_stale_conversations(inactive_hours: int = 24):
    """
    Mark conversations inactive if no messages in the last `inactive_hours` hours.
    Skips conversations that are already inactive.
    """
    async def _run():
        from app.config import get_settings
        from app.db.models import Conversation
        from sqlalchemy import select, update
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        settings = get_settings()
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=inactive_hours)

        async with SessionLocal() as db:
            # Find conversations with last message before cutoff
            stale_result = await db.execute(
                select(Conversation.id).where(
                    Conversation.is_active == True,  # noqa: E712
                    Conversation.updated_at < cutoff,
                )
            )
            stale_ids = [row[0] for row in stale_result.all()]

            if not stale_ids:
                logger.info("close_stale_conversations: no stale conversations")
                return {"closed": 0}

            await db.execute(
                update(Conversation)
                .where(Conversation.id.in_(stale_ids))
                .values(is_active=False)
            )
            await db.commit()

        await engine.dispose()
        logger.info("close_stale_conversations: closed %d conversations", len(stale_ids))
        return {"closed": len(stale_ids)}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


@shared_task(name="app.tasks.maintenance.daily_backup")
def daily_backup():
    """
    Run pg_dump → gzip → save to backups dir.
    Keeps last 7 daily backups.
    """
    from app.config import get_settings
    settings = get_settings()

    # Parse DB URL for pg_dump
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    backup_dir = os.environ.get("WORKMIND_BACKUP_DIR", "/home/emanuele/workmind-v2/backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"workmind_auto_{ts}.dump"
    filepath = os.path.join(backup_dir, filename)

    try:
        result = subprocess.run(
            ["pg_dump", "--format=custom", "--no-password", db_url, "--file", filepath],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error("daily_backup pg_dump failed: %s", result.stderr[:500])
            return {"status": "failed", "error": result.stderr[:200]}

        size = os.path.getsize(filepath)
        logger.info("daily_backup: saved %s (%d bytes)", filename, size)

        # Prune old auto backups — keep 7 most recent
        auto_backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("workmind_auto_")],
            reverse=True,
        )
        for old in auto_backups[7:]:
            try:
                os.unlink(os.path.join(backup_dir, old))
                logger.info("daily_backup: pruned %s", old)
            except OSError:
                pass

        return {"status": "success", "filename": filename, "size_bytes": size}

    except subprocess.TimeoutExpired:
        logger.error("daily_backup: pg_dump timed out")
        return {"status": "failed", "error": "timeout"}
    except Exception as exc:
        logger.error("daily_backup: unexpected error: %s", exc)
        return {"status": "failed", "error": str(exc)}
