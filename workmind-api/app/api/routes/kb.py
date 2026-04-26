"""
WorkMind — Knowledge Base API Routes
Endpoints for file upload, directory scanning, document listing,
semantic search, and document deletion.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import mimetypes

from app.agents.file_agent import SUPPORTED_EXTENSIONS
from app.config import get_settings
from app.db.engine import get_db_session
from app.db.models import Document, DocumentStatus
from app.dependencies import AuthUser
from app.services.embedder import embedder
from app.tasks.kb import index_document

log = structlog.get_logger("workmind.kb")

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    dir_path: str


class ScanResponse(BaseModel):
    dir: str
    total_files_found: int
    indexed: int
    skipped: int
    failed: int
    errors: list[str]


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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/kb/scan",
    response_model=ScanResponse,
    summary="Scan a local directory and queue indexing tasks (async via Celery)",
)
async def scan_directory(
    body: ScanRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db_session),
) -> ScanResponse:
    """
    Recursively scan *dir_path* on the server filesystem, create pending
    Document records for new/changed files, and dispatch async Celery
    indexing tasks. Returns immediately with queued counts.
    Requires authentication. Scoped to the caller's org_id.
    """
    root = Path(body.dir_path)
    if not root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not a directory: {body.dir_path}",
        )

    total = 0
    queued = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            skipped += 1
            continue
        total += 1
        try:
            content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

            # Skip if already indexed at this path with the same hash
            stmt = select(Document).where(
                Document.org_id == user.org_id,
                Document.source_path == str(file_path),
                Document.content_hash == content_hash,
                Document.status == DocumentStatus.indexed,
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                skipped += 1
                continue

            doc = Document(
                org_id=user.org_id,
                title=file_path.name,
                filename=file_path.name,
                content_hash=content_hash,
                source_path=str(file_path),
                mime_type="application/octet-stream",
                status=DocumentStatus.pending,
                total_chunks=0,
                meta_json={},
                metadata_json={"scanned_from": body.dir_path},
            )
            session.add(doc)
            await session.flush()

            index_document.delay(str(doc.id), str(user.org_id), str(file_path))
            queued += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{file_path.name}: {str(exc)[:200]}")
            log.error("kb_scan_file_error", file=str(file_path), error=str(exc))

    log.info(
        "kb_scan_dispatched",
        dir=body.dir_path,
        total=total,
        queued=queued,
        skipped=skipped,
        failed=failed,
        org_id=str(user.org_id),
    )

    return ScanResponse(
        dir=body.dir_path,
        total_files_found=total,
        indexed=queued,
        skipped=skipped,
        failed=failed,
        errors=errors,
    )


@router.post(
    "/kb/upload",
    summary="Upload and index a single file (async via Celery)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file(
    user: AuthUser,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    settings=Depends(get_settings),
) -> dict[str, Any]:
    """
    Accept a file upload, persist it, create a Document record with
    status=pending, and dispatch an async Celery indexing task.
    Returns immediately with doc_id and task_id.
    """
    original_filename = file.filename or "upload"
    ext = Path(original_filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"File type '{ext}' is not supported. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    content = await file.read()

    # Enforce file size limit
    max_bytes = getattr(settings, "upload_max_bytes", 52_428_800)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({len(content):,} bytes). Maximum: {max_bytes:,} bytes.",
        )

    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    content_hash = hashlib.sha256(content).hexdigest()

    # Persist the file to a stable upload directory so the Celery worker can read it
    upload_dir = Path(os.environ.get("WORKMIND_UPLOAD_DIR", "/tmp/workmind_uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Use hash-based name to avoid collisions and enable deduplication
    file_path = upload_dir / f"{content_hash}{ext}"
    if not file_path.exists():
        file_path.write_bytes(content)

    # Infer MIME type from extension if client didn't provide it
    mime_type = (
        file.content_type
        if file.content_type and file.content_type != "application/octet-stream"
        else mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    )

    try:
        # Check for an existing indexed doc with the same hash to skip re-indexing
        stmt = select(Document).where(
            Document.org_id == user.org_id,
            Document.content_hash == content_hash,
            Document.status == DocumentStatus.indexed,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            log.info(
                "kb_upload_duplicate_skip",
                filename=original_filename,
                doc_id=str(existing.id),
            )
            return {
                "doc_id": str(existing.id),
                "filename": existing.filename,
                "status": existing.status.value,
                "task_id": None,
                "message": "Already indexed",
            }

        # Create a pending Document record
        doc = Document(
            org_id=user.org_id,
            title=original_filename,
            filename=original_filename,
            content_hash=content_hash,
            source_path=str(file_path),
            mime_type=mime_type,
            status=DocumentStatus.pending,
            total_chunks=0,
            meta_json={},
            metadata_json={"uploaded_by": "api", "original_filename": original_filename},
        )
        session.add(doc)
        await session.flush()

        # Dispatch Celery task — worker will index asynchronously
        task = index_document.delay(str(doc.id), str(user.org_id), str(file_path), mime_type)

        log.info(
            "kb_upload_dispatched",
            filename=original_filename,
            doc_id=str(doc.id),
            task_id=task.id,
        )

        return {
            "doc_id": str(doc.id),
            "filename": original_filename,
            "status": DocumentStatus.pending.value,
            "task_id": task.id,
            "message": "Indexing queued",
        }
    except Exception as exc:
        log.error("kb_upload_error", filename=original_filename, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {exc}",
        )


@router.get(
    "/kb/documents",
    response_model=list[DocumentOut],
    summary="List indexed documents",
)
async def list_documents(
    user: AuthUser,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentOut]:
    """
    List all documents for the caller's org, optionally filtered by status.
    Results are ordered by creation date descending.
    """
    stmt = (
        select(Document)
        .where(Document.org_id == user.org_id)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status_filter:
        try:
            doc_status = DocumentStatus(status_filter)
            stmt = stmt.where(Document.status == doc_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{status_filter}'. Valid: {[s.value for s in DocumentStatus]}",
            )

    result = await session.execute(stmt)
    docs = result.scalars().all()

    return [
        DocumentOut(
            id=str(doc.id),
            filename=doc.filename,
            source_path=doc.source_path,
            status=doc.status.value if hasattr(doc.status, "value") else doc.status,
            total_chunks=doc.total_chunks,
            content_hash=doc.content_hash,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat(),
        )
        for doc in docs
    ]


@router.get(
    "/kb/search",
    response_model=SearchResponse,
    summary="Semantic search in indexed documents",
)
async def search_kb(
    user: AuthUser,
    q: str = Query(..., min_length=1, max_length=1000, description="Search query"),
    top_k: int = Query(5, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    """
    Perform cosine-similarity vector search over document chunks.
    Returns the top-k most relevant chunks with similarity scores.
    """
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
        rows = await session.execute(
            sql,
            {"qvec": qvec_str, "org_id": org_id_str, "top_k": top_k},
        )
    except Exception as exc:
        log.error("kb_search_query_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search query failed: {exc}",
        )

    chunks = [
        ChunkOut(
            id=row["id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            score=float(row["score"]),
            metadata=row["metadata"] or {},
        )
        for row in rows.mappings()
    ]

    log.info("kb_search", query=q[:80], results=len(chunks), org_id=org_id_str)
    return SearchResponse(query=q, chunks=chunks)


@router.delete(
    "/kb/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all its chunks",
)
async def delete_document(
    doc_id: uuid.UUID,
    user: AuthUser,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """
    Permanently delete a document and all its associated chunks.
    Scoped to the caller's org_id (cannot delete documents from other orgs).
    """
    stmt = select(Document).where(
        Document.id == doc_id,
        Document.org_id == user.org_id,
    )
    result = await session.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {doc_id} not found",
        )

    await session.delete(doc)
    # DocumentChunks are deleted via ON DELETE CASCADE in the DB,
    # but we flush to ensure they are removed before response.
    await session.flush()

    log.info("kb_document_deleted", doc_id=str(doc_id), org_id=str(user.org_id))
