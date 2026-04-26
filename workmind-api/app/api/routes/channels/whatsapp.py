"""
WorkMind API — WhatsApp Channel Routes
GET  /api/channels/whatsapp/webhook      — Meta webhook verification challenge
POST /api/channels/whatsapp/webhook      — receive incoming messages
GET  /api/channels/whatsapp/set-webhook  — admin: register webhook URL with Meta

Signature validation uses X-Hub-Signature-256 (HMAC-SHA256 of the raw body).
Message processing goes through the shared channel_router pipeline:
  anonymize → persist → AI → de-anonymize → persist → reply.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.services.skills.implementations.whatsapp_chat import handle_whatsapp_message as _skill_whatsapp_handler

log = structlog.get_logger("workmind.whatsapp")
router = APIRouter()


# ── Webhook verification (GET) ─────────────────────────────────────────────────

@router.get("/whatsapp/webhook")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Meta webhook verification challenge.
    Returns hub.challenge as plain text when verify_token matches.
    """
    expected_token = settings.whatsapp_verify_token.get_secret_value()
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        log.info("whatsapp_webhook_verified")
        return PlainTextResponse(content=hub_challenge)

    log.warning("whatsapp_webhook_verification_failed", mode=hub_mode)
    return PlainTextResponse(content="Forbidden", status_code=403)


# ── Incoming messages (POST) ───────────────────────────────────────────────────

@router.post("/whatsapp/webhook", status_code=200)
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Receive WhatsApp Cloud API messages.
    Always returns 200 immediately; processing is async.
    """
    body = await request.body()

    # ── Validate HMAC-SHA256 signature ────────────────────────────────────────
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    whatsapp_token = settings.whatsapp_token.get_secret_value()

    if whatsapp_token and signature_header:
        expected_sig = "sha256=" + hmac.new(
            whatsapp_token.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature_header, expected_sig):
            log.warning("whatsapp_invalid_signature")
            return JSONResponse(status_code=200, content={})

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload = json.loads(body)
    except Exception:
        return JSONResponse(status_code=200, content={})

    # ── Process each message ──────────────────────────────────────────────────
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                try:
                    await _handle_whatsapp_message(message, value, db, settings)
                except Exception as exc:
                    log.exception("whatsapp_message_handler_error", error=str(exc))

    return JSONResponse(status_code=200, content={})


async def _handle_whatsapp_message(
    message: dict[str, Any],
    value: dict[str, Any],
    db: AsyncSession,
    settings: Settings,
) -> None:
    """Handle an individual WhatsApp message through the AI pipeline."""
    msg_type = message.get("type", "")
    from_number = message.get("from", "")

    if msg_type != "text":
        log.info("whatsapp_non_text_message", type=msg_type, from_=from_number)
        return

    text = message.get("text", {}).get("body", "")
    if not text:
        return

    # Resolve display name from contacts metadata (present in some payloads)
    contacts = value.get("contacts", [])
    display_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

    log.info("whatsapp_message", from_=from_number, length=len(text))

    token = settings.whatsapp_token.get_secret_value()
    phone_id = settings.whatsapp_phone_id

    try:
        # Route through whatsapp_chat skill which handles the full AI pipeline + send
        ok = await _skill_whatsapp_handler(
            phone_number=from_number,
            text=text,
            display_name=display_name,
            org_id="",  # org resolved inside channel_router via channel mapping
            db=db,
            phone_id=phone_id or "",
            token=token or "",
        )
        if not ok:
            log.warning("whatsapp_skill_handler_returned_false", from_=from_number)
    except Exception as exc:
        log.exception("whatsapp_ai_call_failed", error=str(exc))
        await _send_whatsapp_reply(
            from_number,
            "Errore temporaneo. Riprova tra qualche istante.",
            settings,
        )


async def _send_whatsapp_reply(to: str, text: str, settings: Settings) -> None:
    """Send a reply via the WhatsApp Cloud API."""
    token = settings.whatsapp_token.get_secret_value()
    phone_id = settings.whatsapp_phone_id
    if not token or not phone_id:
        log.warning("whatsapp_send_missing_config")
        return

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://graph.facebook.com/v20.0/{phone_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text[:4096]},
            },
        )
        if resp.status_code not in (200, 201):
            log.warning("whatsapp_send_failed", status=resp.status_code, to=to)


# ── Admin: register webhook with Meta ─────────────────────────────────────────

@router.get("/whatsapp/set-webhook", tags=["admin"])
async def whatsapp_set_webhook(
    webhook_url: str = Query(
        ...,
        description="Full HTTPS URL Meta should POST events to, "
                    "e.g. https://bender.tail898ef4.ts.net/api/channels/whatsapp/webhook",
    ),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Register (or update) the WhatsApp webhook URL via the Meta Graph API.

    Requires WHATSAPP_TOKEN (system user access token) and WHATSAPP_PHONE_ID
    to be set in the environment.  The verify_token sent to Meta equals the
    WHATSAPP_VERIFY_TOKEN setting so the GET challenge passes automatically.

    Example:
        GET /api/channels/whatsapp/set-webhook
            ?webhook_url=https://bender.tail898ef4.ts.net/api/channels/whatsapp/webhook
    """
    token = settings.whatsapp_token.get_secret_value()
    phone_id = settings.whatsapp_phone_id
    verify_token = settings.whatsapp_verify_token.get_secret_value()

    if not token or not phone_id:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "description": "WHATSAPP_TOKEN or WHATSAPP_PHONE_ID not configured",
            },
        )

    # The Graph API endpoint to subscribe a phone number's webhook is:
    # POST /{phone-number-id}/subscribed_apps   (subscribes to webhooks at app level)
    # The actual webhook URL is configured at the App Dashboard level; this endpoint
    # updates the subscription.  For programmatic URL updates we use the app-level API.
    #
    # Since the app-level webhook config requires an App Secret (not a phone token),
    # we return the required settings for the operator to paste into the Meta dashboard
    # alongside the direct API call attempt.
    payload = {
        "webhook_url": webhook_url,
        "verify_token": verify_token or "(set WHATSAPP_VERIFY_TOKEN in .env)",
        "subscribed_fields": ["messages", "messaging_postbacks"],
        "note": (
            "If your Meta App has a system-user token with sufficient permissions, "
            "this response confirms the expected configuration. "
            "Paste webhook_url and verify_token into the Meta App Dashboard → "
            "WhatsApp → Configuration → Webhook."
        ),
    }

    # Attempt programmatic subscription (requires whatsapp_business_management permission)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v20.0/{phone_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {token}"},
            )
        api_result = resp.json()
        payload["meta_api_response"] = api_result
        payload["ok"] = api_result.get("success", False)
        log.info(
            "whatsapp_set_webhook",
            webhook_url=webhook_url,
            ok=payload["ok"],
            api_result=api_result,
        )
    except Exception as exc:
        payload["ok"] = False
        payload["meta_api_error"] = str(exc)
        log.warning("whatsapp_set_webhook_api_error", error=str(exc))

    return JSONResponse(status_code=200, content=payload)
