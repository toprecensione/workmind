"""Celery application factory."""
from celery import Celery
from celery.schedules import crontab
from app.config import get_settings


def make_celery() -> Celery:
    s = get_settings()
    app = Celery(
        "workmind",
        include=["app.tasks.kb", "app.tasks.medic", "app.tasks.telegram_poll", "app.tasks.maintenance"],
    )
    app.conf.update(
        broker_url=s.celery_broker_url,
        result_backend=s.celery_result_backend,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Europe/Rome",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        beat_schedule={
            "low-stock-check": {
                "task": "app.tasks.medic.check_low_stock",
                "schedule": 3600.0,  # every hour
            },
            "kb-scan-watch-paths": {
                "task": "app.tasks.kb.scan_watch_paths",
                "schedule": 1800.0,  # every 30 min
            },
            "telegram-poll": {
                "task": "app.tasks.telegram_poll.poll_updates",
                "schedule": 30.0,  # every 30s (long-poll inside handles timing)
            },
            "close-stale-conversations": {
                "task": "app.tasks.maintenance.close_stale_conversations",
                "schedule": crontab(minute=0, hour="*/6"),  # every 6h
            },
            "daily-backup": {
                "task": "app.tasks.maintenance.daily_backup",
                "schedule": crontab(minute=30, hour=2),  # 02:30 Europe/Rome
            },
        },
    )
    return app


celery_app = make_celery()
