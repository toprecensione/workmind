"""Email alerts skill — periodic stock + report emails via SMTP."""
from __future__ import annotations
import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


async def send_email(smtp_cfg: dict, to: str, subject: str, body: str) -> bool:
    import asyncio
    import smtplib
    import ssl
    from email.mime.text import MIMEText

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = smtp_cfg.get("from_address") or smtp_cfg.get("username", "")
    msg["To"] = to
    msg["Subject"] = subject

    def _send():
        ctx = ssl.create_default_context()
        port = int(smtp_cfg.get("port", 465))
        if port == 587:
            with smtplib.SMTP(smtp_cfg["host"], port, timeout=15) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.login(smtp_cfg["username"], smtp_cfg["password"])
                s.sendmail(msg["From"], [to], msg.as_string())
        else:
            with smtplib.SMTP_SSL(smtp_cfg["host"], port, context=ctx, timeout=15) as s:
                s.login(smtp_cfg["username"], smtp_cfg["password"])
                s.sendmail(msg["From"], [to], msg.as_string())

    try:
        await asyncio.to_thread(_send)
        return True
    except Exception as e:
        logger.error(f"SMTP send failed: {e}")
        return False


async def run_stock_alert_email(org_id: str, config: dict, db: Any) -> dict:
    """Send low-stock alert email to configured recipients."""
    from sqlalchemy import select
    from app.db.models import MedicProduct
    from app.services.connectors import get_connector_registry
    from uuid import UUID

    result = await db.execute(
        select(MedicProduct).where(
            MedicProduct.org_id == UUID(org_id),
            MedicProduct.is_active,
        )
    )
    products = result.scalars().all()
    low = [p for p in products if p.stock_qty <= p.low_stock_threshold]

    if not low:
        return {"sent": 0, "reason": "no low stock items"}

    lines = ["⚠️ Prodotti con stock basso:\n"]
    for p in low:
        lines.append(f"• {p.name}: {p.stock_qty} {p.unit} (soglia: {p.low_stock_threshold})")
    body = "\n".join(lines)

    recipients = config.get("recipients", [])
    if isinstance(recipients, str):
        recipients = [recipients]
    # Also support single alert_email field
    alert_email = config.get("alert_email", "")
    if alert_email and alert_email not in recipients:
        recipients.append(alert_email)

    smtp_cfg = await get_connector_registry().get_config(db, org_id, "smtp")
    if not smtp_cfg or not recipients:
        return {"sent": 0, "reason": "no smtp config or recipients"}

    sent = 0
    for addr in recipients:
        ok = await send_email(smtp_cfg, addr, f"⚠️ Stock basso WorkMind — {date.today()}", body)
        if ok:
            sent += 1
    return {"sent": sent, "low_count": len(low)}


async def run_weekly_report_email(org_id: str, config: dict, db: Any) -> dict:
    """Send weekly sales summary email."""
    from sqlalchemy import select, func
    from app.db.models import MedicSale
    from app.services.connectors import get_connector_registry
    from uuid import UUID
    from datetime import datetime, timezone

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    total = await db.scalar(
        select(func.count(MedicSale.id)).where(
            MedicSale.org_id == UUID(org_id),
            MedicSale.sale_date >= week_ago.date(),
        )
    )
    revenue = await db.scalar(
        select(func.sum(MedicSale.unit_price_eur * MedicSale.quantity)).where(
            MedicSale.org_id == UUID(org_id),
            MedicSale.sale_date >= week_ago.date(),
        )
    ) or 0

    body = (
        f"📊 Report settimanale WorkMind\n"
        f"Periodo: ultimi 7 giorni\n\n"
        f"Vendite: {total or 0}\n"
        f"Fatturato: €{float(revenue):.2f}\n"
    )

    recipients = config.get("recipients", [])
    if isinstance(recipients, str):
        recipients = [recipients]
    alert_email = config.get("alert_email", "")
    if alert_email and alert_email not in recipients:
        recipients.append(alert_email)

    smtp_cfg = await get_connector_registry().get_config(db, org_id, "smtp")
    if not smtp_cfg or not recipients:
        return {"sent": 0}

    sent = 0
    for addr in recipients:
        ok = await send_email(smtp_cfg, addr, f"📊 Report settimanale — {date.today()}", body)
        if ok:
            sent += 1
    return {"sent": sent}


def make_email_alerts_job(org_id: str, config: dict):
    """Return async job function for APScheduler."""
    async def _run():
        from app.db.engine import get_session_factory
        SessionLocal = get_session_factory()
        async with SessionLocal() as db:
            mode = config.get("alert_type", "stock")
            if mode == "stock":
                return await run_stock_alert_email(org_id, config, db)
            elif mode == "weekly":
                return await run_weekly_report_email(org_id, config, db)

    return _run
