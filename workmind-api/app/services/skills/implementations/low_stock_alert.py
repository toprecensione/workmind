"""Skill: low_stock_alert — avvisa quando i prodotti MEDIC sono sotto soglia."""
from __future__ import annotations
import asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import get_settings
from app.db.models import MedicProduct
from app.services.connectors import get_connector_registry

log = structlog.get_logger()


def make_low_stock_job(org_id: str, cfg: dict):
    """Factory: ritorna una coroutine da passare ad APScheduler."""
    async def run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            try:
                await _run_low_stock_alert(db, org_id, cfg)
            except Exception as exc:
                log.error("low_stock_alert_error", error=str(exc))
        await engine.dispose()
    return run


async def _run_low_stock_alert(db, org_id: str, cfg: dict):
    result = await db.execute(
        select(MedicProduct).where(
            MedicProduct.org_id == org_id,
            MedicProduct.is_active,
        )
    )
    products = result.scalars().all()
    low = [p for p in products if p.stock_qty <= p.low_stock_threshold]

    if not low:
        return

    lines = [f"⚠️ *Scorte basse MEDIC* — {len(low)} prodotti:\n"]
    for p in low:
        lines.append(f"  • {p.name}: {p.stock_qty} {p.unit} (soglia: {p.low_stock_threshold})")
    message = "\n".join(lines)

    reg = get_connector_registry()

    if cfg.get("notify_via_telegram", True):
        tg_cfg = await reg.get_config(db, org_id, "telegram")
        if tg_cfg and tg_cfg.get("chat_id_default"):
            await _send_telegram(tg_cfg["bot_token"], tg_cfg["chat_id_default"], message)

    if cfg.get("notify_via_email") and cfg.get("email_recipient"):
        smtp_cfg = await reg.get_config(db, org_id, "smtp")
        if smtp_cfg:
            await asyncio.to_thread(_send_email, smtp_cfg, cfg["email_recipient"], "⚠️ Scorte basse MEDIC", message)


async def _send_telegram(token: str, chat_id: str, text: str):
    import httpx
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )


def _send_email(smtp_cfg: dict, to: str, subject: str, body: str):
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{smtp_cfg.get('from_name','WorkMind')} <{smtp_cfg['from_address']}>"
    msg["To"] = to
    ctx = ssl.create_default_context()
    if smtp_cfg.get("ssl", True):
        with smtplib.SMTP_SSL(smtp_cfg["host"], int(smtp_cfg["port"]), context=ctx, timeout=15) as s:
            s.login(smtp_cfg["username"], smtp_cfg["password"])
            s.sendmail(smtp_cfg["from_address"], [to], msg.as_string())
    else:
        with smtplib.SMTP(smtp_cfg["host"], int(smtp_cfg["port"]), timeout=15) as s:
            s.starttls(context=ctx)
            s.login(smtp_cfg["username"], smtp_cfg["password"])
            s.sendmail(smtp_cfg["from_address"], [to], msg.as_string())
