"""
WorkMind — Orchestrator
Coordinates all agents to produce a final answer enriched with RAG context.
Schedules memory extraction as a background asyncio task after answering.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_agent import ContextAgent
from app.agents.data_agent import DataAgent
from app.agents.file_agent import FileAgent
from app.agents.memory_agent import MemoryAgent

log = structlog.get_logger("workmind.orchestrator")

_SYSTEM_PROMPT_TEMPLATE = (
    "Sei WorkMind, un assistente AI specializzato per le aziende. "
    "Rispondi in modo preciso, professionale e conciso. "
    "Usa le informazioni del contesto fornito quando rilevanti. "
    "Se il contesto non contiene le informazioni necessarie, dillo chiaramente.\n\n"
    "{context_section}"
)

_CONTEXT_SECTION = (
    "## Contesto dalla Knowledge Base\n\n"
    "{context_text}\n\n"
    "---\n\n"
)


def _build_system_prompt(context_text: str) -> str:
    if context_text.strip():
        context_section = _CONTEXT_SECTION.format(context_text=context_text)
    else:
        context_section = ""
    return _SYSTEM_PROMPT_TEMPLATE.format(context_section=context_section)


def _history_to_anthropic(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert WorkMind history format [{"role": ..., "content": ...}]
    to Anthropic messages format.
    Only 'user' and 'assistant' roles are forwarded (system is handled separately).
    """
    messages = []
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


class Orchestrator:
    """
    Main entry point for answering user queries with multi-agent RAG support.
    """

    def __init__(self) -> None:
        self.context_agent = ContextAgent()
        self.memory_agent = MemoryAgent()
        self.file_agent = FileAgent()
        self.data_agent = DataAgent()

    async def answer(
        self,
        query: str,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        history: list[dict[str, Any]],
        session: AsyncSession,
    ) -> str:
        """
        Produce a response to *query* using RAG context and conversation history.

        Steps:
        1. Retrieve RAG context (ContextAgent).
        2. Build system prompt with context.
        3. Call Claude with history + query.
        4. Schedule memory extraction in background.
        5. Return response text.
        """
        import anthropic
        from app.config import get_settings

        settings = get_settings()
        api_key = settings.get_anthropic_key()
        if not api_key:
            log.error("orchestrator_no_anthropic_key")
            return "Errore di configurazione: chiave Anthropic non disponibile."

        # Step 1: retrieve RAG context
        rag_context: dict[str, Any] = {}
        try:
            rag_context = await self.context_agent.run(
                query,
                {
                    "org_id": org_id,
                    "user_id": user_id,
                    "session": session,
                    "top_k_chunks": 5,
                    "top_k_memories": 3,
                },
            )
        except Exception as exc:
            log.error("orchestrator_context_error", error=str(exc))
            rag_context = {"chunks": [], "memories": [], "context_text": ""}

        context_text: str = rag_context.get("context_text", "")

        # Step 2: build system prompt
        system_prompt = _build_system_prompt(context_text)

        # Step 3: build messages (history + current query)
        messages = _history_to_anthropic(history)
        messages.append({"role": "user", "content": query})

        # Step 4: call Claude
        response_text = ""
        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            response = await client.messages.create(
                model=settings.routing.chat_claude_model,
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            )
            response_text = response.content[0].text if response.content else ""
            log.info(
                "orchestrator_claude_ok",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                org_id=str(org_id),
            )
        except Exception as exc:
            log.error("orchestrator_claude_error", error=str(exc))
            return f"Errore nella generazione della risposta: {exc}"

        # Step 5: schedule memory extraction in background
        if response_text:
            conversation_text = (
                f"Utente: {query}\nAssistente: {response_text}"
            )
            # We need a fresh session for the background task (original session may
            # already be committed by the endpoint). We obtain the factory lazily.
            asyncio.create_task(
                self._background_memory_store(org_id, user_id, conversation_text)
            )

        return response_text

    async def _background_memory_store(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        conversation_text: str,
    ) -> None:
        """Fire-and-forget background task to extract and store memories."""
        try:
            from app.db.engine import get_session_factory
            session_factory = get_session_factory()
            async with session_factory() as session:
                count = await self.memory_agent.extract_and_store(
                    org_id, user_id, conversation_text, session
                )
                await session.commit()
                log.info("orchestrator_memories_stored", count=count, org_id=str(org_id))
        except Exception as exc:
            log.error("orchestrator_background_memory_error", error=str(exc))


# Module-level singleton
orchestrator = Orchestrator()
