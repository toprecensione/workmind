"""
WorkMind API — Conversations Routes
GET    /api/conversations
POST   /api/conversations
GET    /api/conversations/:id
PATCH  /api/conversations/:id
DELETE /api/conversations/:id
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import ChannelType, Conversation, Message, MessageRole
from app.dependencies import AuthUser

log = structlog.get_logger("workmind.conversations")
router = APIRouter()


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: str


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    channel_type: str
    created_at: str
    updated_at: str
    messages: list[MessageOut]
    total_messages: int
    page: int
    page_size: int


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    channel_type: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    channel_type: str = "web"


class ConversationPatch(BaseModel):
    title: Optional[str] = None
    is_active: Optional[bool] = None


def _ct(val: Any) -> str:
    """channel_type is String in DB — handle both str and enum."""
    return val.value if hasattr(val, "value") else str(val)


def _role(val: Any) -> str:
    return val.value if hasattr(val, "value") else str(val)


def _provider(val: Any) -> Optional[str]:
    if val is None:
        return None
    return val.value if hasattr(val, "value") else str(val)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: AuthUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> list[ConversationSummary]:
    """List all conversations for the current org, newest first."""
    org_id = current_user.org_id
    offset = (page - 1) * page_size

    result = await db.execute(
        select(Conversation)
        .where(Conversation.org_id == org_id, Conversation.is_active == True)  # noqa: E712
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    conversations = result.scalars().all()

    output = []
    for conv in conversations:
        count_result = await db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conv.id)
        )
        count = count_result.scalar_one()
        output.append(ConversationSummary(
            id=conv.id,
            title=conv.title,
            channel_type=_ct(conv.channel_type),
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
            message_count=count,
        ))
    return output


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: AuthUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationOut:
    """Get a conversation with its messages (paginated)."""
    org_id = current_user.org_id

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    count_result = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .offset(offset)
        .limit(page_size)
    )
    messages = msgs_result.scalars().all()

    visible_roles = {MessageRole.user, MessageRole.assistant, "user", "assistant"}

    return ConversationOut(
        id=conv.id,
        title=conv.title,
        channel_type=_ct(conv.channel_type),
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        messages=[
            MessageOut(
                id=m.id,
                role=_role(m.role),
                content=m.content,
                provider=_provider(m.provider),
                model_name=m.model_name,
                created_at=m.created_at.isoformat(),
            )
            for m in messages
            if m.role in visible_roles
        ],
        total_messages=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
async def create_conversation(
    body: ConversationCreate,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
) -> ConversationSummary:
    """Create a new empty conversation for the caller."""
    org_id = current_user.org_id
    user_id = current_user.user_id

    try:
        ct = ChannelType(body.channel_type)
    except ValueError:
        ct = ChannelType.web

    conv = Conversation(
        org_id=org_id,
        user_id=user_id,
        channel_type=ct,
        title=body.title,
        is_active=True,
        metadata_json={},
    )
    db.add(conv)
    await db.flush()

    # Cache before commit
    conv_id = conv.id
    conv_title = conv.title
    conv_ct = _ct(conv.channel_type)
    conv_created = conv.created_at.isoformat()
    conv_updated = conv.updated_at.isoformat()

    await db.commit()
    log.info("conversation_created", conversation_id=str(conv_id), org_id=str(org_id))

    return ConversationSummary(
        id=conv_id,
        title=conv_title,
        channel_type=conv_ct,
        created_at=conv_created,
        updated_at=conv_updated,
        message_count=0,
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationSummary,
    summary="Update a conversation (title, active state)",
)
async def patch_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatch,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
) -> ConversationSummary:
    """Update conversation title or active/closed state."""
    org_id = current_user.org_id

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if body.title is not None:
        conv.title = body.title
    if body.is_active is not None:
        conv.is_active = body.is_active

    # Cache values before commit (prevents MissingGreenlet on expired attrs)
    conv_id = conv.id
    conv_title = conv.title
    conv_ct = _ct(conv.channel_type)
    conv_created = conv.created_at.isoformat()

    count_result = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conv_id)
    )
    msg_count = count_result.scalar() or 0

    await db.commit()
    log.info("conversation_patched", conversation_id=str(conv_id))

    # Fetch updated_at after commit via fresh query
    upd_result = await db.execute(
        select(Conversation.updated_at).where(Conversation.id == conv_id)
    )
    updated_at = upd_result.scalar_one()

    return ConversationSummary(
        id=conv_id,
        title=conv_title,
        channel_type=conv_ct,
        created_at=conv_created,
        updated_at=updated_at.isoformat(),
        message_count=msg_count,
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete a conversation (sets is_active=False)."""
    org_id = current_user.org_id

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.is_active = False
    await db.commit()
    log.info("conversation_deleted", conversation_id=str(conversation_id))
