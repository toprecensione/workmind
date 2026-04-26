"""
WorkMind API — CRUD: Conversations
Async SQLAlchemy helpers for conversation and message persistence.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChannelType, Conversation, Message, MessageRole


async def get_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    org_id: uuid.UUID,
) -> Optional[Conversation]:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
            Conversation.is_active,
        )
    )
    return result.scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    org_id: uuid.UUID,
    offset: int = 0,
    limit: int = 20,
    channel_type: Optional[ChannelType] = None,
) -> list[Conversation]:
    q = select(Conversation).where(
        Conversation.org_id == org_id,
        Conversation.is_active,
    )
    if channel_type:
        q = q.where(Conversation.channel_type == channel_type)
    q = q.order_by(desc(Conversation.updated_at)).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_conversations(db: AsyncSession, org_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.org_id == org_id,
            Conversation.is_active,
        )
    )
    return result.scalar_one()


async def create_conversation(
    db: AsyncSession,
    org_id: uuid.UUID,
    channel_type: ChannelType = ChannelType.web,
    user_id: Optional[uuid.UUID] = None,
    title: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Conversation:
    conv = Conversation(
        org_id=org_id,
        user_id=user_id,
        channel_type=channel_type,
        title=title,
        metadata_json=metadata or {},
    )
    db.add(conv)
    await db.flush()
    return conv


async def update_conversation_title(
    db: AsyncSession,
    conversation: Conversation,
    title: str,
) -> None:
    conversation.title = title[:512]


async def soft_delete_conversation(
    db: AsyncSession,
    conversation: Conversation,
) -> None:
    conversation.is_active = False


async def get_conversation_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
    roles: Optional[list[MessageRole]] = None,
) -> list[Message]:
    q = select(Message).where(Message.conversation_id == conversation_id)
    if roles:
        q = q.where(Message.role.in_(roles))
    q = q.order_by(Message.created_at).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_recent_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    limit: int = 20,
) -> list[Message]:
    """Returns last N messages in chronological order (for context window)."""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def count_messages(db: AsyncSession, conversation_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    )
    return result.scalar_one()
