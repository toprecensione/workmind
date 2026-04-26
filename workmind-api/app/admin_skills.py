"""Admin API — gestione skill."""
from __future__ import annotations
from uuid import uuid4
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import Skill, Connector
from app.dependencies import get_current_user, CurrentUser
from app.services.skills.catalog import SKILL_CATALOG
from app.services.connectors.catalog import CONNECTOR_CATALOG

log = structlog.get_logger()
router = APIRouter()


def _require_admin(user: CurrentUser):
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")


class SkillConfigIn(BaseModel):
    config: dict = {}


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    category: str
    requires: list[str]
    is_enabled: bool
    config: dict
    config_schema: list[dict]
    requirements_met: bool          # True se tutti i connector richiesti sono configurati e abilitati
    requirements_detail: list[dict] # [{type, name, status, ok}]


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    org_id = str(user.org_id)

    result = await db.execute(select(Skill).where(Skill.org_id == org_id))
    db_skills: dict[str, Skill] = {s.skill_id: s for s in result.scalars().all()}

    conn_result = await db.execute(select(Connector).where(Connector.org_id == org_id))
    db_connectors: dict[str, Connector] = {c.type: c for c in conn_result.scalars().all()}

    out = []
    for sid, sdef in SKILL_CATALOG.items():
        sk = db_skills.get(sid)
        req_detail = []
        requirements_met = True

        # Per skill senza requires (low_stock_alert, daily_report) basta almeno telegram o smtp
        effective_requires = sdef.requires
        if not effective_requires and sid in ("low_stock_alert", "daily_report"):
            effective_requires = []  # gestito a runtime
            requirements_met = True

        for rtype in effective_requires:
            conn = db_connectors.get(rtype)
            ok = bool(conn and conn.is_enabled and conn.status == "ok")
            cdef = CONNECTOR_CATALOG.get(rtype)
            req_detail.append({
                "type": rtype,
                "name": cdef.name if cdef else rtype,
                "status": conn.status if conn else "unconfigured",
                "ok": ok,
            })
            if not ok:
                requirements_met = False

        out.append(SkillOut(
            id=sid,
            name=sdef.name,
            description=sdef.description,
            icon=sdef.icon,
            category=sdef.category,
            requires=sdef.requires,
            is_enabled=sk.is_enabled if sk else False,
            config=sk.config_json if sk else {},
            config_schema=[{
                "key": f.key, "label": f.label, "type": f.type,
                "required": f.required, "default": f.default,
                "hint": f.hint, "options": f.options,
            } for f in sdef.config_schema],
            requirements_met=requirements_met,
            requirements_detail=req_detail,
        ))
    return out


@router.post("/skills/{skill_id}/enable")
async def enable_skill(
    skill_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    if skill_id not in SKILL_CATALOG:
        raise HTTPException(404, f"Skill '{skill_id}' non esiste")
    org_id = str(user.org_id)

    result = await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.skill_id == skill_id))
    row = result.scalar_one_or_none()
    if row:
        row.is_enabled = True
    else:
        db.add(Skill(id=uuid4(), org_id=org_id, skill_id=skill_id, is_enabled=True, config_json={}))
    await db.commit()

    # Ricarica scheduler
    from app.services.skills import reload_skill_jobs
    from app.db.engine import get_session_factory as _gsf
    await reload_skill_jobs(_gsf())
    return {"ok": True}


@router.post("/skills/{skill_id}/disable")
async def disable_skill(
    skill_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    result = await db.execute(
        select(Skill).where(Skill.org_id == str(user.org_id), Skill.skill_id == skill_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.is_enabled = False
        await db.commit()

    from app.services.skills import reload_skill_jobs
    from app.db.engine import get_session_factory as _gsf
    await reload_skill_jobs(_gsf())
    return {"ok": True}


@router.put("/skills/{skill_id}/config")
async def update_skill_config(
    skill_id: str,
    body: SkillConfigIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(user)
    if skill_id not in SKILL_CATALOG:
        raise HTTPException(404, f"Skill '{skill_id}' non esiste")
    org_id = str(user.org_id)

    result = await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.skill_id == skill_id))
    row = result.scalar_one_or_none()
    if row:
        row.config_json = body.config
    else:
        db.add(Skill(id=uuid4(), org_id=org_id, skill_id=skill_id, is_enabled=False, config_json=body.config))
    await db.commit()
    return {"ok": True}
