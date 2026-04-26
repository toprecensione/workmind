"""MEDIC-specific scheduled tasks."""
from __future__ import annotations
import asyncio
import logging
from celery import shared_task

logger = logging.getLogger(__name__)

_MEDIC_ORG_ID = "00000000-0000-0000-0000-000000000002"


def _get_session():
    from app.config import get_settings
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    s = get_settings()
    engine = create_async_engine(s.database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


@shared_task(name="app.tasks.medic.check_low_stock")
def check_low_stock():
    """Check for low stock products and send Telegram notification if configured."""
    async def _check():
        import uuid
        from app.db.models import MedicProduct, User
        from app.config import get_settings
        from sqlalchemy import select

        settings = get_settings()
        SessionLocal = _get_session()
        org_id = uuid.UUID(_MEDIC_ORG_ID)

        async with SessionLocal() as db:
            result = await db.execute(
                select(MedicProduct).where(
                    MedicProduct.org_id == org_id,
                    MedicProduct.is_active == True,  # noqa: E712
                    MedicProduct.stock_qty <= MedicProduct.low_stock_threshold,
                )
            )
            low = result.scalars().all()
            if not low:
                logger.info("check_low_stock: all stock levels OK")
                return {"low_stock": 0}

            msg = "⚠️ *Stock basso MEDIC*\n\n"
            for p in low:
                msg += f"• {p.name}: {p.stock_qty} {p.unit} (min: {p.low_stock_threshold})\n"

            logger.warning("check_low_stock: %d products low", len(low))

            # Send Telegram alert to admin users with telegram channel_refs
            bot_token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""
            if bot_token:
                import httpx
                admins = await db.execute(
                    select(User).where(
                        User.org_id == org_id,
                        User.role.in_(["admin", "owner"]),
                        User.is_active == True,  # noqa: E712
                    )
                )
                sent = 0
                for user in admins.scalars().all():
                    if user.channel_refs and "telegram" in user.channel_refs:
                        chat_id = user.channel_refs["telegram"]
                        try:
                            async with httpx.AsyncClient(timeout=10) as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                    json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                                )
                                sent += 1
                        except Exception as exc:
                            logger.warning("check_low_stock: telegram send failed: %s", exc)
                logger.info("check_low_stock: sent alerts to %d users", sent)

            return {"low_stock": len(low)}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_check())
    finally:
        loop.close()
    return result
