"""
WorkMind API — Admin Routes
POST /api/admin/reindex
GET  /api/admin/usage
GET  /api/admin/jobs
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import Job
from app.dependencies import get_current_user, CurrentUser

log = structlog.get_logger("workmind.admin")
router = APIRouter()


def _require_admin(user: CurrentUser) -> None:
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")


class ReindexRequest(BaseModel):
    scope: str = "all"     # all | documents | memories | kb
    org_id: Optional[uuid.UUID] = None
    force: bool = False


class ReindexResponse(BaseModel):
    job_id: uuid.UUID
    celery_task_id: str
    status: str


class UsageSummary(BaseModel):
    provider: str
    model_name: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


@router.post("/reindex", response_model=ReindexResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_reindex(
    body: ReindexRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ReindexResponse:
    _require_admin(current_user)
    """Trigger full re-indexing of documents. Admin only."""
    if not settings.feature_vector_reindex:
        raise HTTPException(status_code=503, detail="Vector reindex feature not enabled")

    org_id = body.org_id or uuid.UUID("00000000-0000-0000-0000-000000000001")

    job = Job(
        org_id=org_id,
        job_type="reindex_all",
        payload_json={"scope": body.scope, "force": body.force},
    )
    db.add(job)
    await db.flush()

    # Dispatch to Celery
    from celery import Celery
    celery_app = Celery(broker=settings.celery_broker_url)
    result = celery_app.send_task(
        "app.main.reindex_all",
        args=[str(org_id), body.scope, body.force],
        queue="indexing",
    )

    job.celery_task_id = result.id
    await db.commit()

    log.info("reindex_triggered", job_id=str(job.id), task_id=result.id, scope=body.scope)

    return ReindexResponse(
        job_id=job.id,
        celery_task_id=result.id,
        status="queued",
    )


@router.get("/usage")
async def get_usage_summary(
    days: int = 30,
    group_by_day: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    _require_admin(current_user)
    """Get model usage summary for the last N days.

    When group_by_day=True, returns a daily breakdown sorted by date ascending
    with fields: date, provider, model_name, total_calls, total_cost_usd.
    Otherwise returns an aggregate summary per provider/model.
    """
    if not settings.feature_audit_export:
        raise HTTPException(status_code=503, detail="Audit export not enabled")

    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text as sa_text
    since = datetime.now(timezone.utc) - timedelta(days=days)

    if group_by_day:
        result = await db.execute(
            sa_text("""
                SELECT
                    recorded_at::date AS day,
                    provider,
                    model_name,
                    count(id)              AS total_calls,
                    sum(input_tokens)      AS total_input,
                    sum(output_tokens)     AS total_output,
                    sum(cost_usd)          AS total_cost
                FROM model_usage
                WHERE recorded_at >= :since
                GROUP BY recorded_at::date, provider, model_name
                ORDER BY recorded_at::date ASC, sum(cost_usd) DESC
            """),
            {"since": since},
        )
        return [
            {
                "date": str(row.day),
                "provider": str(row.provider),
                "model_name": row.model_name,
                "total_calls": row.total_calls,
                "total_input_tokens": int(row.total_input or 0),
                "total_output_tokens": int(row.total_output or 0),
                "total_cost_usd": float(row.total_cost or 0),
            }
            for row in result.all()
        ]

    # Default aggregate view
    result = await db.execute(
        sa_text("""
            SELECT
                provider,
                model_name,
                count(id)              AS total_calls,
                sum(input_tokens)      AS total_input,
                sum(output_tokens)     AS total_output,
                sum(cost_usd)          AS total_cost
            FROM model_usage
            WHERE recorded_at >= :since
            GROUP BY provider, model_name
            ORDER BY sum(cost_usd) DESC
        """),
        {"since": since},
    )

    return [
        {
            "provider": str(row.provider),
            "model_name": row.model_name,
            "total_calls": row.total_calls,
            "total_input_tokens": int(row.total_input or 0),
            "total_output_tokens": int(row.total_output or 0),
            "total_cost_usd": float(row.total_cost or 0),
        }
        for row in result.all()
    ]


@router.get("/jobs", response_model=list[dict[str, Any]])
async def list_jobs(
    limit: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    _require_admin(current_user)
    """List recent background jobs."""
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc()).limit(limit)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "job_type": j.job_type,
            "status": j.status.value,
            "celery_task_id": j.celery_task_id,
            "retry_count": j.retry_count,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat(),
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]
