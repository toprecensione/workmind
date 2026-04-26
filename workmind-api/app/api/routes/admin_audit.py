"""
WorkMind API — Admin Audit Log Routes
GET /api/admin/audit/logs        — paginated audit log with filters
GET /api/admin/audit/logs/export — CSV export (StreamingResponse)
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import AuditLog, AuditEventType
from app.dependencies import AdminUser

log = structlog.get_logger("workmind.admin_audit")
router = APIRouter()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/audit/logs")
async def list_audit_logs(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
    from_date: Optional[datetime] = Query(None, description="ISO datetime lower bound (inclusive)"),
    to_date: Optional[datetime] = Query(None, description="ISO datetime upper bound (inclusive)"),
    event_type: Optional[str] = Query(None, description="Filter by AuditEventType value"),
    user_id: Optional[UUID] = Query(None, description="Filter by user UUID"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """Return audit log entries with optional filters. Admin only."""

    stmt = select(AuditLog).where(AuditLog.org_id == user.org_id)

    if from_date is not None:
        stmt = stmt.where(AuditLog.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(AuditLog.created_at <= to_date)
    if event_type is not None:
        try:
            et = AuditEventType(event_type)
            stmt = stmt.where(AuditLog.event_type == et)
        except ValueError:
            # Unknown event type — return empty rather than 400
            return []
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": entry.id,
            "event_type": (
                entry.event_type.value
                if hasattr(entry.event_type, "value")
                else str(entry.event_type)
            ),
            "actor": entry.actor,
            "summary": entry.summary,
            "details_json": entry.details_json,
            "ip_address": str(entry.ip_address) if entry.ip_address else None,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "user_id": str(entry.user_id) if entry.user_id else None,
        }
        for entry in logs
    ]


@router.get("/audit/logs/export")
async def export_audit_logs(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    event_type: Optional[str] = Query(None),
) -> StreamingResponse:
    """Download audit logs as a CSV file. Admin only."""

    stmt = select(AuditLog).where(AuditLog.org_id == user.org_id)

    if from_date is not None:
        stmt = stmt.where(AuditLog.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(AuditLog.created_at <= to_date)
    if event_type is not None:
        try:
            et = AuditEventType(event_type)
            stmt = stmt.where(AuditLog.event_type == et)
        except ValueError:
            pass

    stmt = stmt.order_by(AuditLog.created_at.desc())
    result = await db.execute(stmt)
    entries = result.scalars().all()

    # Build CSV in-memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "event_type", "actor", "summary", "ip_address", "created_at"])
    for entry in entries:
        writer.writerow([
            entry.id,
            entry.event_type.value if hasattr(entry.event_type, "value") else str(entry.event_type),
            entry.actor,
            entry.summary,
            str(entry.ip_address) if entry.ip_address else "",
            entry.created_at.isoformat() if entry.created_at else "",
        ])

    output.seek(0)
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"audit_export_{today_str}.csv"

    log.info("audit_export", record_count=len(entries), org_id=str(user.org_id))

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
