"""
WorkMind API — Teach Route
POST /api/teach

Allows supervisors to inject knowledge: facts, corrections, processes, glossary.
Content is stored as a Document and queued for vector indexing.
"""
from __future__ import annotations

import uuid
import os
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import Document, DocumentStatus
from app.dependencies import SupervisorUser

log = structlog.get_logger("workmind.teach")
router = APIRouter()


class TeachRequest(BaseModel):
    type: str = Field(..., pattern="^(fact|correction|process|glossary)$")
    content: str = Field(..., min_length=1, max_length=8192)
    correction_wrong: Optional[str] = None
    correction_right: Optional[str] = None
    process_name: Optional[str] = None
    glossary_term: Optional[str] = None


class TeachResponse(BaseModel):
    id: uuid.UUID
    type: str
    indexed: bool
    task_id: Optional[str] = None


@router.post(
    "/teach",
    response_model=TeachResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inject knowledge into the system",
)
async def teach(
    body: TeachRequest,
    current_user: SupervisorUser,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TeachResponse:
    """
    Supervisor/admin endpoint to teach facts, corrections, processes, glossary.
    Content is stored as a Document and queued for vector indexing via Celery.
    """
    org_id = current_user.org_id

    # Build metadata
    metadata: dict = {"teach_type": body.type}
    if body.correction_wrong:
        metadata["correction_wrong"] = body.correction_wrong
    if body.correction_right:
        metadata["correction_right"] = body.correction_right
    if body.process_name:
        metadata["process_name"] = body.process_name
    if body.glossary_term:
        metadata["glossary_term"] = body.glossary_term

    filename = f"teach_{body.type}_{uuid.uuid4().hex[:8]}.txt"

    # Write content to uploads dir so Celery worker can read it
    upload_dir = os.environ.get("WORKMIND_UPLOAD_DIR", "/home/emanuele/workmind-v2/uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(body.content)

    # title = first 120 chars of content
    title = body.content[:120].replace("\n", " ").strip()

    # Store Document record
    doc = Document(
        org_id=org_id,
        title=title,
        filename=filename,
        source_path=file_path,
        status=DocumentStatus.pending,
        metadata_json={**metadata},
    )
    db.add(doc)
    await db.flush()

    # Dispatch Celery task
    task_id: Optional[str] = None
    indexed = False
    try:
        from app.tasks.kb import index_document
        result = index_document.delay(str(doc.id), str(org_id), file_path, "text/plain")
        task_id = result.id
        log.info("teach_queued", doc_id=str(doc.id), task_id=task_id, type=body.type)
    except Exception as exc:
        log.warning("teach_celery_dispatch_failed", error=str(exc))
        # Document stored; admin can reindex manually via scan_watch_paths

    await db.commit()

    return TeachResponse(
        id=doc.id,
        type=body.type,
        indexed=indexed,
        task_id=task_id,
    )
