"""
WorkMind — Memory Agent
Extracts key facts from conversations via Claude and stores them as vector memories.
Also supports semantic retrieval of relevant memories.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.db.models import Memory
from app.services.embedder import embedder

log = structlog.get_logger("workmind.memory_agent")

_EXTRACT_PROMPT = (
    "Analizza la seguente conversazione ed estrai al massimo 5 fatti rilevanti e concreti "
    "che potrebbero essere utili in future conversazioni. "
    "Rispondi SOLO con i fatti, uno per riga, senza numerazione, senza prefissi, senza spiegazioni. "
    "Se non ci sono fatti rilevanti, rispondi con una riga vuota.\n\n"
    "Conversazione:\n{conversation}"
)

_MEMORY_SEARCH_SQL = text(
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


class MemoryAgent(BaseAgent):
    name = "memory_agent"

    async def extract_and_store(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        conversation_text: str,
        session: AsyncSession,
    ) -> int:
        """
        Use Claude to extract facts from *conversation_text*, embed them,
        and store them as Memory records.

        Returns the number of memories created.
        """
        import anthropic
        from app.config import get_settings

        settings = get_settings()
        api_key = settings.get_anthropic_key()
        if not api_key:
            log.warning("memory_agent_no_anthropic_key")
            return 0

        # Extract facts via Claude
        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            prompt = _EXTRACT_PROMPT.format(conversation=conversation_text[:8000])
            message = await client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text: str = message.content[0].text if message.content else ""
        except Exception as exc:
            log.error("memory_agent_extract_error", error=str(exc))
            return 0

        facts = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not facts:
            log.info("memory_agent_no_facts_extracted", org_id=str(org_id))
            return 0

        # Embed and store each fact
        created = 0
        for fact in facts[:5]:  # hard cap at 5
            try:
                embedding = await embedder.embed_text(fact)
                memory = Memory(
                    org_id=org_id,
                    user_id=user_id,
                    content=fact,
                    source="memory_agent",
                    embedding=embedding,
                    metadata_json={"extracted_by": "memory_agent"},
                    is_active=True,
                )
                session.add(memory)
                created += 1
            except Exception as exc:
                log.error("memory_agent_store_error", fact=fact[:100], error=str(exc))

        if created:
            await session.flush()
            log.info("memory_agent_stored", count=created, org_id=str(org_id))

        return created

    async def run(self, query: str, context: dict) -> dict:
        """
        Search memories relevant to *query*.

        Expected context keys:
          - org_id: UUID
          - session: AsyncSession
          - top_k: int (default 5)
        """
        org_id: uuid.UUID = context["org_id"]
        session: AsyncSession = context["session"]
        top_k: int = context.get("top_k", 5)

        try:
            query_embedding = await embedder.embed_text(query)
        except Exception as exc:
            log.error("memory_agent_embed_error", error=str(exc))
            return {"memories": []}

        qvec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        org_id_str = str(org_id)

        memories: list[dict[str, Any]] = []
        try:
            rows = await session.execute(
                _MEMORY_SEARCH_SQL,
                {"qvec": qvec_str, "org_id": org_id_str, "top_k": top_k},
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
            log.error("memory_agent_search_error", error=str(exc))

        return {"memories": memories}
