"""Admin API — gestione connector."""
from __future__ import annotations
from typing import Optional
from uuid import uuid4
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.db.engine import get_db_session
from app.db.models import Connector
from app.dependencies import get_current_user, CurrentUser
from app.services.connectors import get_connector_registry
from app.services.connectors.catalog import CONNECTOR_CATALOG
from app.services.encryption import decrypt_config, encrypt_config, mask_config

log = structlog.get_logger()
router = APIRouter()


def _require_admin(user: CurrentUser):
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")
    return user


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ConnectorConfigIn(BaseModel):
    config: dict


class ConnectorRolesIn(BaseModel):
    allowed_roles: Optional[list[str]] = None  # None = tutti i ruoli


class ConnectorOut(BaseModel):
    type: str
    name: str
    description: str
    icon: str
    category: str
    is_enabled: bool
    status: str
    status_msg: Optional[str]
    tested_at: Optional[str]
    fields: list[dict]  # schema campi
    config: Optional[dict]  # valori correnti (mascherati)
    allowed_roles: Optional[list[str]]  # None = tutti i ruoli

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/connectors", response_model=list[ConnectorOut])
async def list_connectors(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Lista tutti i connector disponibili con stato attuale."""
    _require_admin(user)
    org_id = str(user.org_id)

    # Carica record DB
    result = await db.execute(select(Connector).where(Connector.org_id == org_id))
    db_rows: dict[str, Connector] = {r.type: r for r in result.scalars().all()}

    out = []
    for ctype, cdef in CONNECTOR_CATALOG.items():
        row = db_rows.get(ctype)
        config_current = None
        if row and row.config_enc:
            try:
                raw = decrypt_config(row.config_enc, settings.workmind_secret_key.get_secret_value())
                config_current = mask_config(raw, cdef.sensitive_keys)
            except Exception:
                config_current = {}

        out.append(ConnectorOut(
            type=ctype,
            name=cdef.name,
            description=cdef.description,
            icon=cdef.icon,
            category=cdef.category,
            is_enabled=row.is_enabled if row else False,
            status=row.status if row else "unconfigured",
            status_msg=row.status_msg if row else None,
            tested_at=row.tested_at.isoformat() if (row and row.tested_at) else None,
            fields=[{"key": f.key, "label": f.label, "type": f.type, "required": f.required,
                     "default": f.default, "hint": f.hint, "options": f.options}
                    for f in cdef.fields],
            config=config_current,
            allowed_roles=row.allowed_roles if row else None,
        ))
    return out


@router.put("/connectors/{connector_type}")
async def save_connector(
    connector_type: str,
    body: ConnectorConfigIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Salva/aggiorna la configurazione di un connector."""
    _require_admin(user)
    if connector_type not in CONNECTOR_CATALOG:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_type}' non esiste")

    org_id = str(user.org_id)
    secret = settings.workmind_secret_key.get_secret_value()
    cdef = CONNECTOR_CATALOG[connector_type]

    # Se il body contiene valori mascherati (••••••••), mantieni quelli vecchi
    result = await db.execute(
        select(Connector).where(Connector.org_id == org_id, Connector.type == connector_type)
    )
    existing = result.scalar_one_or_none()
    old_config = {}
    if existing and existing.config_enc:
        try:
            old_config = decrypt_config(existing.config_enc, secret)
        except Exception:
            pass

    # Merge: sostituisci solo i valori non mascherati
    merged = {**old_config}
    for k, v in body.config.items():
        if v != "••••••••":
            merged[k] = v

    encrypted = encrypt_config(merged, secret)

    if existing:
        existing.config_enc = encrypted
        existing.name = cdef.name
        existing.status = "configured"
        existing.status_msg = None
    else:
        db.add(Connector(
            id=uuid4(),
            org_id=org_id,
            type=connector_type,
            name=cdef.name,
            config_enc=encrypted,
            status="configured",
        ))
    await db.commit()
    log.info("connector_saved", type=connector_type, org_id=org_id)
    return {"ok": True}


@router.post("/connectors/{connector_type}/enable")
async def enable_connector(
    connector_type: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    result = await db.execute(
        select(Connector).where(Connector.org_id == str(user.org_id), Connector.type == connector_type)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Connector non configurato. Salva prima la configurazione.")
    row.is_enabled = True
    await db.commit()
    return {"ok": True}


@router.post("/connectors/{connector_type}/disable")
async def disable_connector(
    connector_type: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    result = await db.execute(
        select(Connector).where(Connector.org_id == str(user.org_id), Connector.type == connector_type)
    )
    row = result.scalar_one_or_none()
    if row:
        row.is_enabled = False
        await db.commit()
    return {"ok": True}


@router.post("/connectors/{connector_type}/test")
async def test_connector(
    connector_type: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    if connector_type not in CONNECTOR_CATALOG:
        raise HTTPException(404, f"Connector '{connector_type}' non esiste")
    ok, msg = await get_connector_registry().test_connector(db, str(user.org_id), connector_type)
    return {"ok": ok, "message": msg}


@router.patch("/connectors/{connector_type}/roles")
async def set_connector_roles(
    connector_type: str,
    body: ConnectorRolesIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Imposta i ruoli che possono usare questo connector. None = tutti."""
    _require_admin(user)
    result = await db.execute(
        select(Connector).where(Connector.org_id == str(user.org_id), Connector.type == connector_type)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Connector non configurato.")
    row.allowed_roles = body.allowed_roles or None
    await db.commit()
    log.info("connector_roles_updated", type=connector_type, roles=body.allowed_roles)
    return {"ok": True}


@router.delete("/connectors/{connector_type}")
async def delete_connector(
    connector_type: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    result = await db.execute(
        select(Connector).where(Connector.org_id == str(user.org_id), Connector.type == connector_type)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"ok": True}
