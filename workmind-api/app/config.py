"""
WorkMind API — Configuration
Pydantic Settings v2 with full validation at startup.
All settings sourced from environment variables or .env file.
"""
from __future__ import annotations

import secrets
from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import (
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    development = "development"
    staging = "staging"
    production = "production"


class WorkMindProfile(str, Enum):
    start = "start"    # DeepSeek + Claude API, no GPU
    pro = "pro"        # Ollama local + Claude fallback, GPU


class ModelRoutingConfig(BaseSettings):
    """Per-role routing table. Override via env vars to change routing without deploys."""
    fast_primary: str = "deepseek"
    fast_fallback: str = "claude"
    fast_claude_model: str = "claude-haiku-4-5"

    reliable_primary: str = "claude"
    reliable_fallback: str = "deepseek"
    reliable_claude_model: str = "claude-haiku-4-5"

    analyse_primary: str = "claude"
    analyse_fallback: str = "deepseek"
    analyse_claude_model: str = "claude-sonnet-4-6"

    chat_primary: str = "claude"
    chat_fallback: str = "claude"
    chat_claude_model: str = "claude-sonnet-4-6"

    local_model: str = "qwen2.5:14b"
    local_embed_model: str = "nomic-embed-text"

    model_config = SettingsConfigDict(env_prefix="MODEL_ROUTING_", extra="ignore")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Core ──────────────────────────────────────────────────────────────────
    workmind_env: Environment = Environment.production
    workmind_profile: WorkMindProfile = WorkMindProfile.start
    workmind_node_id: str = "bender"
    workmind_secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_hex(32))
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description="AsyncPG connection string: postgresql+asyncpg://user:pass@host/db",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        # Normalize: ensure asyncpg driver for async usage
        return v.replace("postgresql://", "postgresql+asyncpg://", 1) if "postgresql+asyncpg" not in v else v

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(..., description="Redis URL: redis://:password@host:6379/0")
    celery_broker_url: str = Field(default="")
    celery_result_backend: str = Field(default="")

    @model_validator(mode="after")
    def set_celery_defaults(self) -> "Settings":
        if not self.celery_broker_url:
            # Use DB 1 for broker (separate from cache on DB 0)
            self.celery_broker_url = self.redis_url.replace("/0", "/1")
        if not self.celery_result_backend:
            self.celery_result_backend = self.redis_url.replace("/0", "/2")
        return self

    # ── AI Providers ──────────────────────────────────────────────────────────
    deepseek_api_key: SecretStr = Field(default=SecretStr(""))
    anthropic_api_key: SecretStr = Field(default=SecretStr(""))
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_embed_model: str = "nomic-embed-text"

    workmind_deepseek_daily_limit: float = 5.0
    workmind_claude_daily_limit: float = 10.0

    ai_timeout_seconds: int = 60
    ai_max_retries: int = 3

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    api_key_header: str = "X-WorkMind-Key"
    internal_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_hex(32))
    )

    # ── Channels ──────────────────────────────────────────────────────────────
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_webhook_secret: SecretStr = Field(default=SecretStr(""))
    whatsapp_token: SecretStr = Field(default=SecretStr(""))
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: SecretStr = Field(default=SecretStr(""))
    twilio_account_sid: SecretStr = Field(default=SecretStr(""))
    twilio_auth_token: SecretStr = Field(default=SecretStr(""))

    # ── Channel / multi-org ───────────────────────────────────────────────────
    # UUID of the org that receives inbound channel messages (Telegram/WhatsApp).
    # Override with WORKMIND_CHANNEL_ORG_ID env var in multi-org setups.
    channel_org_id: Optional[str] = Field(default=None, alias="WORKMIND_CHANNEL_ORG_ID")

    # ── File upload ────────────────────────────────────────────────────────────
    upload_max_bytes: int = Field(default=52_428_800)  # 50 MB

    # ── Email / SMTP ──────────────────────────────────────────────────────────
    smtp_host: str = Field(default="smtps.aruba.it")
    smtp_port: int = Field(default=465)
    smtp_user: str = Field(default="workmind@faberweb.it")
    smtp_password: SecretStr = Field(default=SecretStr(""))
    smtp_from: str = Field(default="WorkMind MEDIC <workmind@faberweb.it>")
    smtp_ssl: bool = Field(default=True)   # True = SMTP_SSL (port 465)

    # ── Frontend ──────────────────────────────────────────────────────────────
    frontend_url: str = Field(default="https://workmind.bender")

    # ── Feature Flags ─────────────────────────────────────────────────────────
    feature_local_llm: bool = False
    feature_gpu_inference: bool = False
    feature_langflow_flows: bool = False
    feature_multiorg: bool = False
    feature_audit_export: bool = True
    feature_vector_reindex: bool = True

    # ── Anonymization ─────────────────────────────────────────────────────────
    anonymize_before_external_ai: bool = True
    anonymize_names: bool = False
    anonymize_ttl_seconds: int = 900   # 15 minutes

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"   # json | text

    # ── Model Routing ─────────────────────────────────────────────────────────
    @property
    def routing(self) -> ModelRoutingConfig:
        return ModelRoutingConfig()

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.workmind_env == Environment.production

    @property
    def is_pro_profile(self) -> bool:
        return self.workmind_profile == WorkMindProfile.pro

    @property
    def local_llm_enabled(self) -> bool:
        return self.is_pro_profile and self.feature_local_llm

    def get_deepseek_key(self) -> str:
        return self.deepseek_api_key.get_secret_value()

    def get_anthropic_key(self) -> str:
        return self.anthropic_api_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached settings singleton. Use FastAPI Depends(get_settings) to inject.
    Call invalidate_settings_cache() in tests to reset.
    """
    return Settings()


def invalidate_settings_cache() -> None:
    """Use in tests only."""
    get_settings.cache_clear()
