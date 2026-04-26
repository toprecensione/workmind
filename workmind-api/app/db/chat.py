"""
WorkMind API — Chat Route
POST /api/chat

Handles multi-turn conversations across all channels.
Persists messages to PostgreSQL, anonymizes PII before AI calls,
records model usage, and enforces rate limits.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_db_session
from app.db.models import ChannelType, Conversation, Message, MessageRole
from app.services.anonymizer import Anonymizer, get_anonymizer
from app.services.embedder import embedder
from app.db.crud.documents import similarity_search
from app.services.model_router import ModelRole, ModelRouter, get_model_router

log = structlog.get_logger("workmind.chat")
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    conversation_id: Optional[uuid.UUID] = None
    message: str = Field(..., min_length=1, max_length=4096)
    channel: ChannelType = ChannelType.web
    metadata: dict = Field(default_factory=dict)

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, v: str) -> str:
        return v.strip()


class TokenUsage(BaseModel):
    input: int
    output: int


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    reply: str
    provider: str
    model: str
    latency_ms: int
    tokens: TokenUsage
    hallucination_warning: bool = False


# ── Dependency: get or create conversation ─────────────────────────────────────

async def _get_or_create_conversation(
    conversation_id: Optional[uuid.UUID],
    channel: ChannelType,
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
) -> Conversation:
    """Load existing conversation or create a new one."""
    from sqlalchemy import select

    if conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.org_id == org_id,
                Conversation.is_active,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {conversation_id} not found",
            )
        return conv

    # Create new conversation
    conv = Conversation(
        org_id=org_id,
        user_id=user_id,
        channel_type=channel,
    )
    db.add(conv)
    await db.flush()  # Get the generated ID without committing
    return conv


# ── Chat endpoint ──────────────────────────────────────────────────────────────

@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a message and get an AI response",
)
async def chat(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    router_svc: ModelRouter = Depends(get_model_router),
    anonymizer: Anonymizer = Depends(get_anonymizer),
) -> ChatResponse:
    """
    Multi-turn chat endpoint. Conversation state is stored in PostgreSQL.

    Auth: Bearer JWT or X-WorkMind-Key header.
    Rate limit: enforced by Nginx upstream config (100 req/min per IP).
    """
    # ── Auth resolution (Phase 1 stub; full JWT middleware in P0.8) ─
    org_id = _extract_org_id(request)
    user_id = _extract_user_id(request)

    # ── Load or create conversation ────────────────────────────────────────────
    conversation = await _get_or_create_conversation(
        body.conversation_id, body.channel, db, org_id, user_id
    )

    # ── Anonymize user message before external AI call ─────────────────────────
    session_key = f"anon:{conversation.id}:{len(body.message)}"
    anon_content = body.message

    if settings.anonymize_before_external_ai:
        anon_result = await anonymizer.anonymize(
            body.message,
            session_key=session_key,
        )
        anon_content = anon_result.anonymized_text

    # ── Persist user message ───────────────────────────────────────────────────
    user_msg = Message(
        org_id=org_id,
        conversation_id=conversation.id,
        role=MessageRole.user,
        content=body.message,
        content_anon=anon_content if anon_content != body.message else None,
    )
    db.add(user_msg)
    await db.flush()

    # ── Determine routing role based on channel and content ────────────────────
    model_role = _detect_role(body.message, body.channel)

    # ── Load conversation history for context ──────────────────────────────────
    from sqlalchemy import select

    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(20)  # Last 20 messages as context window
    )
    history = list(reversed(history_result.scalars().all()))

    # ── RAG: retrieve relevant KB chunks ─────────────────────────────────────
    kb_system_prompt = await _build_kb_context(body.message, org_id, db)

    # ── Call AI via ModelRouter ────────────────────────────────────────────────
    ai_response = await router_svc.complete(
        messages=history,
        current_message=anon_content,
        role=model_role,
        org_id=org_id,
        system_prompt=kb_system_prompt or None,
    )

    # ── De-anonymize AI response ───────────────────────────────────────────────
    reply_text = ai_response.text
    if settings.anonymize_before_external_ai and anon_content != body.message:
        reply_text = await anonymizer.deanonymize(ai_response.text, session_key=session_key)

    # ── Persist assistant message ──────────────────────────────────────────────
    from app.db.models import AIProvider, ModelRoleEnum

    assistant_msg = Message(
        org_id=org_id,
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=reply_text,
        content_anon=ai_response.text if ai_response.text != reply_text else None,
        provider=AIProvider(ai_response.provider),
        model_name=ai_response.model,
        model_role=ModelRoleEnum(model_role.value),
        input_tokens=ai_response.input_tokens,
        output_tokens=ai_response.output_tokens,
        cost_usd=ai_response.cost_usd,
        latency_ms=int(ai_response.latency_ms),
    )
    db.add(assistant_msg)

    # ── Record model usage ─────────────────────────────────────────────────────
    from app.db.models import ModelUsage

    usage = ModelUsage(
        org_id=org_id,
        provider=AIProvider(ai_response.provider),
        model_name=ai_response.model,
        model_role=ModelRoleEnum(model_role.value),
        input_tokens=ai_response.input_tokens,
        output_tokens=ai_response.output_tokens,
        cost_usd=ai_response.cost_usd,
        latency_ms=int(ai_response.latency_ms),
        success=True,
        conversation_id=conversation.id,
        message_id=assistant_msg.id,
    )
    db.add(usage)

    # ── Auto-title conversation on first exchange ──────────────────────────────
    if not conversation.title:
        conversation.title = body.message[:100]

    await db.commit()

    log.info(
        "chat_completed",
        conversation_id=str(conversation.id),
        provider=ai_response.provider,
        model=ai_response.model,
        input_tokens=ai_response.input_tokens,
        output_tokens=ai_response.output_tokens,
        latency_ms=int(ai_response.latency_ms),
    )

    return ChatResponse(
        conversation_id=conversation.id,
        message_id=assistant_msg.id,
        reply=reply_text,
        provider=ai_response.provider,
        model=ai_response.model,
        latency_ms=int(ai_response.latency_ms),
        tokens=TokenUsage(input=ai_response.input_tokens, output=ai_response.output_tokens),
        hallucination_warning=ai_response.metadata.get("hallucination_warning", False),
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _build_kb_context(
    message: str,
    org_id: uuid.UUID,
    db: AsyncSession,
    top_k: int = 5,
    min_similarity: float = 0.45,
) -> str:
    """
    Embed the user message, retrieve top-k KB chunks via pgvector,
    and return a formatted system-prompt block.
    Returns empty string if no relevant chunks found or on error.
    """
    try:
        query_vec = await embedder.embed_text(message)
        chunks = await similarity_search(
            db, org_id, query_vec, top_k=top_k, min_similarity=min_similarity
        )
    except Exception as exc:
        log.warning("rag_retrieval_failed", error=str(exc))
        return ""

    if not chunks:
        return ""

    lines = [
        "=== DOCUMENTI AZIENDALI ===",
        "Usa le informazioni seguenti per rispondere. "
        "Cita la fonte se pertinente. Non inventare dati non presenti.",
        "",
    ]
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata") or {}
        source = meta.get("source_path") or meta.get("filename") or "documento interno"
        lines.append(f"[{i}] (fonte: {source}, similarità: {chunk['similarity']:.2f})")
        lines.append(chunk["content"])
        lines.append("")

    log.info("rag_context_built", chunks=len(chunks), org_id=str(org_id))
    return "\n".join(lines)


def _detect_role(message: str, channel: ChannelType) -> ModelRole:
    """
    Classify the message intent to select the appropriate model role.
    Fast heuristic; no AI call required.
    """
    msg_lower = message.lower()

    factual_kw = ("contatt", "telefono", "email", "indirizzo", "sito", "partita iva")
    analysis_kw = ("analizza", "report", "riepilog", "riassumi", "classifica", "quant")

    if any(kw in msg_lower for kw in analysis_kw):
        return ModelRole.ANALYSE
    if any(kw in msg_lower for kw in factual_kw):
        return ModelRole.RELIABLE
    if channel in (ChannelType.telegram, ChannelType.whatsapp):
        return ModelRole.RELIABLE  # external-facing: always reliable tier
    return ModelRole.CHAT


def _extract_org_id(request: Request) -> uuid.UUID:
    """
    Extract org_id from JWT claims or fallback to default org.
    Phase 1 stub: returns hardcoded default org UUID until full JWT middleware lands.
    Replace with: return request.state.user.org_id
    """
    default_org = getattr(request.state, "org_id", None)
    if default_org:
        return default_org
    # Phase 1 fallback: single-org mode
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _extract_user_id(request: Request) -> Optional[uuid.UUID]:
    """Extract user_id from JWT claims. Phase 1 stub."""
    return getattr(request.state, "user_id", None)
