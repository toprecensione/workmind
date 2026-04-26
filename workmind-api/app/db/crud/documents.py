"""
WorkMind API — CRUD: Documents & Document Chunks
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentStatus


async def get_document(db: AsyncSession, doc_id: uuid.UUID) -> Optional[Document]:
    result = await db.execute(select(Document).where(Document.id == doc_id))
    return result.scalar_one_or_none()


async def get_document_by_hash(
    db: AsyncSession, content_hash: str, org_id: uuid.UUID
) -> Optional[Document]:
    result = await db.execute(
        select(Document).where(
            Document.content_hash == content_hash,
            Document.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_documents(
    db: AsyncSession,
    org_id: uuid.UUID,
    status: Optional[DocumentStatus] = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Document]:
    q = select(Document).where(Document.org_id == org_id)
    if status:
        q = q.where(Document.status == status)
    q = q.order_by(Document.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def create_document(
    db: AsyncSession,
    org_id: uuid.UUID,
    filename: str,
    content_hash: Optional[str] = None,
    mime_type: Optional[str] = None,
    source_path: Optional[str] = None,
    metadata: Optional[dict] = None,
    user_id: Optional[uuid.UUID] = None,
) -> Document:
    doc = Document(
        org_id=org_id,
        user_id=user_id,
        filename=filename,
        content_hash=content_hash,
        mime_type=mime_type,
        source_path=source_path,
        status=DocumentStatus.pending,
        metadata_json=metadata or {},
    )
    db.add(doc)
    await db.flush()
    return doc


async def similarity_search(
    db: AsyncSession,
    org_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.7,
) -> list[dict]:
    """
    pgvector cosine similarity search on document_chunks.
    Returns top_k chunks ordered by similarity.

    NOTE: The IVFFlat index must be built manually after initial data load:
      CREATE INDEX CONCURRENTLY idx_chunks_embedding
      ON document_chunks USING ivfflat (embedding vector_cosine_ops)
      WITH (lists = 100);
    """
    from sqlalchemy import text

    result = await db.execute(
        text("""
            SELECT
                dc.id,
                dc.document_id,
                dc.content,
                dc.chunk_index,
                dc.meta_json,
                1 - (dc.embedding <=> CAST(:query_vec AS vector)) AS similarity
            FROM document_chunks dc
            WHERE dc.org_id = :org_id
              AND dc.embedding IS NOT NULL
              AND 1 - (dc.embedding <=> CAST(:query_vec AS vector)) >= :min_sim
            ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
            LIMIT :top_k
        """),
        {
            "query_vec": str(query_embedding),
            "org_id": org_id,
            "min_sim": min_similarity,
            "top_k": top_k,
        }
    )

    return [
        {
            "id": str(row.id),
            "document_id": str(row.document_id),
            "content": row.content,
            "chunk_index": row.chunk_index,
            "similarity": float(row.similarity),
            "metadata": row.meta_json,
        }
        for row in result.all()
    ]
