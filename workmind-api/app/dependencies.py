"""
WorkMind API — FastAPI Dependency Injection
Reusable Depends() factories for auth, DB session, and service access.

Auth flow:
  Phase 1: X-WorkMind-Key internal API key (service-to-service)
  Phase 2: Bearer JWT with org_id + user_id + role claims (web login)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from typing import Annotated, Optional

import structlog
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import Settings, get_settings

log = structlog.get_logger("workmind.auth")

from dataclasses import dataclass  # noqa: E402

# In-memory last-seen throttle: {user_id_str: unix_timestamp}
# Prevents DB write on every request — updates at most every 5 min per user
_last_seen_cache: dict[str, float] = {}
_LAST_SEEN_TTL = 300  # seconds


@dataclass
class CurrentUser:
    org_id: uuid.UUID
    user_id: Optional[uuid.UUID]
    role: str   # "admin" | "supervisor" | "agent" | "user"
    channel: str  # "web" | "telegram" | "api"


_DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_api_key_header = APIKeyHeader(name="X-WorkMind-Key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


# ── Internal API key (Phase 1 / service-to-service) ──────────────────────────

async def _verify_internal_api_key(
    api_key: Optional[str] = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> Optional[CurrentUser]:
    if not api_key:
        return None
    expected = settings.internal_api_key.get_secret_value()
    if not expected:
        return None
    if hmac.compare_digest(
        hashlib.sha256(api_key.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    ):
        return CurrentUser(
            org_id=_DEFAULT_ORG_ID,
            user_id=None,
            role="admin",
            channel="api",
        )
    return None


# ── JWT Bearer (Phase 2 / web login) ─────────────────────────────────────────

async def _verify_jwt_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> Optional[CurrentUser]:
    if not credentials:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.workmind_secret_key.get_secret_value(),
            algorithms=[ALGORITHM],
        )
        if payload.get("type") != "access":
            return None
        return CurrentUser(
            org_id=uuid.UUID(payload["org_id"]),
            user_id=uuid.UUID(payload["sub"]),
            role=payload.get("role", "user"),
            channel="web",
        )
    except (JWTError, KeyError, ValueError):
        return None


# ── Background last_seen updater ─────────────────────────────────────────────

async def _update_last_seen(user_id: uuid.UUID) -> None:
    """Fire-and-forget: update last_seen_at for a user. Errors are silently swallowed."""
    try:
        from datetime import datetime, timezone
        from sqlalchemy import update as sa_update
        from app.db.models import User
        from app.db.engine import get_session_factory
        SessionLocal = get_session_factory()
        async with SessionLocal() as db:
            await db.execute(
                sa_update(User)
                .where(User.id == user_id)
                .values(last_seen_at=datetime.now(tz=timezone.utc))
            )
            await db.commit()
    except Exception:
        pass  # Non-fatal


# ── Combined auth dependency ──────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    api_key_user: Optional[CurrentUser] = Depends(_verify_internal_api_key),
    jwt_user: Optional[CurrentUser] = Depends(_verify_jwt_token),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    user = api_key_user or jwt_user

    if user:
        structlog.contextvars.bind_contextvars(
            org_id=str(user.org_id),
            user_role=user.role,
        )
        # Update last_seen_at throttled (once per 5 min per user)
        if user.user_id:
            uid = str(user.user_id)
            now = time.monotonic()
            if now - _last_seen_cache.get(uid, 0) > _LAST_SEEN_TTL:
                _last_seen_cache[uid] = now
                asyncio.ensure_future(_update_last_seen(user.user_id))
        return user

    if not settings.is_production:
        log.debug("auth_phase1_fallback", path=request.url.path)
        return CurrentUser(
            org_id=_DEFAULT_ORG_ID,
            user_id=None,
            role="user",
            channel="web",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_supervisor(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role not in ("supervisor", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor o admin richiesto")
    return user


async def require_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin richiesto")
    return user


AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
SupervisorUser = Annotated[CurrentUser, Depends(require_supervisor)]
AdminUser = Annotated[CurrentUser, Depends(require_admin)]
