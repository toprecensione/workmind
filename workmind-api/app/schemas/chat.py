"""
WorkMind API — Pydantic Schemas: Chat
Request/response models for the chat and conversation endpoints.
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.db.models import ChannelType


class ChatRequest(BaseModel):
    conversation_id: Optional[uuid.UUID] = None
    message: str = Field(..., min_length=1, max_length=4096, description="User message text")
    channel: ChannelType = ChannelType.web
    metadata: dict = Field(default_factory=dict)

    @field_validator("message", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Message cannot be empty or whitespace only")
        return stripped

    model_config = {"json_schema_extra": {
        "example": {
            "message": "Qual è il numero di telefono del cliente Rossi?",
            "channel": "web",
        }
    }}


class TokenUsage(BaseModel):
    input: int = Field(..., description="Input tokens consumed")
    output: int = Field(..., description="Output tokens generated")

    @property
    def total(self) -> int:
        return self.input + self.output


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    reply: str
    provider: str = Field(..., description="AI provider used: deepseek | claude | ollama")
    model: str = Field(..., description="Model name used")
    latency_ms: int
    tokens: TokenUsage
    hallucination_warning: bool = False
    cost_usd: float = 0.0

    model_config = {"json_schema_extra": {
        "example": {
            "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
            "message_id": "660e8400-e29b-41d4-a716-446655440000",
            "reply": "Il cliente Rossi è raggiungibile al numero +39 333 123 4567.",
            "provider": "claude",
            "model": "claude-haiku-4-5",
            "latency_ms": 1250,
            "tokens": {"input": 120, "output": 45},
            "hallucination_warning": False,
            "cost_usd": 0.000232,
        }
    }}


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    provider: Optional[str] = None
    model_name: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None
    created_at: str


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    channel_type: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    channel_type: str
    created_at: str
    updated_at: str
    messages: list[MessageOut]
    total_messages: int
    page: int
    page_size: int
