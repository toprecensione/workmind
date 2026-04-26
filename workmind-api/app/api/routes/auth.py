"""
WorkMind API — Auth Router
POST /auth/login   → { access_token, refresh_token, expires_in }
POST /auth/refresh → { access_token, expires_in }
POST /auth/logout  → 204
GET  /auth/me      → { id, email, display_name, role, org_id }
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt

from app.api.deps.limiter import limiter
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import User
from app.dependencies import AuthUser

log = structlog.get_logger("workmind.auth")

router = APIRouter(tags=["auth"])

ALGORITHM = "HS256"
ACCESS_TTL_MINUTES = 60
REFRESH_TTL_DAYS = 30


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TTL_MINUTES * 60


class RefreshRequest(BaseModel):
    refresh_token: str


class TotpLoginResponse(BaseModel):
    totp_required: bool = True
    temp_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TTL_MINUTES * 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_access_token(user: User, settings: Settings) -> str:
    payload = {
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": user.role,
        "email_hash": user.email_hash,
        "display_name": user.display_name or user.email or "",
        "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=ACCESS_TTL_MINUTES),
        "iat": datetime.now(tz=timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.workmind_secret_key.get_secret_value(), algorithm=ALGORITHM)


def _make_refresh_token(user: User, settings: Settings) -> tuple[str, str]:
    """Returns (raw_token, sha256_hash_for_storage)."""
    raw = jwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(tz=timezone.utc) + timedelta(days=REFRESH_TTL_DAYS),
            "iat": datetime.now(tz=timezone.utc),
            "type": "refresh",
            "jti": str(uuid.uuid4()),
        },
        settings.workmind_secret_key.get_secret_value(),
        algorithm=ALGORITHM,
    )
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    ehash = _email_hash(body.email)
    result = await db.execute(
        select(User).where(User.email_hash == ehash, User.is_active == True)  # noqa: E712
    )
    user: Optional[User] = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )

    if not _bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        log.warning("login_failed", email_hash=ehash[:8])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )

    # 2FA check
    if user.totp_enabled:
        from app.api.routes.auth_2fa import _make_temp_token
        temp = _make_temp_token(user.id, settings)
        log.info("login_totp_required", user_id=str(user.id))
        return {"totp_required": True, "temp_token": temp}

    access_token = _make_access_token(user, settings)
    refresh_token_raw, refresh_hash = _make_refresh_token(user, settings)

    # Store hashed refresh token for rotation
    user.refresh_token_hash = refresh_hash
    await db.commit()

    log.info("login_success", user_id=str(user.id), org_id=str(user.org_id))
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_raw,
    )


@router.post("/auth/refresh", response_model=AccessTokenResponse)
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    secret = settings.workmind_secret_key.get_secret_value()
    try:
        payload = jwt.decode(body.refresh_token, secret, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token non valido")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token non valido")

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))  # noqa: E712
    user: Optional[User] = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non trovato")

    incoming_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    if user.refresh_token_hash != incoming_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revocato")

    return AccessTokenResponse(access_token=_make_access_token(user, settings))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    secret = settings.workmind_secret_key.get_secret_value()
    try:
        payload = jwt.decode(body.refresh_token, secret, algorithms=[ALGORITHM])
        user_id = uuid.UUID(payload["sub"])
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.refresh_token_hash = None
            await db.commit()
    except Exception:
        pass  # Logout is best-effort


class MeResponse(BaseModel):
    id: uuid.UUID
    email: Optional[str]
    display_name: Optional[str]
    role: str
    org_id: uuid.UUID


@router.get("/auth/me", response_model=MeResponse, summary="Get current user profile")
async def get_me(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
) -> MeResponse:
    """Return profile of the authenticated user."""
    result = await db.execute(
        select(User).where(
            User.id == current_user.user_id,
            User.org_id == current_user.org_id,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        # Fallback for API-key users or channel stubs
        return MeResponse(
            id=current_user.user_id or uuid.uuid4(),
            email=None,
            display_name=current_user.role,
            role=current_user.role,
            org_id=current_user.org_id,
        )

    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        org_id=user.org_id,
    )


class MePatchRequest(BaseModel):
    display_name: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


@router.patch("/auth/me", response_model=MeResponse, summary="Update own profile or change password")
async def patch_me(
    body: MePatchRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    """Update display name or change password (current_password required for password change)."""
    if current_user.user_id is None:
        raise HTTPException(status_code=403, detail="API key users cannot update profile")

    result = await db.execute(
        select(User).where(
            User.id == current_user.user_id,
            User.org_id == current_user.org_id,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.display_name is not None:
        user.display_name = body.display_name

    if body.new_password:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="current_password required to change password")
        if not user.password_hash:
            raise HTTPException(status_code=400, detail="Account has no password set")
        if not _bcrypt.checkpw(body.current_password.encode(), user.password_hash.encode()):
            raise HTTPException(status_code=400, detail="Password corrente errata")
        if len(body.new_password) < 8:
            raise HTTPException(status_code=400, detail="Nuova password deve avere almeno 8 caratteri")
        user.password_hash = _bcrypt.hashpw(body.new_password.encode(), _bcrypt.gensalt()).decode()
        # Invalidate refresh tokens
        user.refresh_token_hash = None
        log.info("password_changed", user_id=str(user.id))

    await db.commit()

    # Cache before session expires
    user_id = user.id
    email = user.email
    display_name = user.display_name
    role = user.role
    org_id = user.org_id

    return MeResponse(
        id=user_id,
        email=email,
        display_name=display_name,
        role=role,
        org_id=org_id,
    )


def hash_password(plain: str) -> str:
    """Utility for seed scripts."""
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()
