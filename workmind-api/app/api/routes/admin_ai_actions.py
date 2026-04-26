"""
Admin — AI Action Permissions
Configure which executable actions the chatbot can perform, per org/role/user.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session as get_db
from app.db.models import AiActionConfig, User
from app.dependencies import AdminUser

router = APIRouter()

MEDIC_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

# ── Static action definitions ─────────────────────────────────────────────────
AI_ACTIONS: list[dict[str, Any]] = [
    # --- LETTURA ---
    {
        "key": "cerca_prodotto",
        "label": "Cerca prodotto",
        "description": "Il bot può cercare prodotti per nome o categoria e mostrare stock, prezzo e dettagli.",
        "category": "read",
        "default_roles": None,            # tutti i ruoli
        "default_confirmation": False,
        "risk": "low",
    },
    {
        "key": "stato_stock",
        "label": "Stato stock & alert",
        "description": "Il bot può consultare lo stock attuale di tutti i prodotti e segnalare quelli sotto soglia o esauriti.",
        "category": "read",
        "default_roles": None,
        "default_confirmation": False,
        "risk": "low",
    },
    {
        "key": "inventario",
        "label": "Inventario completo",
        "description": "Il bot può mostrare l'inventario completo con i lotti attivi, quantità e date di scadenza.",
        "category": "read",
        "default_roles": ["supervisor", "admin"],
        "default_confirmation": False,
        "risk": "low",
    },
    {
        "key": "stats_vendite",
        "label": "Statistiche vendite",
        "description": "Il bot può calcolare e mostrare statistiche di vendita per periodo, prodotto o agente.",
        "category": "read",
        "default_roles": ["supervisor", "admin"],
        "default_confirmation": False,
        "risk": "low",
    },
    # --- SCRITTURA ---
    {
        "key": "registra_vendita",
        "label": "Registra vendita",
        "description": "Il bot può registrare una nuova vendita specificando prodotto, quantità e data. Decrementa lo stock automaticamente.",
        "category": "write",
        "default_roles": ["agent", "supervisor", "admin"],
        "default_confirmation": True,
        "risk": "medium",
    },
    {
        "key": "carica_stock",
        "label": "Carica stock",
        "description": "Il bot può aggiungere un nuovo carico/lotto a un prodotto, incrementando lo stock.",
        "category": "write",
        "default_roles": ["supervisor", "admin"],
        "default_confirmation": True,
        "risk": "medium",
    },
    {
        "key": "annulla_vendita",
        "label": "Annulla vendita",
        "description": "Il bot può annullare una vendita registrata e ripristinare lo stock. Operazione irreversibile.",
        "category": "write",
        "default_roles": ["admin"],
        "default_confirmation": True,
        "risk": "high",
    },
    # --- CATALOGO ---
    {
        "key": "crea_prodotto",
        "label": "Crea prodotto",
        "description": "Il bot può creare nuovi prodotti nel catalogo MEDIC con nome, unità, prezzo e soglia di allerta.",
        "category": "catalog",
        "default_roles": ["admin"],
        "default_confirmation": True,
        "risk": "medium",
    },
]

_ACTIONS_BY_KEY: dict[str, dict] = {a["key"]: a for a in AI_ACTIONS}


# ── Pydantic schemas ──────────────────────────────────────────────────────────
class AiActionOut(BaseModel):
    key: str
    label: str
    description: str
    category: str
    risk: str
    # configurable fields
    enabled: bool
    allowed_roles: Optional[list[str]]
    allowed_user_ids: Optional[list[str]]
    requires_confirmation: bool


class AiActionUpdate(BaseModel):
    enabled: Optional[bool] = None
    allowed_roles: Optional[list[str]] = None          # None = keep, [] = clear to "all"
    allowed_user_ids: Optional[list[str]] = None
    requires_confirmation: Optional[bool] = None
    clear_roles: bool = False           # explicit flag to set allowed_roles = null (all)
    clear_users: bool = False           # explicit flag to set allowed_user_ids = null


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _get_or_create(db: AsyncSession, action_key: str) -> AiActionConfig:
    """Return existing config row or create with defaults."""
    result = await db.execute(
        select(AiActionConfig).where(
            AiActionConfig.org_id == MEDIC_ORG_ID,
            AiActionConfig.action_key == action_key,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return row
    defn = _ACTIONS_BY_KEY.get(action_key, {})
    row = AiActionConfig(
        org_id=MEDIC_ORG_ID,
        action_key=action_key,
        enabled=True,
        allowed_roles=defn.get("default_roles"),
        allowed_user_ids=None,
        requires_confirmation=defn.get("default_confirmation", False),
    )
    db.add(row)
    await db.flush()
    return row


def _serialize(action_def: dict, cfg: AiActionConfig) -> AiActionOut:
    return AiActionOut(
        key=action_def["key"],
        label=action_def["label"],
        description=action_def["description"],
        category=action_def["category"],
        risk=action_def["risk"],
        enabled=cfg.enabled,
        allowed_roles=cfg.allowed_roles,
        allowed_user_ids=[str(u) for u in cfg.allowed_user_ids] if cfg.allowed_user_ids else cfg.allowed_user_ids,
        requires_confirmation=cfg.requires_confirmation,
    )


# ── Routes ────────────────────────────────────────────────────────────────────
@router.get("/ai-actions", response_model=list[AiActionOut])
async def list_ai_actions(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Return all AI actions with their current configuration."""
    # Fetch all existing configs for this org
    result = await db.execute(
        select(AiActionConfig).where(AiActionConfig.org_id == MEDIC_ORG_ID)
    )
    existing: dict[str, AiActionConfig] = {r.action_key: r for r in result.scalars().all()}

    out = []
    for defn in AI_ACTIONS:
        if defn["key"] not in existing:
            cfg = await _get_or_create(db, defn["key"])
        else:
            cfg = existing[defn["key"]]
        out.append(_serialize(defn, cfg))

    await db.commit()
    return out


@router.get("/ai-actions/users", response_model=list[dict])
async def list_users_for_ai(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Return users eligible for per-user AI action assignment."""
    result = await db.execute(
        select(User.id, User.display_name, User.email, User.role).where(
            User.org_id == MEDIC_ORG_ID,
            User.is_active,
            ~User.email.like("__deleted__%"),
        ).order_by(User.display_name)
    )
    rows = result.all()
    return [
        {
            "id": str(r.id),
            "display_name": r.display_name or r.email,
            "role": r.role,
        }
        for r in rows
    ]


@router.patch("/ai-actions/{action_key}", response_model=AiActionOut)
async def update_ai_action(
    action_key: str,
    body: AiActionUpdate,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update configuration for a specific AI action."""
    if action_key not in _ACTIONS_BY_KEY:
        raise HTTPException(status_code=404, detail="Action not found")

    cfg = await _get_or_create(db, action_key)

    if body.enabled is not None:
        cfg.enabled = body.enabled

    if body.clear_roles:
        cfg.allowed_roles = None
    elif body.allowed_roles is not None:
        cfg.allowed_roles = body.allowed_roles if body.allowed_roles else None

    if body.clear_users:
        cfg.allowed_user_ids = None
    elif body.allowed_user_ids is not None:
        cfg.allowed_user_ids = body.allowed_user_ids if body.allowed_user_ids else None

    if body.requires_confirmation is not None:
        cfg.requires_confirmation = body.requires_confirmation

    await db.commit()
    await db.refresh(cfg)
    return _serialize(_ACTIONS_BY_KEY[action_key], cfg)
