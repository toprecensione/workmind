"""SkillScheduler — gestione APScheduler per le skill pianificate."""
from __future__ import annotations
from typing import Optional
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = structlog.get_logger()

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Europe/Rome")
    return _scheduler


async def start_scheduler() -> None:
    """Avviato all'startup di FastAPI."""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        log.info("skill_scheduler_started")


async def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        log.info("skill_scheduler_stopped")


async def reload_skill_jobs(db_factory) -> None:
    """
    Ricarica tutti i job schedulati dal DB.
    Chiamato all'avvio e ogni volta che una skill viene abilitata/disabilitata.
    db_factory: callable async che produce AsyncSession
    """
    from app.services.skills.implementations import get_skill_jobs
    sched = get_scheduler()

    # Rimuovi job esistenti (prefisso "skill_")
    for job in sched.get_jobs():
        if job.id.startswith("skill_"):
            job.remove()

    async with db_factory() as db:  # db_factory is async_sessionmaker
        jobs = await get_skill_jobs(db)
        await db.close()

    for job_def in jobs:
        try:
            sched.add_job(
                job_def["func"],
                trigger=job_def["trigger"],
                id=job_def["id"],
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            log.info("skill_job_scheduled", job_id=job_def["id"])
        except Exception as exc:
            log.error("skill_job_schedule_error", job_id=job_def.get("id"), error=str(exc))
