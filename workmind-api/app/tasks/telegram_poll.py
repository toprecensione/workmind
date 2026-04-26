"""Telegram long-polling task — used when webhook/Funnel is not available."""
from __future__ import annotations
import asyncio
import logging
from celery import shared_task

logger = logging.getLogger(__name__)

# Persistent offset stored in Redis to track processed update_id
_OFFSET_KEY = "workmind:telegram:poll_offset"


async def _poll_once(bot_token: str, redis_url: str) -> int:
    """
    Fetch pending Telegram updates, route them through the channel pipeline,
    return number of processed updates.
    """
    import httpx
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url, decode_responses=True)
    offset = int(await r.get(_OFFSET_KEY) or 0)

    async with httpx.AsyncClient(timeout=35.0) as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={"offset": offset, "timeout": 30, "limit": 50},
        )
        if resp.status_code != 200:
            logger.error("telegram_poll_error status=%s body=%s", resp.status_code, resp.text[:200])
            await r.aclose()
            return 0

        data = resp.json()
        if not data.get("ok"):
            logger.error("telegram_poll_not_ok %s", data)
            await r.aclose()
            return 0

        updates = data.get("result", [])
        if not updates:
            await r.aclose()
            return 0

    # Import channel router
    from app.services.channel_router import handle_incoming_message as handle_channel_message
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    processed = 0
    new_offset = offset

    for upd in updates:
        update_id = upd["update_id"]
        new_offset = max(new_offset, update_id + 1)

        try:
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue

            chat_id = str(msg["chat"]["id"])
            user_info = msg.get("from", {})
            external_id = f"tg_{user_info.get('id', chat_id)}"
            text = msg.get("text", "")

            # Handle voice messages
            if not text:
                voice = msg.get("voice") or msg.get("audio")
                if voice:
                    from app.services.skills.implementations.telegram_voice import handle_voice_message
                    from app.config import get_settings as _gs
                    from sqlalchemy.ext.asyncio import create_async_engine as _cae, async_sessionmaker as _asm
                    _s = _gs()
                    _engine = _cae(_s.database_url, pool_pre_ping=True)
                    _Session = _asm(_engine, expire_on_commit=False)
                    async with _Session() as db:
                        reply = await handle_voice_message(
                            file_id=voice["file_id"],
                            org_id=settings.channel_org_id or "00000000-0000-0000-0000-000000000002",
                            db=db,
                            bot_token=bot_token,
                        )
                    await _engine.dispose()
                    if reply:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": chat_id, "text": reply, "parse_mode": "Markdown"},
                            )
                    processed += 1
                continue

            async with SessionLocal() as db:
                reply = await handle_channel_message(
                    db=db,
                    channel_type="telegram",
                    external_id=external_id,
                    text=text,
                    user_display_name=user_info.get("first_name", ""),
                )

            if reply:
                # Send reply back to Telegram
                from app.config import get_settings
                get_settings()
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": reply, "parse_mode": "Markdown"},
                    )

            processed += 1

        except Exception as exc:
            logger.error("telegram_poll_update_error update_id=%s error=%s", update_id, exc)

    # Persist new offset
    await r.set(_OFFSET_KEY, new_offset)
    await r.aclose()
    await engine.dispose()

    logger.info("telegram_poll processed=%d new_offset=%d", processed, new_offset)
    return processed


_LOCK_KEY = "workmind:telegram:poll_lock"
_LOCK_TTL = 55  # seconds — longer than poll timeout (30s) + processing


@shared_task(name="app.tasks.telegram_poll.poll_updates", ignore_result=True)
def poll_updates():
    """
    Celery beat task: poll Telegram for new messages every 30s.
    Uses long-polling (timeout=30) to minimize API calls.
    A Redis lock prevents concurrent execution across workers.
    Only runs if Telegram connector is enabled and no webhook is active.
    """
    async def _run():
        from app.config import get_settings
        import httpx
        import redis.asyncio as aioredis

        settings = get_settings()
        _token_field = getattr(settings, "telegram_bot_token", None)
        if not _token_field:
            return {"skip": "no bot_token"}
        bot_token = (
            _token_field.get_secret_value()
            if hasattr(_token_field, "get_secret_value")
            else str(_token_field)
        )
        if not bot_token:
            return {"skip": "no bot_token"}

        # Redis lock — only one poller at a time across all workers
        redis_url = getattr(settings, "celery_broker_url", "redis://localhost:6379/2")
        redis_state_url = redis_url.rsplit("/", 1)[0] + "/0"
        r = aioredis.from_url(redis_state_url, decode_responses=True)

        acquired = await r.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL)
        if not acquired:
            await r.aclose()
            logger.debug("telegram_poll skip: lock held by another worker")
            return {"skip": "locked"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check if a webhook is registered — skip polling if so
                resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getWebhookInfo")
                if resp.status_code == 200:
                    wh_url = resp.json().get("result", {}).get("url", "")
                    if wh_url:
                        logger.debug("telegram_poll skip: webhook active at %s", wh_url)
                        return {"skip": "webhook_active", "webhook": wh_url}

                # Ensure no stale session from previous long-poll hangs
                await client.get(f"https://api.telegram.org/bot{bot_token}/deleteWebhook")

            result = await _poll_once(bot_token, redis_state_url)
            return result
        finally:
            await r.delete(_LOCK_KEY)
            await r.aclose()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_run())
        return result
    finally:
        loop.close()
