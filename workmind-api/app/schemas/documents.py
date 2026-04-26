"""
WorkMind API — Pydantic Schemas: Documents & Knowledge Base
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    total_chunks: int
    mime_type: Optional[str] = None
    created_at: str
    updated_at: str


class ChunkSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)
    top_k: int = Field(5, ge=1, le=20)
    min_similarity: float = Field(0.7, ge=0.0, le=1.0)


class ChunkSearchResult(BaseModel):
    document_id: uuid.UUID
    chunk_index: int
    content: str
    similarity: float
    metadata: dict = Field(default_factory=dict)


class TeachRequest(BaseModel):
    type: str = Field(..., pattern="^(fact|correction|process|glossary)$")
    content: str = Field(..., min_length=1, max_length=8192)
    correction_wrong: Optional[str] = None
    correction_right: Optional[str] = None
    process_name: Optional[str] = None
    glossary_term: Optional[str] = None

    model_config = {"json_schema_extra": {
        "example": {
            "type": "fact",
            "content": "Il fornitore Acme S.r.l. ha termini di pagamento a 60 giorni.",
        }
    }}


class TeachResponse(BaseModel):
    id: uuid.UUID
    type: str
    indexed: bool
    job_id: Optional[uuid.UUID] = None
