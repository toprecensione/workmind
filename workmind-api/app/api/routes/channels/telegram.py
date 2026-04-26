"""
WorkMind API — Telegram Channel Routes
POST /api/channels/telegram/webhook      — receive updates from Telegram Bot API
GET  /api/channels/telegram/set-webhook  — admin: register webhook URL with Telegram

Webhook validation uses X-Telegram-Bot-Api-Secret-Token.
All webhook responses return HTTP 200 immediately (Telegram retries on non-2xx).
Message processing goes through the shared channel_router pipeline:
  anonymize → persist → AI → de-anonymize → persist → reply.
"""
from __future__ import annotations

import hmac
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.services.channel_router import handle_incoming_message
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("workmind.telegram")
router = APIRouter()


# ── Webhook endpoint ───────────────────────────────────────────────────────────

@router.post("/telegram/webhook", status_code=200)
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Telegram webhook endpoint.  Always returns 200 (even on error) to prevent
    Telegram from retrying indefinitely.
    """
    # ── Validate secret ────────────────────────────────────────────────────────
    secret = settings.telegram_webhook_secret.get_secret_value()
    if secret:
        token_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token_header, secret):
            log.warning("telegram_webhook_invalid_secret")
            return JSONResponse(status_code=200, content={})

    # ── Parse update ──────────────────────────────────────────────────────────
    try:
        update = await request.json()
    except Exception:
        log.warning("telegram_webhook_invalid_json")
        return JSONResponse(status_code=200, content={})

    update_id = update.get("update_id", "unknown")
    log.info("telegram_update_received", update_id=update_id)

    # ── Route to handler ──────────────────────────────────────────────────────
    try:
        await _handle_update(update, db, settings)
    except Exception as exc:
        log.exception("telegram_update_handler_error", update_id=update_id, error=str(exc))

    return JSONResponse(status_code=200, content={})


async def _handle_update(
    update: dict[str, Any],
    db: AsyncSession,
    settings: Settings,
) -> None:
    """Route Telegram updates to the appropriate handler."""
    if "message" in update:
        message = update["message"]
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        voice = message.get("voice")

        if not chat_id:
            return

        # Voice message: transcribe via telegram_voice skill
        if voice:
            await _handle_voice(chat_id, voice, message, db, settings)
            return

        if not text:
            return

        if text.startswith("/"):
            await _handle_command(chat_id, text, message, db, settings)
        else:
            await _handle_message(chat_id, text, message, db, settings)

    elif "callback_query" in update:
        query = update["callback_query"]
        await _answer_callback_query(query["id"], settings)


async def _handle_voice(
    chat_id: int,
    voice: dict[str, Any],
    message: dict,
    db: AsyncSession,
    settings: Settings,
) -> None:
    """Handle a voice message: transcribe and route through AI pipeline."""
    from app.services.skills.implementations.telegram_voice import handle_voice_message
    from app.services.connectors import get_connector_registry

    bot_token = settings.telegram_bot_token.get_secret_value()
    if not bot_token:
        return

    # Resolve Ollama URL from connector config (fall back to default)
    ollama_url = "http://localhost:11434"
    try:
        ollama_cfg = await get_connector_registry().get_config(db, "default", "ollama")
        if ollama_cfg:
            ollama_url = ollama_cfg.get("base_url", ollama_url)
    except Exception:
        pass

    file_id = voice.get("file_id", "")
    # Use chat_id as external_id so conversation is properly tracked per-user
    try:
        reply = await handle_voice_message(
            file_id=file_id,
            org_id=str(chat_id),   # resolved to MEDIC org inside handle_voice_message
            db=db,
            bot_token=bot_token,
            ollama_url=ollama_url,
        )
        await _send_message(chat_id, reply, settings)
    except Exception as exc:
        log.exception("telegram_voice_handler_error", error=str(exc))
        await _send_message(chat_id, "Errore nella trascrizione vocale. Riprova.", settings)


async def _handle_message(
    chat_id: int,
    text: str,
    message: dict,
    db: AsyncSession,
    settings: Settings,
) -> None:
    """Route a regular text message through the full AI pipeline."""
    from_user = message.get("from", {})
    display_name = " ".join(
        filter(None, [from_user.get("first_name", ""), from_user.get("last_name", "")])
    ).strip() or from_user.get("username", "")

    log.info("telegram_message", chat_id=chat_id, length=len(text))

    try:
        reply = await handle_incoming_message(
            db=db,
            channel_type="telegram",
            external_id=str(chat_id),
            text=text,
            user_display_name=display_name,
            settings=settings,
        )
        await _send_message(chat_id, reply, settings)
    except Exception as exc:
        log.exception("telegram_ai_call_failed", error=str(exc))
        await _send_message(
            chat_id, "Errore temporaneo. Riprova tra qualche istante.", settings
        )


# ── Command handlers ───────────────────────────────────────────────────────────

async def _handle_command(
    chat_id: int, text: str, message: dict, db: AsyncSession, settings: Settings
) -> None:
    """Handle Telegram slash commands, delegating extended ones to the skill."""
    parts = text.split(None, 1)
    command = parts[0].split("@")[0]
    args = parts[1] if len(parts) > 1 else ""

    # Built-in simple commands (no DB needed)
    simple_handlers = {
        "/start": _cmd_start,
        "/help": _cmd_help,
        "/status": _cmd_status,
    }
    if command in simple_handlers:
        await simple_handlers[command](chat_id, message, settings)
        return

    # Extended commands routed through telegram_commands skill
    try:
        from app.services.skills.implementations.telegram_commands import handle_command
        # Use chat_id as a stand-in org_id at the channel level;
        # skill-level org resolution happens inside handle_command.
        reply = await handle_command(command, args, str(chat_id), db)
        if reply:
            await _send_message(chat_id, reply, settings)
            return
    except Exception as exc:
        log.exception("telegram_skill_command_error", command=command, error=str(exc))

    await _cmd_unknown(chat_id, message, settings)


async def _cmd_start(chat_id: int, message: dict, settings: Settings) -> None:
    name = message.get("from", {}).get("first_name", "")
    await _send_message(
        chat_id,
        f"Ciao {name}! Sono WorkMind, il tuo assistente operativo.\n"
        "Scrivi una domanda o usa /help per vedere i comandi disponibili.",
        settings,
    )


async def _cmd_help(chat_id: int, message: dict, settings: Settings) -> None:
    await _send_message(
        chat_id,
        "Comandi disponibili:\n"
        "/start — Avvia il bot\n"
        "/status — Stato del sistema\n"
        "/help — Questo messaggio\n\n"
        "Puoi anche scrivere liberamente per chattare con l'AI.",
        settings,
    )


async def _cmd_status(chat_id: int, message: dict, settings: Settings) -> None:
    await _send_message(
        chat_id,
        f"WorkMind API v2\nProfilo: {settings.workmind_profile.value}\nNodo: {settings.workmind_node_id}",
        settings,
    )


async def _cmd_unknown(chat_id: int, message: dict, settings: Settings) -> None:
    await _send_message(chat_id, "Comando non riconosciuto. Usa /help.", settings)


# ── Telegram API helpers ───────────────────────────────────────────────────────

async def _answer_callback_query(query_id: str, settings: Settings) -> None:
    """Acknowledge a callback query to clear the loading state."""
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": query_id},
        )


async def _send_message(chat_id: int, text: str, settings: Settings) -> None:
    """Send a text message to a Telegram chat (4096-char limit)."""
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        log.warning("telegram_send_no_token")
        return

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text[:4096],
                "parse_mode": "Markdown",
            },
        )
        if resp.status_code != 200:
            log.warning("telegram_send_failed", status=resp.status_code, chat_id=chat_id)


# ── Admin: register webhook with Telegram ─────────────────────────────────────

@router.get("/telegram/set-webhook", tags=["admin"])
async def telegram_set_webhook(
    webhook_url: str = Query(
        ...,
        description="Full HTTPS URL that Telegram should POST updates to, "
                    "e.g. https://bender.tail898ef4.ts.net/api/channels/telegram/webhook",
    ),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Register (or update) the webhook URL with the Telegram Bot API.
    Also sets the secret_token so Telegram signs every update.

    Example:
        GET /api/channels/telegram/set-webhook
            ?webhook_url=https://bender.tail898ef4.ts.net/api/channels/telegram/webhook
    """
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "description": "TELEGRAM_BOT_TOKEN not configured"},
        )

    secret = settings.telegram_webhook_secret.get_secret_value()
    payload: dict[str, Any] = {
        "url": webhook_url,
        "allowed_updates": ["message", "edited_message", "callback_query"],
        "drop_pending_updates": False,
    }
    if secret:
        payload["secret_token"] = secret

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json=payload,
        )

    result = resp.json()
    log.info(
        "telegram_set_webhook",
        webhook_url=webhook_url,
        ok=result.get("ok"),
        description=result.get("description"),
    )
    return JSONResponse(status_code=resp.status_code, content=result)
