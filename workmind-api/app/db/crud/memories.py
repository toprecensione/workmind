"""
WorkMind API — CRUD: Memories
Persistent facts extracted from conversations (mem0 integration point).
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory


async def create_memory(
    db: AsyncSession,
    org_id: uuid.UUID,
    content: str,
    source: str = "auto",
    user_id: Optional[uuid.UUID] = None,
    embedding: Optional[list[float]] = None,
    metadata: Optional[dict] = None,
) -> Memory:
    mem = Memory(
        org_id=org_id,
        user_id=user_id,
        content=content,
        source=source,
        embedding=embedding,
        metadata_json=metadata or {},
    )
    db.add(mem)
    await db.flush()
    return mem


async def list_memories(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> list[Memory]:
    q = select(Memory).where(Memory.org_id == org_id, Memory.is_active)
    if user_id:
        q = q.where(Memory.user_id == user_id)
    q = q.order_by(Memory.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def search_memories(
    db: AsyncSession,
    org_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.6,
) -> list[dict]:
    """Cosine similarity search on memories using pgvector."""
    result = await db.execute(
        text("""
            SELECT
                id, content, source, metadata_json,
                1 - (embedding <=> :query_vec::vector) AS similarity
            FROM memories
            WHERE org_id = :org_id
              AND is_active = TRUE
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :query_vec::vector) >= :min_sim
            ORDER BY embedding <=> :query_vec::vector
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
            "content": row.content,
            "source": row.source,
            "similarity": float(row.similarity),
            "metadata": row.metadata_json,
        }
        for row in result.all()
    ]


async def deactivate_memory(db: AsyncSession, memory_id: uuid.UUID) -> None:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    mem = result.scalar_one_or_none()
    if mem:
        mem.is_active = False
