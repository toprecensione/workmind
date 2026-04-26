"""
WorkMind API — 2FA TOTP Routes
POST /auth/2fa/setup     → generate secret + QR (not yet enabled)
POST /auth/2fa/confirm   → verify code and enable 2FA
POST /auth/2fa/challenge → exchange temp_token + code for real tokens
DELETE /auth/2fa         → disable 2FA
"""
from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import User
from app.dependencies import AuthUser
from app.api.deps.limiter import limiter
from app.api.routes.auth import ALGORITHM, _make_access_token, _make_refresh_token

log = structlog.get_logger("workmind.auth_2fa")
router = APIRouter(tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TotpSetupResponse(BaseModel):
    secret: str
    uri: str
    qr_base64: str          # PNG QR code as base64


class TotpConfirmRequest(BaseModel):
    code: str               # 6-digit TOTP code


class TotpChallengeRequest(BaseModel):
    temp_token: str
    code: str


class TotpChallengeResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class TotpDisableRequest(BaseModel):
    code: str               # current TOTP code to confirm disable


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_qr_base64(uri: str) -> str:
    try:
        import qrcode
        qr = qrcode.make(uri)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _make_temp_token(user_id: uuid.UUID, settings: Settings) -> str:
    """Short-lived JWT used only for TOTP challenge step."""
    payload = {
        "sub": str(user_id),
        "type": "totp_challenge",
        "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=5),
        "iat": datetime.now(tz=timezone.utc),
    }
    return jwt.encode(payload, settings.workmind_secret_key.get_secret_value(), algorithm=ALGORITHM)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/2fa/setup", response_model=TotpSetupResponse)
async def totp_setup(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a new TOTP secret for the user. Does NOT enable 2FA yet — call /confirm."""
    user = await db.get(User, current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    if user.totp_enabled:
        raise HTTPException(
            status_code=409,
            detail="2FA già attivo. Disabilitalo prima di rigenerare il segreto.",
        )

    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name="WorkMind",
    )

    # Store pending secret (not yet enabled)
    user.totp_secret = secret
    await db.commit()

    log.info("totp_setup", user_id=str(user.id))
    return TotpSetupResponse(
        secret=secret,
        uri=uri,
        qr_base64=_make_qr_base64(uri),
    )


@router.post("/auth/2fa/confirm", status_code=200)
async def totp_confirm(
    body: TotpConfirmRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify TOTP code and enable 2FA for the user."""
    user = await db.get(User, current_user.user_id)
    if not user or not user.totp_secret:
        raise HTTPException(
            status_code=400,
            detail="Nessun segreto TOTP configurato. Chiama prima /auth/2fa/setup.",
        )

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        log.warning("totp_confirm_invalid_code", user_id=str(user.id))
        raise HTTPException(
            status_code=400,
            detail="Codice TOTP non valido.",
        )

    user.totp_enabled = True
    await db.commit()

    log.info("totp_enabled", user_id=str(user.id))
    return {"detail": "2FA attivato con successo."}


@router.post("/auth/2fa/challenge", response_model=TotpChallengeResponse)
@limiter.limit("10/minute")
async def totp_challenge(
    request: Request,
    body: TotpChallengeRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Exchange a temp_token + TOTP code for real access/refresh tokens."""
    secret = settings.workmind_secret_key.get_secret_value()

    # Validate temp token
    try:
        payload = jwt.decode(body.temp_token, secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token temporaneo non valido o scaduto.")

    if payload.get("type") != "totp_challenge":
        raise HTTPException(status_code=401, detail="Token temporaneo non valido.")

    user_id = uuid.UUID(payload["sub"])
    user = await db.get(User, user_id)

    if not user or not user.is_active or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=401, detail="Autenticazione fallita.")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        log.warning("totp_challenge_invalid_code", user_id=str(user_id))
        raise HTTPException(status_code=401, detail="Codice TOTP non valido.")

    access_token = _make_access_token(user, settings)
    refresh_token_raw, refresh_hash = _make_refresh_token(user, settings)
    user.refresh_token_hash = refresh_hash
    await db.commit()

    log.info("totp_challenge_ok", user_id=str(user.id))
    return TotpChallengeResponse(
        access_token=access_token,
        refresh_token=refresh_token_raw,
    )


@router.delete("/auth/2fa", status_code=200)
async def totp_disable(
    body: TotpDisableRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
):
    """Disable 2FA. Requires current TOTP code to confirm."""
    user = await db.get(User, current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato.")

    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA non attivo.")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Codice TOTP non valido.")

    user.totp_enabled = False
    user.totp_secret = None
    await db.commit()

    log.info("totp_disabled", user_id=str(user.id))
    return {"detail": "2FA disabilitato."}
