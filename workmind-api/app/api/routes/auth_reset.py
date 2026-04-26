"""
WorkMind API — Password Reset Routes
POST /auth/forgot-password  → request a reset link (always returns the same message)
POST /auth/reset-password   → consume token and set new password
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import PasswordResetToken, User
from app.services.email import build_reset_email, send_email

log = structlog.get_logger("workmind.auth_reset")

router = APIRouter(tags=["auth"])

# Fixed org UUID for the MEDIC client
MEDIC_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

_SAFE_RESPONSE = {"message": "Se l'email esiste, riceverai un link"}
_RESET_TTL_MINUTES = 30


# ── Schemas ───────────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """
    Request a password-reset link.

    Always returns the same opaque message regardless of whether the email
    exists — this prevents user-enumeration attacks.
    """
    # Look up user by plain email within the MEDIC org
    result = await db.execute(
        select(User).where(
            User.email == body.email.lower(),
            User.org_id == MEDIC_ORG_ID,
            User.is_active == True,  # noqa: E712
        )
    )
    user: User | None = result.scalar_one_or_none()

    if not user:
        log.info("forgot_password_unknown_email", email_prefix=body.email[:3])
        return _SAFE_RESPONSE

    # Delete any previous unused tokens for this user
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )

    # Generate a new token
    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=_RESET_TTL_MINUTES)

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token=raw_token,
            expires_at=expires_at,
        )
    )
    await db.commit()

    # Build and send the email
    reset_url = f"{settings.frontend_url}/reset-password?token={raw_token}"
    html = build_reset_email(reset_url, expires_minutes=_RESET_TTL_MINUTES)
    sent = await send_email(
        to=user.email,
        subject="WorkMind — Reimposta la tua password",
        html_body=html,
        settings=settings,
    )

    if not sent:
        log.warning("forgot_password_email_failed", user_id=str(user.id))
    else:
        log.info("forgot_password_email_sent", user_id=str(user.id))

    return _SAFE_RESPONSE


@router.post("/auth/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Consume a password-reset token and update the user's password.

    Raises HTTP 400 for any invalid / expired / already-used token.
    """
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == body.token)
    )
    token_row: PasswordResetToken | None = result.scalar_one_or_none()

    now = datetime.now(tz=timezone.utc)

    if token_row is None:
        log.warning("reset_password_token_not_found")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token non valido o scaduto",
        )

    if token_row.used_at is not None:
        log.warning("reset_password_token_already_used", token_id=str(token_row.id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token non valido o scaduto",
        )

    # Make expires_at timezone-aware for comparison if stored as naive UTC
    expires_at = token_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        log.warning("reset_password_token_expired", token_id=str(token_row.id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token non valido o scaduto",
        )

    # Fetch the target user
    result = await db.execute(
        select(User).where(User.id == token_row.user_id, User.is_active == True)  # noqa: E712
    )
    user: User | None = result.scalar_one_or_none()

    if not user:
        log.warning("reset_password_user_not_found", user_id=str(token_row.user_id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token non valido o scaduto",
        )

    # Hash the new password with bcrypt (cost=12)
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt(12)).decode()
    user.password_hash = new_hash
    # Invalidate any active refresh tokens
    user.refresh_token_hash = None

    # Mark token as used
    token_row.used_at = now

    await db.commit()

    log.info("reset_password_success", user_id=str(user.id))
    return {"message": "Password aggiornata con successo"}
