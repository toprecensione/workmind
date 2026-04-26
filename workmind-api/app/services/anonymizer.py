"""
WorkMind API — PII Anonymizer Service
Reversible anonymization for text sent to external AI providers.
Entity substitution map stored in Redis with configurable TTL.

Two operating modes:
  1. MASK (irreversible)  — for logs and audit records
  2. ANONYMIZE (reversible) — for AI API calls (map stored in Redis)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import redis.asyncio as aioredis
import structlog
from fastapi import Depends

from app.config import Settings, get_settings

log = structlog.get_logger("workmind.anonymizer")

# ── PII Pattern definitions ────────────────────────────────────────────────────

_PII_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "EMAIL",
        re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'),
        "***@***.***",
    ),
    (
        "CF",
        re.compile(r'\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b'),
        "CF:****",
    ),
    (
        "IBAN",
        re.compile(r'\b[A-Z]{2}\d{2}\s?[A-Z0-9]{4}(?:\s?\d{4}){5}(?:\s?\d{1,4})?\b'),
        "IBAN:****",
    ),
    (
        "PIVA",
        re.compile(r'\b(?:IT)?\d{11}\b'),
        "PIVA:****",
    ),
    (
        "PHONE",
        re.compile(r'\b(?:\+39\s?)?(?:0\d{1,4}[\s\-]?\d{4,8}|3\d{2}[\s\-]?\d{6,7})\b'),
        "TEL:****",
    ),
    (
        "CC",
        re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'),
        "CC:****",
    ),
    (
        "INTERNAL_IP",
        re.compile(
            r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|'
            r'10\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
            r'172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'
        ),
        "HOST:****",
    ),
    (
        "API_KEY",
        re.compile(r'\b[A-Za-z0-9_\-]{32,}\b'),
        "KEY:****",
    ),
]


# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class AnonymizeResult:
    anonymized_text: str
    entity_map: dict[str, str] = field(default_factory=dict)  # placeholder -> original
    entity_count: int = 0

    @property
    def has_pii(self) -> bool:
        return self.entity_count > 0


@dataclass
class MaskResult:
    masked_text: str
    detected_types: list[str] = field(default_factory=list)


# ── Anonymizer ────────────────────────────────────────────────────────────────

class Anonymizer:
    """
    Reversible PII anonymizer.

    anonymize() — replaces PII with typed placeholders, stores reverse map in Redis
    deanonymize() — restores original values using the Redis map
    mask() — irreversible masking for logs (no Redis storage)
    """

    def __init__(self, settings: Settings, redis_client: Optional[aioredis.Redis] = None) -> None:
        self._settings = settings
        self._redis = redis_client
        self._ttl = settings.anonymize_ttl_seconds

    # ── Public API ─────────────────────────────────────────────────────────────

    async def anonymize(
        self,
        text: str,
        session_key: str,
    ) -> AnonymizeResult:
        """
        Replace PII in text with numbered placeholders.
        Store the original values in Redis keyed by session_key.
        If Redis is unavailable, falls back to irreversible masking.
        """
        if not self._settings.anonymize_before_external_ai:
            return AnonymizeResult(anonymized_text=text)

        entity_map: dict[str, str] = {}
        counters: dict[str, int] = {}
        result_text = text

        for entity_type, pattern, _ in _PII_PATTERNS:
            for match in pattern.finditer(text):
                original = match.group()
                # Deterministic placeholder: same value gets same placeholder in this session
                value_hash = hashlib.md5(original.encode()).hexdigest()[:8]
                placeholder_key = f"{entity_type}_{value_hash}"
                placeholder = f"[{placeholder_key}]"

                if placeholder_key not in entity_map:
                    entity_map[placeholder_key] = original
                    counters[entity_type] = counters.get(entity_type, 0) + 1

                result_text = result_text.replace(original, placeholder)

        if entity_map and self._redis:
            try:
                redis_key = f"anon:{session_key}"
                await self._redis.setex(
                    redis_key,
                    self._ttl,
                    json.dumps(entity_map, ensure_ascii=False),
                )
            except Exception as exc:
                log.warning("anonymizer_redis_store_failed", error=str(exc))

        if entity_map:
            log.info(
                "pii_detected_anonymized",
                session_key=session_key,
                entity_types=list(counters.keys()),
                total_entities=sum(counters.values()),
            )

        return AnonymizeResult(
            anonymized_text=result_text,
            entity_map=entity_map,
            entity_count=sum(counters.values()),
        )

    async def deanonymize(self, text: str, session_key: str) -> str:
        """
        Restore original PII values in AI response text.
        If Redis key is missing (TTL expired), returns text as-is with a log warning.
        """
        if not self._redis:
            return text

        try:
            redis_key = f"anon:{session_key}"
            raw = await self._redis.get(redis_key)
            if not raw:
                log.warning(
                    "anonymizer_deanon_map_missing",
                    session_key=session_key,
                    hint="Redis TTL may have expired; returning anonymized response",
                )
                return text

            entity_map: dict[str, str] = json.loads(raw)
            result = text
            for placeholder_key, original in entity_map.items():
                result = result.replace(f"[{placeholder_key}]", original)
            return result

        except Exception as exc:
            log.warning("anonymizer_deanon_failed", session_key=session_key, error=str(exc))
            return text

    def mask(self, text: str) -> MaskResult:
        """
        Irreversible PII masking for logs and audit records.
        Does NOT use Redis. Always safe to call.
        """
        detected: list[str] = []
        result = text
        for entity_type, pattern, replacement in _PII_PATTERNS:
            new_result, n = pattern.subn(replacement, result)
            if n > 0:
                detected.append(entity_type)
                result = new_result
        return MaskResult(masked_text=result, detected_types=detected)

    def has_pii(self, text: str) -> bool:
        """Quick check: returns True if any PII pattern matches."""
        return any(pattern.search(text) for _, pattern, _ in _PII_PATTERNS)


# ── Dependency injection ───────────────────────────────────────────────────────

_anonymizer_instance: Optional[Anonymizer] = None


async def get_anonymizer(settings: Settings = Depends(get_settings)) -> Anonymizer:
    """FastAPI dependency. Lazily creates Anonymizer with Redis connection."""
    global _anonymizer_instance
    if _anonymizer_instance is None:
        redis_client = None
        try:
            redis_client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as exc:
            log.warning("anonymizer_redis_connect_failed", error=str(exc))
        _anonymizer_instance = Anonymizer(settings, redis_client)
    return _anonymizer_instance
