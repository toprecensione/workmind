"""
WorkMind API — Pydantic Schemas: Admin
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class ReindexRequest(BaseModel):
    scope: str = Field("all", pattern="^(all|documents|memories|kb)$")
    org_id: Optional[uuid.UUID] = None
    force: bool = False


class ReindexResponse(BaseModel):
    job_id: uuid.UUID
    celery_task_id: str
    estimated_documents: Optional[int] = None
    status: str = "queued"


class UsageSummary(BaseModel):
    provider: str
    model_name: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class JobOut(BaseModel):
    id: uuid.UUID
    job_type: str
    status: str
    celery_task_id: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class HealthCheck(BaseModel):
    status: str
    service: str
    uptime_seconds: int
    checks: dict = Field(default_factory=dict)
