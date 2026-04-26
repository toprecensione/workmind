"""
WorkMind — Context Agent
Retrieves relevant DocumentChunks and Memories via pgvector cosine similarity
to build RAG context for the orchestrator.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.services.embedder import embedder

log = structlog.get_logger("workmind.context_agent")

_CHUNK_SQL = text(
    """
    SELECT
        dc.id::text          AS id,
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

_MEMORY_SQL = text(
    """
    SELECT
        m.id::text           AS id,
        m.content            AS content,
        m.metadata_json      AS metadata,
        1 - (m.embedding <=> :qvec::vector) AS score
    FROM memories m
    WHERE
        m.org_id = :org_id
        AND m.is_active = true
        AND m.embedding IS NOT NULL
    ORDER BY m.embedding <=> :qvec::vector
    LIMIT :top_k
    """
)


def _format_context(
    chunks: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> str:
    """Build a formatted context string to inject into the system prompt."""
    parts: list[str] = []

    if chunks:
        parts.append("## Documenti rilevanti dalla Knowledge Base\n")
        for i, c in enumerate(chunks, 1):
            score_pct = round(c["score"] * 100, 1)
            parts.append(f"[Documento {i} — rilevanza {score_pct}%]\n{c['content']}\n")

    if memories:
        parts.append("## Memorie conversazionali rilevanti\n")
        for i, m in enumerate(memories, 1):
            score_pct = round(m["score"] * 100, 1)
            parts.append(f"[Memoria {i} — rilevanza {score_pct}%]\n{m['content']}\n")

    return "\n".join(parts)


class ContextAgent(BaseAgent):
    name = "context_agent"

    async def run(self, query: str, context: dict) -> dict:
        """
        Retrieve RAG context for *query*.

        Expected context keys:
          - org_id: UUID
          - user_id: UUID | None
          - session: AsyncSession
          - top_k_chunks: int (default 5)
          - top_k_memories: int (default 3)

        Returns:
          {
            "chunks": [...],
            "memories": [...],
            "context_text": "formatted string for system prompt"
          }
        """
        org_id: uuid.UUID = context["org_id"]
        session: AsyncSession = context["session"]
        top_k_chunks: int = context.get("top_k_chunks", 5)
        top_k_memories: int = context.get("top_k_memories", 3)

        try:
            query_embedding = await embedder.embed_text(query)
        except Exception as exc:
            log.error("context_agent_embed_error", error=str(exc))
            return {"chunks": [], "memories": [], "context_text": ""}

        # Pgvector expects the vector as a string like '[0.1, 0.2, ...]'
        qvec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        org_id_str = str(org_id)

        # Retrieve matching chunks
        chunks: list[dict[str, Any]] = []
        try:
            rows = await session.execute(
                _CHUNK_SQL,
                {"qvec": qvec_str, "org_id": org_id_str, "top_k": top_k_chunks},
            )
            for row in rows.mappings():
                chunks.append(
                    {
                        "id": row["id"],
                        "content": row["content"],
                        "metadata": row["metadata"],
                        "score": float(row["score"]),
                    }
                )
        except Exception as exc:
            log.error("context_agent_chunk_query_error", error=str(exc))

        # Retrieve matching memories
        memories: list[dict[str, Any]] = []
        try:
            rows = await session.execute(
                _MEMORY_SQL,
                {"qvec": qvec_str, "org_id": org_id_str, "top_k": top_k_memories},
            )
            for row in rows.mappings():
                memories.append(
                    {
                        "id": row["id"],
                        "content": row["content"],
                        "metadata": row["metadata"],
                        "score": float(row["score"]),
                    }
                )
        except Exception as exc:
            log.error("context_agent_memory_query_error", error=str(exc))

        context_text = _format_context(chunks, memories)

        log.info(
            "context_agent_retrieved",
            chunks=len(chunks),
            memories=len(memories),
            org_id=str(org_id),
        )

        return {
            "chunks": chunks,
            "memories": memories,
            "context_text": context_text,
        }
