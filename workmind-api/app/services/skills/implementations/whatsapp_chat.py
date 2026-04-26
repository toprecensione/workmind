"""WhatsApp chat skill — manages WhatsApp conversation sessions."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


async def send_whatsapp(phone_id: str, token: str, to: str, text: str) -> bool:
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://graph.facebook.com/v20.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text[:4096]},
            },
        )
        return r.status_code in (200, 201)


async def send_whatsapp_template(
    phone_id: str, token: str, to: str, template_name: str, lang: str = "it"
) -> bool:
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://graph.facebook.com/v20.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {"name": template_name, "language": {"code": lang}},
            },
        )
        return r.status_code in (200, 201)


async def handle_whatsapp_message(
    phone_number: str,
    text: str,
    display_name: str,
    org_id: str,
    db,
    phone_id: str,
    token: str,
) -> bool:
    """Process incoming WhatsApp message and send reply."""
    from app.services.channel_router import handle_incoming_message

    try:
        reply = await handle_incoming_message(
            db=db,
            channel_type="whatsapp",
            external_id=phone_number,
            text=text,
            user_display_name=display_name,
        )
        return await send_whatsapp(phone_id, token, phone_number, reply)
    except Exception as e:
        logger.error(f"WhatsApp message handling failed: {e}")
        return False


def make_whatsapp_chat_job(org_id: str, config: dict):
    """Periodic proactive WhatsApp notification job (daily report)."""
    async def run():
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.config import get_settings
        from app.services.connectors import get_connector_registry
        from app.services.skills.implementations.daily_report import get_quick_summary

        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as db:
            try:
                reg = get_connector_registry()
                wa_cfg = await reg.get_config(db, org_id, "whatsapp")
                if not wa_cfg:
                    logger.warning("whatsapp_chat_job: no whatsapp connector for org %s", org_id)
                    return

                token = wa_cfg.get("token", "")
                phone_id = wa_cfg.get("phone_number_id", "")
                notify_phone = config.get("notify_phone", "")

                if not token or not phone_id or not notify_phone:
                    logger.warning(
                        "whatsapp_chat_job: missing token/phone_id/notify_phone for org %s", org_id
                    )
                    return

                message = await get_quick_summary(org_id, db)
                ok = await send_whatsapp(phone_id, token, notify_phone, message)
                if not ok:
                    logger.error("whatsapp_chat_job: send failed for org %s", org_id)
            except Exception as exc:
                logger.error("whatsapp_chat_job error: %s", exc)
        await engine.dispose()

    return run
