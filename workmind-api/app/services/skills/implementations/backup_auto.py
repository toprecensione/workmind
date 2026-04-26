"""Skill: backup_auto — backup automatico PostgreSQL."""
from __future__ import annotations
import asyncio
import os
import subprocess
from datetime import datetime
import structlog

from app.config import get_settings
from app.services.connectors import get_connector_registry
from app.services.skills.implementations.low_stock_alert import _send_telegram, _send_email
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

log = structlog.get_logger()


def make_backup_job(org_id: str, cfg: dict):
    async def run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            backup_cfg = await get_connector_registry().get_config(db, org_id, "backup")
        await engine.dispose()
        if not backup_cfg:
            return
        await _run_backup(org_id, cfg, backup_cfg, settings)
    return run


async def _run_backup(org_id: str, skill_cfg: dict, backup_cfg: dict, settings):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    backup_path = backup_cfg.get("backup_path", "/home/emanuele/workmind-v2/backups")
    os.makedirs(backup_path, exist_ok=True)
    filename = os.path.join(backup_path, f"workmind_backup_{ts}.sql.gz")

    # Esegui pg_dump
    db_url = settings.database_url.replace("+asyncpg", "")
    cmd = f"pg_dump {db_url} | gzip > {filename}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        size_mb = os.path.getsize(filename) / 1024 / 1024
        msg = f"✅ *Backup completato*\n📁 {filename}\n📦 {size_mb:.2f} MB\n🕐 {ts}"
        # Pulizia retention
        await asyncio.to_thread(_cleanup_old_backups, backup_path, int(backup_cfg.get("retention_days", 30)))
    else:
        msg = f"❌ *Backup fallito*\n```{result.stderr[:300]}```"

    # Notifiche
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        reg = get_connector_registry()
        if skill_cfg.get("notify_telegram", True):
            tg = await reg.get_config(db, org_id, "telegram")
            if tg and tg.get("chat_id_default"):
                await _send_telegram(tg["bot_token"], tg["chat_id_default"], msg)
        if skill_cfg.get("notify_email") and skill_cfg.get("notify_email_to"):
            smtp = await reg.get_config(db, org_id, "smtp")
            if smtp:
                await asyncio.to_thread(_send_email, smtp, skill_cfg["notify_email_to"], "WorkMind Backup", msg)
    await engine.dispose()


def _cleanup_old_backups(backup_path: str, retention_days: int):
    import glob
    import time
    pattern = os.path.join(backup_path, "workmind_backup_*.sql.gz")
    cutoff = time.time() - retention_days * 86400
    for f in glob.glob(pattern):
        if os.path.getmtime(f) < cutoff:
            os.remove(f)
            log.info("backup_cleaned", file=f)
