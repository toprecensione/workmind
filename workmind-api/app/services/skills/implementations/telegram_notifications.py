"""Skill: telegram_notifications — riepilogo giornaliero + notifiche."""
from __future__ import annotations
from app.services.skills.implementations.daily_report import make_daily_report_job
# Il riepilogo giornaliero è gestito da daily_report.
# Questa skill aggiunge notifiche realtime sulle vendite (chiamata da webhook).

import structlog
log = structlog.get_logger()


def make_telegram_notifications_job(org_id: str, cfg: dict):
    """Usa daily_report come job giornaliero."""
    return make_daily_report_job(org_id, cfg)


async def notify_new_sale(db, org_id: str, product_name: str, quantity: int, agent_name: str):
    """Chiamata dal route /sales quando viene registrata una vendita."""
    from app.services.connectors import get_connector_registry
    from app.db.models import Skill
    from sqlalchemy import select

    skill_r = await db.execute(
        select(Skill).where(
            Skill.org_id == org_id,
            Skill.skill_id == "telegram_notifications",
            Skill.is_enabled,
        )
    )
    skill = skill_r.scalar_one_or_none()
    if not skill or not skill.config_json.get("new_sale_notification"):
        return

    reg = get_connector_registry()
    tg = await reg.get_config(db, org_id, "telegram")
    if not tg or not tg.get("chat_id_default"):
        return

    msg = f"🛒 *Nuova vendita* — {product_name} x{quantity}\n👤 Operatore: {agent_name}"
    from app.services.skills.implementations.low_stock_alert import _send_telegram
    await _send_telegram(tg["bot_token"], tg["chat_id_default"], msg)
