"""
WorkMind API — Channel Router Service
Shared pipeline for processing incoming messages from any channel (Telegram, WhatsApp, web).

Responsibilities:
- Find or create Channel record by (channel_type, external_id)
- Find or create a stub User linked to this channel (channel_refs JSONB)
- Find or create an open Conversation for this user+channel
- Anonymize input, call ModelRouter, de-anonymize output
- Persist user + assistant Messages and ModelUsage
- Return plain reply text to the caller (which sends it via channel API)
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import (
    AIProvider,
    Channel,
    ChannelType,
    Conversation,
    Message,
    MessageRole,
    ModelRoleEnum,
    ModelUsage,
    Organization,
    User,
)
from app.services.anonymizer import Anonymizer, get_anonymizer
from app.services.embedder import embedder
from app.db.crud.documents import similarity_search
from app.services.model_router import ModelRole, ModelRouter, get_model_router

log = structlog.get_logger("workmind.channel_router")

# Fallback used only when DB query fails AND no WORKMIND_CHANNEL_ORG_ID configured.
_DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ── Public entry point ─────────────────────────────────────────────────────────

async def handle_incoming_message(
    db: AsyncSession,
    channel_type: str,           # "telegram" | "whatsapp" | "web"
    external_id: str,            # Telegram chat_id (str), WhatsApp phone number, etc.
    text: str,
    user_display_name: str = "",
    settings: Optional[Settings] = None,
    router_svc: Optional[ModelRouter] = None,
    anonymizer: Optional[Anonymizer] = None,
) -> str:
    """
    Route an incoming channel message through the full AI pipeline.

    Returns the plain reply string that the caller should forward to the user
    via the appropriate channel API (Telegram sendMessage, WhatsApp messages, …).
    """
    if settings is None:
        settings = get_settings()
    if router_svc is None:
        router_svc = get_model_router(settings)
    if anonymizer is None:
        anonymizer = await get_anonymizer(settings)

    try:
        ct = ChannelType(channel_type)
    except ValueError:
        log.warning("channel_router_unknown_channel_type", channel_type=channel_type)
        ct = ChannelType.web

    # ── 1. Resolve org ─────────────────────────────────────────────────────────
    org_id = await _get_default_org_id(db, settings)

    # ── 2. Find / create Channel record ────────────────────────────────────────
    channel = await _get_or_create_channel(db, org_id, ct, external_id)

    # ── 3. Find / create stub User ─────────────────────────────────────────────
    user = await _get_or_create_channel_user(
        db, org_id, ct, external_id, user_display_name
    )

    # ── 4. Find / create open Conversation ────────────────────────────────────
    conversation = await _get_or_create_conversation(
        db, org_id, user.id, channel.id, ct, external_id
    )

    # ── 5. Anonymize ───────────────────────────────────────────────────────────
    session_key = f"anon:{conversation.id}:{external_id}"
    anon_content = text
    if settings.anonymize_before_external_ai:
        try:
            anon_result = await anonymizer.anonymize(text, session_key=session_key)
            anon_content = anon_result.anonymized_text
        except Exception as exc:
            log.warning("channel_router_anonymize_failed", error=str(exc))

    # ── 6. Persist user message ────────────────────────────────────────────────
    user_msg = Message(
        org_id=org_id,
        conversation_id=conversation.id,
        role=MessageRole.user,
        content=text,
        content_anon=anon_content if anon_content != text else None,
    )
    db.add(user_msg)
    await db.flush()

    # ── 7. Load recent history ─────────────────────────────────────────────────
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history = list(reversed(history_result.scalars().all()))

    # ── 8. Determine model role ────────────────────────────────────────────────
    model_role = _detect_role(text, ct)

    # ── 9. RAG: retrieve KB context ────────────────────────────────────────────
    kb_system_prompt = await _build_kb_context(text, org_id, db)

    # ── 10. Call AI ────────────────────────────────────────────────────────────
    ai_response = await router_svc.complete(
        messages=history,
        current_message=anon_content,
        role=model_role,
        org_id=org_id,
        system_prompt=kb_system_prompt or None,
    )

    # ── 11. De-anonymize ───────────────────────────────────────────────────────
    reply_text = ai_response.text
    if settings.anonymize_before_external_ai and anon_content != text:
        try:
            reply_text = await anonymizer.deanonymize(ai_response.text, session_key=session_key)
        except Exception as exc:
            log.warning("channel_router_deanonymize_failed", error=str(exc))

    # ── 11. Persist assistant message ──────────────────────────────────────────
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

    # ── 12. Record model usage ─────────────────────────────────────────────────
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

    # Auto-title on first exchange
    if not conversation.title:
        conversation.title = text[:100]

    await db.commit()

    log.info(
        "channel_router_completed",
        channel_type=channel_type,
        external_id=external_id,
        provider=ai_response.provider,
        model=ai_response.model,
        input_tokens=ai_response.input_tokens,
        output_tokens=ai_response.output_tokens,
        latency_ms=int(ai_response.latency_ms),
    )

    return reply_text


# ── Private helpers ────────────────────────────────────────────────────────────

async def _get_default_org_id(db: AsyncSession, settings: Optional[Settings] = None) -> uuid.UUID:
    """
    Resolve org for inbound channel messages.
    Priority: 1) WORKMIND_CHANNEL_ORG_ID env var  2) last-created active org  3) hardcoded fallback
    """
    # 1. Explicit config override
    if settings and settings.channel_org_id:
        try:
            return uuid.UUID(settings.channel_org_id)
        except ValueError:
            pass

    # 2. Most recently created active org (newest = real client, not default placeholder)
    try:
        result = await db.execute(
            select(Organization.id)
            .where(Organization.is_active == True)  # noqa: E712
            .order_by(Organization.id.desc())
            .limit(1)
        )
        org_id = result.scalar_one_or_none()
        if org_id:
            return org_id
    except Exception:
        pass

    return _DEFAULT_ORG_ID


async def _get_or_create_channel(
    db: AsyncSession,
    org_id: uuid.UUID,
    channel_type: ChannelType,
    external_id: str,
) -> Channel:
    """Find or create a Channel record for this (channel_type, external_id) pair."""
    result = await db.execute(
        select(Channel).where(
            Channel.org_id == org_id,
            Channel.channel_type == channel_type,
            Channel.external_id == external_id,
        )
    )
    channel = result.scalar_one_or_none()
    if channel:
        return channel

    channel = Channel(
        org_id=org_id,
        channel_type=channel_type,
        external_id=external_id,
        display_name=f"{channel_type.value}:{external_id}",
        is_active=True,
    )
    db.add(channel)
    await db.flush()
    log.info(
        "channel_created",
        channel_type=channel_type.value,
        external_id=external_id,
    )
    return channel


async def _get_or_create_channel_user(
    db: AsyncSession,
    org_id: uuid.UUID,
    channel_type: ChannelType,
    external_id: str,
    display_name: str,
) -> User:
    """
    Find a user whose channel_refs JSONB contains this channel's external_id,
    or create a minimal stub user.  channel_refs stores {channel_type: external_id}.
    """
    import hashlib

    # Derive a stable email-like identifier from channel + external_id
    # so we satisfy the unique (org_id, email_hash) constraint.
    fake_email = f"{channel_type.value}_{external_id}@channel.workmind.internal"
    email_hash = hashlib.sha256(fake_email.encode()).hexdigest()

    result = await db.execute(
        select(User).where(
            User.org_id == org_id,
            User.email_hash == email_hash,
        )
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        org_id=org_id,
        email=fake_email,
        email_hash=email_hash,
        display_name=display_name or f"{channel_type.value}:{external_id}",
        role="user",
        channel_refs={channel_type.value: external_id},
        is_active=True,
    )
    db.add(user)
    await db.flush()
    log.info(
        "channel_user_created",
        channel_type=channel_type.value,
        external_id=external_id,
    )
    return user


async def _get_or_create_conversation(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    channel_id: uuid.UUID,
    channel_type: ChannelType,
    external_id: str,
) -> Conversation:
    """Return the most recent active conversation for this user+channel, or create one."""
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.org_id == org_id,
            Conversation.user_id == user_id,
            Conversation.channel_id == channel_id,
            Conversation.is_active,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        org_id=org_id,
        user_id=user_id,
        channel_id=channel_id,
        channel_type=channel_type,
        metadata_json={"external_id": external_id},
    )
    db.add(conv)
    await db.flush()
    return conv


def _detect_role(message: str, channel_type: ChannelType) -> ModelRole:
    """Heuristic model role detection — mirrors chat.py logic."""
    msg_lower = message.lower()
    analysis_kw = ("analizza", "report", "riepilog", "riassumi", "classifica", "quant")
    if any(kw in msg_lower for kw in analysis_kw):
        return ModelRole.ANALYSE
    # External-facing channels always use the reliable tier
    if channel_type in (ChannelType.telegram, ChannelType.whatsapp):
        return ModelRole.RELIABLE
    return ModelRole.CHAT


async def _build_kb_context(
    message: str,
    org_id: uuid.UUID,
    db: AsyncSession,
    top_k: int = 5,
    min_similarity: float = 0.45,
) -> str:
    """Retrieve relevant KB chunks and format as system prompt block."""
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
