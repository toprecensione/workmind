"""Raccoglie tutti i job delle skill abilitate dal DB."""
from __future__ import annotations
from typing import Any
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.db.models import Skill

log = structlog.get_logger()


async def get_skill_jobs(db: AsyncSession) -> list[dict[str, Any]]:
    """Ritorna lista di job da aggiungere allo scheduler, uno per ogni skill abilitata."""
    from app.services.skills.implementations.low_stock_alert import make_low_stock_job
    from app.services.skills.implementations.daily_report import make_daily_report_job
    from app.services.skills.implementations.backup_auto import make_backup_job
    from app.services.skills.implementations.telegram_notifications import make_telegram_notifications_job
    from app.services.skills.implementations.email_reader import make_email_reader_job
    from app.services.skills.implementations.email_alerts import make_email_alerts_job
    from app.services.skills.implementations.github_issues import make_github_issues_job

    result = await db.execute(select(Skill).where(Skill.is_enabled))
    enabled_skills = result.scalars().all()

    jobs = []
    for skill in enabled_skills:
        cfg = skill.config_json or {}
        org_id = str(skill.org_id)
        try:
            match skill.skill_id:
                case "low_stock_alert":
                    hours = int(cfg.get("check_interval_hours", 4))
                    jobs.append({
                        "id": f"skill_low_stock_{org_id}",
                        "func": make_low_stock_job(org_id, cfg),
                        "trigger": IntervalTrigger(hours=hours),
                    })
                case "daily_report":
                    hour = int(cfg.get("send_hour", 8))
                    jobs.append({
                        "id": f"skill_daily_report_{org_id}",
                        "func": make_daily_report_job(org_id, cfg),
                        "trigger": CronTrigger(hour=hour, minute=0),
                    })
                case "backup_auto":
                    jobs.append({
                        "id": f"skill_backup_{org_id}",
                        "func": make_backup_job(org_id, cfg),
                        "trigger": CronTrigger(hour=2, minute=0),  # overridden by connector config
                    })
                case "telegram_notifications":
                    if cfg.get("daily_summary_enabled", True):
                        hour = int(cfg.get("daily_summary_hour", 8))
                        jobs.append({
                            "id": f"skill_tg_summary_{org_id}",
                            "func": make_telegram_notifications_job(org_id, cfg),
                            "trigger": CronTrigger(hour=hour, minute=5),
                        })
                case "email_reader":
                    mins = int(cfg.get("check_interval_minutes", 15))
                    jobs.append({
                        "id": f"skill_email_reader_{org_id}",
                        "func": make_email_reader_job(org_id, cfg),
                        "trigger": IntervalTrigger(minutes=mins),
                    })
                case "telegram_commands":
                    # No scheduled job — handled via webhook
                    pass
                case "telegram_voice":
                    # No scheduled job — handled via webhook
                    pass
                case "email_alerts":
                    alert_type = cfg.get("alert_type", "stock")
                    if alert_type == "weekly":
                        day = int(cfg.get("weekly_report_day", 0))
                        jobs.append({
                            "id": f"skill_email_alerts_{org_id}",
                            "func": make_email_alerts_job(org_id, cfg),
                            "trigger": CronTrigger(day_of_week=day, hour=8, minute=0),
                        })
                    else:
                        hours = int(cfg.get("check_interval_hours", 4))
                        jobs.append({
                            "id": f"skill_email_alerts_{org_id}",
                            "func": make_email_alerts_job(org_id, cfg),
                            "trigger": IntervalTrigger(hours=hours),
                        })
                case "whatsapp_chat":
                    # No scheduled job — handled via webhook
                    pass
                case "github_issues":
                    hours = int(cfg.get("check_interval_hours", 24))
                    jobs.append({
                        "id": f"skill_github_issues_{org_id}",
                        "func": make_github_issues_job(org_id, cfg),
                        "trigger": IntervalTrigger(hours=hours),
                    })
        except Exception as exc:
            log.error("skill_job_build_error", skill_id=skill.skill_id, error=str(exc))

    return jobs
