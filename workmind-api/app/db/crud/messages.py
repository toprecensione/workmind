"""
WorkMind API — CRUD: Messages
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIProvider, Message, MessageRole, ModelRoleEnum


async def create_user_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    content: str,
    content_anon: Optional[str] = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.user,
        content=content,
        content_anon=content_anon if content_anon and content_anon != content else None,
    )
    db.add(msg)
    await db.flush()
    return msg


async def create_assistant_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    content: str,
    content_anon: Optional[str] = None,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    model_role: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.assistant,
        content=content,
        content_anon=content_anon if content_anon and content_anon != content else None,
        provider=AIProvider(provider) if provider else None,
        model_name=model_name,
        model_role=ModelRoleEnum(model_role) if model_role else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )
    db.add(msg)
    await db.flush()
    return msg
