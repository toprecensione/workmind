"""Admin API — gestione utenti e organizzazione."""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import (
    User, Organization, AuditLog, AuditEventType,
    Connector, Skill, Conversation, Message
)
from app.dependencies import get_current_user, CurrentUser

log = structlog.get_logger()
router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin(user: CurrentUser) -> None:
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def _gen_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # almeno una maiuscola, una cifra, un simbolo
        if (any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)
                and any(c in "!@#$" for c in pwd)):
            return pwd


async def _write_audit(
    db: AsyncSession,
    org_id: UUID,
    user_id: Optional[UUID],
    actor: str,
    event_type: AuditEventType,
    summary: str,
    details: dict | None = None,
) -> None:
    try:
        db.add(AuditLog(
            org_id=org_id,
            user_id=user_id,
            event_type=event_type,
            actor=actor,
            summary=summary,
            details_json=details or {},
        ))
        await db.flush()
    except Exception as exc:
        log.warning("audit_write_failed", error=str(exc))


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    display_name: Optional[str]
    role: str
    is_active: bool
    last_seen_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserDetailOut(BaseModel):
    user: UserOut
    message_count: int
    conversation_count: int
    connectors_enabled: list[str]
    skills_enabled: list[str]
    recent_activity: list[dict]


class UserCreateIn(BaseModel):
    email: EmailStr
    display_name: Optional[str] = None
    role: str = "user"
    password: Optional[str] = None


class UserUpdateIn(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class OrgOut(BaseModel):
    id: UUID
    slug: str
    name: str
    sector: Optional[str]
    is_active: bool
    config_json: dict
    created_at: datetime
    user_count: int

    model_config = {"from_attributes": True}


class OrgUpdateIn(BaseModel):
    name: Optional[str] = None
    sector: Optional[str] = None
    config_json: Optional[dict] = None


# ── Users endpoints ───────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Lista tutti gli utenti dell'organizzazione con filtri opzionali."""
    _require_admin(user)

    stmt = select(User).where(
        User.org_id == user.org_id,
        ~User.email.like("__deleted__%"),   # escludi soft-deleted di default
    )

    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if search:
        term = f"%{search.lower()}%"
        stmt = stmt.where(
            (User.email.ilike(term)) | (User.display_name.ilike(term))
        )

    stmt = stmt.order_by(User.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Crea un nuovo utente nell'organizzazione."""
    _require_admin(user)

    email_hash = _hash_email(body.email)

    # Verifica duplicati
    existing = await db.execute(
        select(User).where(
            User.org_id == user.org_id,
            User.email_hash == email_hash,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Utente con email '{body.email}' già esistente")

    plain_pwd = body.password or _gen_temp_password()
    new_user = User(
        id=uuid4(),
        org_id=user.org_id,
        email=body.email,
        email_hash=email_hash,
        display_name=body.display_name or body.email.split("@")[0],
        role=body.role,
        password_hash=_hash_password(plain_pwd),
        is_active=True,
    )
    db.add(new_user)

    await _write_audit(
        db, user.org_id, user.user_id,
        actor=str(user.user_id),
        event_type=AuditEventType.admin_action,
        summary=f"Creato utente {body.email} con ruolo {body.role}",
        details={"email": body.email, "role": body.role},
    )
    await db.commit()
    await db.refresh(new_user)

    log.info("admin_user_created", email=body.email, by=str(user.user_id))
    # Includi la password temporanea nella risposta (solo alla creazione)
    out = UserOut.model_validate(new_user)
    # Hack: aggiungi temp_password nel response dict senza cambiare schema
    response_data = out.model_dump()
    if not body.password:
        response_data["temp_password"] = plain_pwd
    return response_data


@router.get("/users/{user_id}", response_model=UserDetailOut)
async def get_user_detail(
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Dettaglio utente con statistiche di utilizzo."""
    _require_admin(current_user)

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Utente non trovato")

    # Conta conversazioni dell'utente
    conv_count_res = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.org_id == current_user.org_id,
            Conversation.user_id == user_id,
        )
    )
    conv_count = conv_count_res.scalar() or 0

    # Conta messaggi nelle conversazioni dell'utente
    msg_count_res = await db.execute(
        select(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.org_id == current_user.org_id,
            Conversation.user_id == user_id,
        )
    )
    msg_count = msg_count_res.scalar() or 0

    # Connector abilitati
    conn_res = await db.execute(
        select(Connector.type).where(
            Connector.org_id == current_user.org_id,
            Connector.is_enabled,
        )
    )
    connectors_enabled = [r[0] for r in conn_res.all()]

    # Skill abilitate
    skill_res = await db.execute(
        select(Skill.skill_id).where(
            Skill.org_id == current_user.org_id,
            Skill.is_enabled,
        )
    )
    skills_enabled = [r[0] for r in skill_res.all()]

    # Attività recente (ultimi 10)
    audit_res = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    )
    recent_activity = [
        {
            "event_type": str(a.event_type.value if hasattr(a.event_type, 'value') else a.event_type),
            "summary": a.summary,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audit_res.scalars().all()
    ]

    return UserDetailOut(
        user=UserOut.model_validate(target),
        message_count=msg_count,
        conversation_count=conv_count,
        connectors_enabled=connectors_enabled,
        skills_enabled=skills_enabled,
        recent_activity=recent_activity,
    )


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    body: UserUpdateIn,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Aggiorna ruolo, nome o stato attivo di un utente."""
    _require_admin(current_user)

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Utente non trovato")

    if body.display_name is not None:
        target.display_name = body.display_name
    if body.role is not None:
        if body.role not in ("user", "agent", "supervisor", "admin"):
            raise HTTPException(400, "Ruolo non valido")
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active
        if not body.is_active:
            target.refresh_token_hash = None  # invalida sessioni

    await _write_audit(
        db, current_user.org_id, current_user.user_id,
        actor=str(current_user.user_id),
        event_type=AuditEventType.admin_action,
        summary=f"Aggiornato utente {target.email}: {body.model_dump(exclude_none=True)}",
    )
    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Elimina (soft delete) un utente. Non puoi eliminare te stesso."""
    _require_admin(current_user)

    if current_user.user_id and str(current_user.user_id) == str(user_id):
        raise HTTPException(400, "Non puoi eliminare il tuo stesso account")

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Utente non trovato")

    # Soft delete
    target.is_active = False
    target.refresh_token_hash = None
    target.email = f"__deleted__{target.email}"
    target.email_hash = _hash_email(target.email)

    await _write_audit(
        db, current_user.org_id, current_user.user_id,
        actor=str(current_user.user_id),
        event_type=AuditEventType.admin_action,
        summary=f"Eliminato (soft delete) utente id={user_id}",
    )
    await db.commit()


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Genera e imposta una nuova password temporanea per l'utente."""
    _require_admin(current_user)

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Utente non trovato")

    new_pwd = _gen_temp_password()
    target.password_hash = _hash_password(new_pwd)
    target.refresh_token_hash = None  # forza re-login

    await _write_audit(
        db, current_user.org_id, current_user.user_id,
        actor=str(current_user.user_id),
        event_type=AuditEventType.admin_action,
        summary=f"Reset password per utente {target.email}",
    )
    await db.commit()
    log.info("admin_password_reset", target_user=str(user_id))
    return {"new_password": new_pwd}


@router.post("/users/{user_id}/activate", response_model=UserOut)
async def activate_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Attiva un utente disabilitato."""
    _require_admin(current_user)

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Utente non trovato")

    target.is_active = True
    await db.commit()
    await db.refresh(target)
    return target


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Disattiva un utente (invalida sessioni)."""
    _require_admin(current_user)

    if current_user.user_id and str(current_user.user_id) == str(user_id):
        raise HTTPException(400, "Non puoi disattivare te stesso")

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Utente non trovato")

    target.is_active = False
    target.refresh_token_hash = None
    await db.commit()
    await db.refresh(target)
    return target


@router.get("/users/{user_id}/activity")
async def get_user_activity(
    user_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Ultimi N eventi di audit per un utente specifico."""
    _require_admin(current_user)

    # Verifica che l'utente appartenga all'org
    exists = await db.execute(
        select(User.id).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    if not exists.scalar_one_or_none():
        raise HTTPException(404, "Utente non trovato")

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": a.id,
            "event_type": str(a.event_type.value if hasattr(a.event_type, 'value') else a.event_type),
            "actor": a.actor,
            "summary": a.summary,
            "ip_address": str(a.ip_address) if a.ip_address else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in logs
    ]


# ── Organization endpoints ────────────────────────────────────────────────────

@router.get("/org", response_model=OrgOut)
async def get_org(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Dettaglio organizzazione corrente con conteggio utenti."""
    _require_admin(current_user)

    org_res = await db.execute(
        select(Organization).where(Organization.id == current_user.org_id)
    )
    org = org_res.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organizzazione non trovata")

    user_count_res = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == current_user.org_id,
            User.is_active,
        )
    )
    user_count = user_count_res.scalar() or 0

    return OrgOut(
        id=org.id,
        slug=org.slug,
        name=org.name,
        sector=org.sector,
        is_active=org.is_active,
        config_json=org.config_json or {},
        created_at=org.created_at,
        user_count=user_count,
    )


@router.put("/org", response_model=OrgOut)
async def update_org(
    body: OrgUpdateIn,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Aggiorna nome, settore e config JSON dell'organizzazione."""
    _require_admin(current_user)

    org_res = await db.execute(
        select(Organization).where(Organization.id == current_user.org_id)
    )
    org = org_res.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organizzazione non trovata")

    if body.name is not None:
        org.name = body.name
    if body.sector is not None:
        org.sector = body.sector
    if body.config_json is not None:
        org.config_json = {**(org.config_json or {}), **body.config_json}

    await _write_audit(
        db, current_user.org_id, current_user.user_id,
        actor=str(current_user.user_id),
        event_type=AuditEventType.admin_action,
        summary=f"Aggiornata organizzazione: {body.model_dump(exclude_none=True)}",
    )
    await db.commit()
    await db.refresh(org)

    user_count_res = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == current_user.org_id,
            User.is_active,
        )
    )
    user_count = user_count_res.scalar() or 0

    return OrgOut(
        id=org.id,
        slug=org.slug,
        name=org.name,
        sector=org.sector,
        is_active=org.is_active,
        config_json=org.config_json or {},
        created_at=org.created_at,
        user_count=user_count,
    )
