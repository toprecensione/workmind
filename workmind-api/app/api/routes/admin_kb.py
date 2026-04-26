"""
WorkMind API — Admin KB (Knowledge Base) Routes
GET    /api/admin/kb/documents
DELETE /api/admin/kb/documents/{id}
GET    /api/admin/kb/search
GET    /api/admin/kb/watch-paths
POST   /api/admin/kb/watch-paths
PUT    /api/admin/kb/watch-paths/{id}
DELETE /api/admin/kb/watch-paths/{id}
POST   /api/admin/kb/watch-paths/{id}/scan
POST   /api/admin/kb/reindex
GET    /api/admin/kb/stats
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import Document, DocumentChunk, DocumentStatus, KbWatchPath
from app.dependencies import AdminUser

log = structlog.get_logger("workmind.admin_kb")
router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    filename: str
    source_path: Optional[str]
    status: str
    total_chunks: int
    content_hash: Optional[str]
    created_at: str
    updated_at: str


class ChunkOut(BaseModel):
    id: str
    chunk_index: int
    content: str
    score: float
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    chunks: list[ChunkOut]


class WatchPathOut(BaseModel):
    id: str
    path: str
    path_type: str
    is_enabled: bool
    last_scan_at: Optional[str]
    created_at: str


class WatchPathIn(BaseModel):
    path: str
    path_type: str = "local"
    is_enabled: bool = True


class WatchPathUpdate(BaseModel):
    path: Optional[str] = None
    path_type: Optional[str] = None
    is_enabled: Optional[bool] = None


# ── Background scan task ──────────────────────────────────────────────────────

async def _run_scan(watch_path_id: uuid.UUID, org_id: uuid.UUID, path: str) -> None:
    """Enumerate files in path, create Document records, dispatch Celery index tasks."""
    import hashlib
    from datetime import datetime, timezone
    from pathlib import Path
    from app.db.engine import get_session_factory
    from app.tasks.kb import index_document
    from app.agents.file_agent import SUPPORTED_EXTENSIONS

    log.info("kb_scan_started", watch_path_id=str(watch_path_id), path=path)
    queued = 0
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            root = Path(path)
            if root.exists():
                for fpath in root.rglob("*"):
                    if not fpath.is_file():
                        continue
                    if fpath.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    try:
                        content_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
                        existing = await session.execute(
                            select(Document).where(
                                Document.org_id == org_id,
                                Document.source_path == str(fpath),
                                Document.content_hash == content_hash,
                                Document.status == "indexed",
                            )
                        )
                        if existing.scalar_one_or_none():
                            continue
                        doc = Document(
                            org_id=org_id,
                            title=fpath.name,
                            filename=fpath.name,
                            content_hash=content_hash,
                            source_path=str(fpath),
                            mime_type="application/octet-stream",
                            status="pending",
                            total_chunks=0,
                            meta_json={},
                            metadata_json={"scanned_by": "watch_path", "watch_path_id": str(watch_path_id)},
                        )
                        session.add(doc)
                        await session.flush()
                        index_document.delay(str(doc.id), str(org_id), str(fpath))
                        queued += 1
                    except Exception as exc:
                        log.error("kb_scan_file_error", file=str(fpath), error=str(exc))

            result = await session.execute(
                select(KbWatchPath).where(
                    KbWatchPath.id == watch_path_id,
                    KbWatchPath.org_id == org_id,
                )
            )
            wp = result.scalar_one_or_none()
            if wp:
                wp.last_scan_at = datetime.now(timezone.utc)
            await session.commit()

        log.info("kb_scan_completed", watch_path_id=str(watch_path_id), queued=queued)
    except Exception as exc:
        log.error("kb_scan_failed", watch_path_id=str(watch_path_id), error=str(exc))


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/kb/documents", response_model=list[DocumentOut])
async def list_documents(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by document status"),
    search: Optional[str] = Query(None, description="Filename substring filter"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[DocumentOut]:
    """List all KB documents for the current organisation, with optional filters."""
    stmt = select(Document).where(Document.org_id == user.org_id)

    if status_filter is not None:
        try:
            stmt = stmt.where(Document.status == DocumentStatus(status_filter))
        except ValueError:
            return []
    if search:
        stmt = stmt.where(Document.filename.ilike(f"%{search}%"))

    stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    docs = result.scalars().all()

    return [
        DocumentOut(
            id=str(d.id),
            filename=d.filename,
            source_path=d.source_path,
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
            total_chunks=d.total_chunks,
            content_hash=d.content_hash,
            created_at=d.created_at.isoformat(),
            updated_at=d.updated_at.isoformat(),
        )
        for d in docs
    ]


@router.delete("/kb/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a document and all its associated chunks."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    # Chunks are deleted via CASCADE on the FK, but we log counts first
    chunk_count_res = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)
    )
    chunk_count = chunk_count_res.scalar() or 0

    await db.delete(doc)
    await db.commit()
    log.info("kb_document_deleted", doc_id=str(doc_id), chunks_removed=chunk_count)


@router.get("/kb/search", response_model=SearchResponse)
async def admin_search_kb(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
    q: str = Query(..., min_length=1, max_length=1000, description="Search query"),
    top_k: int = Query(5, ge=1, le=50),
) -> SearchResponse:
    """Semantic vector search over KB document chunks (admin scope)."""
    from app.services.embedder import embedder

    try:
        query_embedding = await embedder.embed_text(q)
    except Exception as exc:
        log.error("kb_search_embed_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service unavailable: {exc}",
        )

    qvec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    org_id_str = str(user.org_id)

    sql = text(
        """
        SELECT
            dc.id::text          AS id,
            dc.chunk_index       AS chunk_index,
            dc.content           AS content,
            dc.meta_json         AS metadata,
            1 - (dc.embedding <=> CAST(:qvec AS vector)) AS score
        FROM document_chunks dc
        WHERE
            dc.org_id = :org_id
            AND dc.embedding IS NOT NULL
        ORDER BY dc.embedding <=> CAST(:qvec AS vector)
        LIMIT :top_k
        """
    )

    try:
        rows = (await db.execute(sql, {"qvec": qvec_str, "org_id": org_id_str, "top_k": top_k})).mappings().all()
    except Exception as exc:
        log.error("kb_search_query_error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Search query failed: {exc}")

    chunks = [
        ChunkOut(
            id=row["id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            score=float(row["score"]),
            metadata=row["metadata"] or {},
        )
        for row in rows
    ]
    return SearchResponse(query=q, chunks=chunks)


@router.post("/kb/reindex", summary="Reindex all pending/failed documents")
async def reindex_documents(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Queue indexing tasks for all documents in pending or failed state."""
    from app.tasks.kb import index_document

    result = await db.execute(
        select(Document).where(
            Document.org_id == user.org_id,
            Document.status.in_([DocumentStatus.pending, DocumentStatus.failed]),
        )
    )
    docs = result.scalars().all()

    queued = 0
    for doc in docs:
        if doc.source_path:
            doc.status = DocumentStatus.pending
            index_document.delay(
                str(doc.id),
                str(doc.org_id),
                doc.source_path,
                doc.mime_type or "text/plain",
            )
            queued += 1

    await db.commit()
    log.info("kb_reindex_queued", queued=queued, org_id=str(user.org_id))
    return {"queued": queued}


@router.get("/kb/watch-paths", response_model=list[WatchPathOut])
async def list_watch_paths(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> list[WatchPathOut]:
    """List all KB watch paths for the current organisation."""
    result = await db.execute(
        select(KbWatchPath)
        .where(KbWatchPath.org_id == user.org_id)
        .order_by(KbWatchPath.created_at.asc())
    )
    paths = result.scalars().all()
    return [
        WatchPathOut(
            id=str(wp.id),
            path=wp.path,
            path_type=wp.path_type,
            is_enabled=wp.is_enabled,
            last_scan_at=wp.last_scan_at.isoformat() if wp.last_scan_at else None,
            created_at=wp.created_at.isoformat(),
        )
        for wp in paths
    ]


@router.post("/kb/watch-paths", response_model=WatchPathOut, status_code=status.HTTP_201_CREATED)
async def create_watch_path(
    body: WatchPathIn,
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> WatchPathOut:
    """Create a new KB watch path."""
    if body.path_type not in ("local", "smb"):
        raise HTTPException(status_code=400, detail="path_type deve essere 'local' o 'smb'")

    wp = KbWatchPath(
        org_id=user.org_id,
        path=body.path,
        path_type=body.path_type,
        is_enabled=body.is_enabled,
    )
    db.add(wp)
    await db.commit()
    await db.refresh(wp)

    log.info("kb_watch_path_created", path=body.path, org_id=str(user.org_id))
    return WatchPathOut(
        id=str(wp.id),
        path=wp.path,
        path_type=wp.path_type,
        is_enabled=wp.is_enabled,
        last_scan_at=wp.last_scan_at.isoformat() if wp.last_scan_at else None,
        created_at=wp.created_at.isoformat(),
    )


@router.put("/kb/watch-paths/{path_id}", response_model=WatchPathOut)
async def update_watch_path(
    path_id: uuid.UUID,
    body: WatchPathUpdate,
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> WatchPathOut:
    """Update an existing KB watch path."""
    result = await db.execute(
        select(KbWatchPath).where(
            KbWatchPath.id == path_id,
            KbWatchPath.org_id == user.org_id,
        )
    )
    wp = result.scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Watch path non trovato")

    if body.path is not None:
        wp.path = body.path
    if body.path_type is not None:
        if body.path_type not in ("local", "smb"):
            raise HTTPException(status_code=400, detail="path_type deve essere 'local' o 'smb'")
        wp.path_type = body.path_type
    if body.is_enabled is not None:
        wp.is_enabled = body.is_enabled

    await db.commit()
    await db.refresh(wp)

    log.info("kb_watch_path_updated", path_id=str(path_id), changes=body.model_dump(exclude_none=True))
    return WatchPathOut(
        id=str(wp.id),
        path=wp.path,
        path_type=wp.path_type,
        is_enabled=wp.is_enabled,
        last_scan_at=wp.last_scan_at.isoformat() if wp.last_scan_at else None,
        created_at=wp.created_at.isoformat(),
    )


@router.delete("/kb/watch-paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_path(
    path_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a KB watch path."""
    result = await db.execute(
        select(KbWatchPath).where(
            KbWatchPath.id == path_id,
            KbWatchPath.org_id == user.org_id,
        )
    )
    wp = result.scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Watch path non trovato")

    await db.delete(wp)
    await db.commit()
    log.info("kb_watch_path_deleted", path_id=str(path_id))


@router.post("/kb/watch-paths/{path_id}/scan")
async def trigger_scan(
    path_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Trigger a background scan for a KB watch path."""
    result = await db.execute(
        select(KbWatchPath).where(
            KbWatchPath.id == path_id,
            KbWatchPath.org_id == user.org_id,
        )
    )
    wp = result.scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Watch path non trovato")

    if not wp.is_enabled:
        raise HTTPException(status_code=400, detail="Watch path disabilitato — abilitalo prima di scansionare")

    asyncio.create_task(_run_scan(wp.id, user.org_id, wp.path))
    log.info("kb_scan_queued", path_id=str(path_id), path=wp.path)
    return {"queued": True, "path": wp.path}


@router.get("/kb/stats")
async def get_kb_stats(
    user: AdminUser,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Knowledge base aggregate statistics."""

    # Total documents
    total_res = await db.execute(
        select(func.count(Document.id)).where(Document.org_id == user.org_id)
    )
    total_documents = total_res.scalar() or 0

    # Documents by status
    status_res = await db.execute(
        select(Document.status, func.count(Document.id))
        .where(Document.org_id == user.org_id)
        .group_by(Document.status)
    )
    by_status: dict[str, int] = {
        DocumentStatus.indexed.value: 0,
        DocumentStatus.failed.value: 0,
        DocumentStatus.processing.value: 0,
        DocumentStatus.pending.value: 0,
    }
    for row in status_res.all():
        status_val = row[0].value if hasattr(row[0], "value") else str(row[0])
        by_status[status_val] = row[1]

    # Total chunks
    chunks_res = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.org_id == user.org_id)
    )
    total_chunks = chunks_res.scalar() or 0

    # Watch paths
    wp_total_res = await db.execute(
        select(func.count(KbWatchPath.id)).where(KbWatchPath.org_id == user.org_id)
    )
    wp_total = wp_total_res.scalar() or 0

    wp_active_res = await db.execute(
        select(func.count(KbWatchPath.id)).where(
            KbWatchPath.org_id == user.org_id,
            KbWatchPath.is_enabled,
        )
    )
    wp_active = wp_active_res.scalar() or 0

    return {
        "total_documents": total_documents,
        "by_status": by_status,
        "total_chunks": total_chunks,
        "watch_paths_active": wp_active,
        "watch_paths_total": wp_total,
    }
