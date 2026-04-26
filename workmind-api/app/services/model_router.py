"""
WorkMind API — Model Router Service
Selects AI provider and model based on role, profile, and budget.
Handles retry with exponential backoff and provider failover.
Feature-flag aware: routes to Ollama in PRO profile when FEATURE_LOCAL_LLM=true.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import AsyncGenerator, Optional, Sequence

import httpx
import structlog
from fastapi import Depends

from app.config import Settings, get_settings
from app.db.models import Message, MessageRole

log = structlog.get_logger("workmind.model_router")

# ── Token pricing table (USD per 1M tokens) ────────────────────────────────────

_MODEL_PRICES: dict[str, dict[str, float]] = {
    "deepseek-chat":         {"input": 0.07,  "output": 1.10},
    "claude-haiku-4-5":      {"input": 0.80,  "output": 4.00},
    "claude-haiku-3-5":      {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":     {"input": 3.00,  "output": 15.00},
    "claude-sonnet-3-7":     {"input": 3.00,  "output": 15.00},
    "claude-opus-4":         {"input": 15.00, "output": 75.00},
}

_PROVIDER_PRICE_FALLBACK: dict[str, dict[str, float]] = {
    "deepseek": {"input": 0.07,  "output": 1.10},
    "claude":   {"input": 3.00,  "output": 15.00},
    "ollama":   {"input": 0.00,  "output": 0.00},   # local = zero marginal cost
}

_DEEPSEEK_BASE = "https://api.deepseek.com"
_CLAUDE_BASE   = "https://api.anthropic.com"
_CLAUDE_API_VERSION = "2023-06-01"

MAX_RETRIES = 3
RETRY_BASE_S = 2.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ── Enums ──────────────────────────────────────────────────────────────────────

class ModelRole(str, Enum):
    FAST     = "fast"       # DeepSeek: classification, internal summaries
    RELIABLE = "reliable"   # Claude Haiku: customer-facing, factual
    ANALYSE  = "analyse"    # Claude Sonnet: complex analysis, reports
    CHAT     = "chat"       # Claude Sonnet: multi-turn supervisor chat
    VISION   = "vision"     # Claude Sonnet: OCR / image analysis
    LOCAL    = "local"      # Ollama (PRO profile only)


# ── Response dataclass ─────────────────────────────────────────────────────────

@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    metadata: dict = field(default_factory=dict)


# ── Custom exceptions ──────────────────────────────────────────────────────────

class BudgetExhaustedError(RuntimeError):
    """Raised when the daily budget for a provider is exhausted."""
    pass


# ── Model Router ───────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Central AI routing service. Injected into FastAPI routes via Depends().

    Routing is determined by:
    1. WORKMIND_PROFILE env var (start | pro)
    2. FEATURE_LOCAL_LLM flag (enables Ollama in PRO)
    3. ModelRole passed by the caller
    4. Daily budget limits (falls back if limit reached)
    5. Provider health (falls back on HTTP errors / timeouts)

    The HTTP client is synchronous (httpx.Client) wrapped in run_in_executor
    to avoid blocking the FastAPI event loop. This is intentional for Phase 1
    stability — async httpx client migration is a Phase 2 task.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.Client(timeout=settings.ai_timeout_seconds)
        self._daily_usage: dict[str, float] = {}  # provider -> today's cost USD

    # ── Public API ─────────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: Sequence[Message],
        current_message: str,
        role: ModelRole,
        org_id: Optional[uuid.UUID] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> AIResponse:
        """
        Route a completion request to the appropriate provider.
        Runs synchronous httpx calls in a thread pool executor.
        """
        primary, fallback, model_name = self._resolve_route(role)

        for provider, model in [(primary, model_name), (fallback, self._fallback_model(role))]:
            if not provider:
                continue
            if not self._check_budget(provider):
                log.warning("budget_exhausted_skip", provider=provider)
                continue
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda p=provider, m=model: self._call_with_retry(
                        p, m, messages, current_message, system_prompt, max_tokens, temperature
                    ),
                )
                self._record_cost(provider, response.input_tokens, response.output_tokens, model)
                log.info(
                    "ai_call_success",
                    provider=provider,
                    model=model,
                    role=role.value,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    latency_ms=response.latency_ms,
                    cost_usd=response.cost_usd,
                )
                return response
            except BudgetExhaustedError:
                log.warning("budget_exhausted_during_call", provider=provider)
                continue
            except Exception as exc:
                log.warning(
                    "provider_failed_trying_fallback",
                    provider=provider,
                    error=str(exc),
                    fallback=fallback,
                )

        raise RuntimeError(
            f"All AI providers failed for role={role.value}. "
            "Check provider API keys, budget limits, and connectivity."
        )

    # ── Route resolution ───────────────────────────────────────────────────────

    def _resolve_route(self, role: ModelRole) -> tuple[str, str, str]:
        """Returns (primary_provider, fallback_provider, primary_model_name)."""
        r = self._settings.routing

        if self._settings.local_llm_enabled:
            if role in (ModelRole.FAST, ModelRole.CHAT, ModelRole.LOCAL):
                return ("ollama", "claude", r.local_model)
            if role == ModelRole.ANALYSE:
                return ("claude", "ollama", r.analyse_claude_model)
            if role == ModelRole.RELIABLE:
                return ("claude", "ollama", r.reliable_claude_model)

        # START profile (or PRO with local LLM disabled)
        role_map = {
            ModelRole.FAST:     (r.fast_primary,     r.fast_fallback,     r.fast_claude_model),
            ModelRole.RELIABLE: (r.reliable_primary, r.reliable_fallback, r.reliable_claude_model),
            ModelRole.ANALYSE:  (r.analyse_primary,  r.analyse_fallback,  r.analyse_claude_model),
            ModelRole.CHAT:     (r.chat_primary,      r.chat_fallback,     r.chat_claude_model),
            ModelRole.VISION:   ("claude",            "",                  r.analyse_claude_model),
            ModelRole.LOCAL:    ("ollama",            "claude",            r.local_model),
        }
        return role_map.get(role, ("claude", "deepseek", r.analyse_claude_model))

    def _fallback_model(self, role: ModelRole) -> str:
        r = self._settings.routing
        if role in (ModelRole.ANALYSE, ModelRole.CHAT, ModelRole.VISION):
            return r.analyse_claude_model
        return r.fast_claude_model

    # ── Budget management ──────────────────────────────────────────────────────

    def _check_budget(self, provider: str) -> bool:
        if provider == "ollama":
            return True
        spent = self._daily_usage.get(provider, 0.0)
        if provider == "deepseek":
            return spent < self._settings.workmind_deepseek_daily_limit
        if provider == "claude":
            return spent < self._settings.workmind_claude_daily_limit
        return True

    def _record_cost(
        self, provider: str, input_tokens: int, output_tokens: int, model: str
    ) -> float:
        prices = _MODEL_PRICES.get(model, _PROVIDER_PRICE_FALLBACK.get(provider, {"input": 0, "output": 0}))
        cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
        self._daily_usage[provider] = self._daily_usage.get(provider, 0.0) + cost
        return cost

    # ── Retry wrapper ──────────────────────────────────────────────────────────

    def _call_with_retry(
        self,
        provider: str,
        model: str,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(self._settings.ai_max_retries):
            try:
                if provider == "deepseek":
                    return self._call_deepseek(messages, current_message, system_prompt, max_tokens, temperature)
                elif provider == "claude":
                    return self._call_claude(messages, current_message, system_prompt, max_tokens, temperature, model)
                elif provider == "ollama":
                    return self._call_ollama(messages, current_message, system_prompt, max_tokens, temperature, model)
                else:
                    raise ValueError(f"Unknown provider: {provider}")
            except httpx.TimeoutException as exc:
                last_exc = exc
                wait = RETRY_BASE_S * (2 ** attempt)
                log.warning("provider_timeout_retry", provider=provider, attempt=attempt + 1, wait_s=wait)
                time.sleep(wait)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in RETRYABLE_STATUS_CODES:
                    last_exc = exc
                    wait = RETRY_BASE_S * (2 ** attempt)
                    log.warning("provider_http_error_retry", provider=provider, status=exc.response.status_code, attempt=attempt + 1)
                    time.sleep(wait)
                else:
                    raise
        raise last_exc

    # ── DeepSeek ───────────────────────────────────────────────────────────────

    def _call_deepseek(
        self,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        key = self._settings.get_deepseek_key()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY not configured")

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            if msg.role in (MessageRole.user, MessageRole.assistant):
                payload_messages.append({"role": msg.role.value, "content": msg.content})
        payload_messages.append({"role": "user", "content": current_message})

        t0 = time.monotonic()
        resp = self._http.post(
            f"{_DEEPSEEK_BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": payload_messages, "max_tokens": max_tokens, "temperature": temperature},
        )
        resp.raise_for_status()
        latency_ms = (time.monotonic() - t0) * 1000

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        input_tok = usage.get("prompt_tokens", 0)
        output_tok = usage.get("completion_tokens", 0)
        cost = self._record_cost("deepseek", input_tok, output_tok, "deepseek-chat")

        return AIResponse(text=text, provider="deepseek", model="deepseek-chat",
                          input_tokens=input_tok, output_tokens=output_tok, cost_usd=cost, latency_ms=latency_ms)

    # ── Claude (Anthropic) ─────────────────────────────────────────────────────

    def _call_claude(
        self,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AIResponse:
        key = self._settings.get_anthropic_key()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        payload_messages = []
        for msg in messages:
            if msg.role in (MessageRole.user, MessageRole.assistant):
                payload_messages.append({"role": msg.role.value, "content": msg.content})
        payload_messages.append({"role": "user", "content": current_message})

        body: dict = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": payload_messages}
        if system_prompt:
            body["system"] = system_prompt

        t0 = time.monotonic()
        resp = self._http.post(
            f"{_CLAUDE_BASE}/v1/messages",
            headers={"x-api-key": key, "anthropic-version": _CLAUDE_API_VERSION, "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
        latency_ms = (time.monotonic() - t0) * 1000

        data = resp.json()
        text = data["content"][0]["text"]
        usage = data.get("usage", {})
        input_tok = usage.get("input_tokens", 0)
        output_tok = usage.get("output_tokens", 0)
        cost = self._record_cost("claude", input_tok, output_tok, model)

        return AIResponse(text=text, provider="claude", model=model,
                          input_tokens=input_tok, output_tokens=output_tok, cost_usd=cost, latency_ms=latency_ms)

    # ── Ollama (PRO profile) ───────────────────────────────────────────────────

    def _call_ollama(
        self,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AIResponse:
        base_url = self._settings.ollama_base_url.rstrip("/")
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            if msg.role in (MessageRole.user, MessageRole.assistant):
                payload_messages.append({"role": msg.role.value, "content": msg.content})
        payload_messages.append({"role": "user", "content": current_message})

        t0 = time.monotonic()
        resp = self._http.post(
            f"{base_url}/api/chat",
            json={"model": model, "messages": payload_messages, "stream": False,
                  "options": {"num_predict": max_tokens, "temperature": temperature}},
        )
        resp.raise_for_status()
        latency_ms = (time.monotonic() - t0) * 1000

        data = resp.json()
        text = data["message"]["content"]
        input_tok = data.get("prompt_eval_count", 0)
        output_tok = data.get("eval_count", 0)

        return AIResponse(text=text, provider="ollama", model=model,
                          input_tokens=input_tok, output_tokens=output_tok, cost_usd=0.0, latency_ms=latency_ms)

    # ── Streaming API ──────────────────────────────────────────────────────────

    async def complete_stream(
        self,
        messages: Sequence[Message],
        current_message: str,
        role: ModelRole,
        org_id: Optional[uuid.UUID] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> AsyncGenerator[str, None]:
        """
        Stream text chunks from AI provider. Yields str chunks as they arrive.
        Falls back to secondary provider on failure.
        """
        primary, fallback, model_name = self._resolve_route(role)

        for provider, model in [(primary, model_name), (fallback, self._fallback_model(role))]:
            if not provider or not self._check_budget(provider):
                continue
            try:
                if provider == "claude":
                    async for chunk in self._stream_claude(
                        messages, current_message, system_prompt, max_tokens, temperature, model
                    ):
                        yield chunk
                elif provider == "deepseek":
                    async for chunk in self._stream_deepseek(
                        messages, current_message, system_prompt, max_tokens, temperature
                    ):
                        yield chunk
                elif provider == "ollama":
                    async for chunk in self._stream_ollama(
                        messages, current_message, system_prompt, max_tokens, temperature, model
                    ):
                        yield chunk
                return  # success — don't try fallback
            except Exception as exc:
                log.warning(
                    "stream_provider_failed_trying_fallback",
                    provider=provider,
                    error=str(exc),
                    fallback=fallback,
                )
                continue

        # All providers failed
        yield "\n\n[Errore: nessun provider AI disponibile. Riprova più tardi.]"

    async def _stream_claude(
        self,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AsyncGenerator[str, None]:
        key = self._settings.get_anthropic_key()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        payload_messages = []
        for msg in messages:
            if msg.role in (MessageRole.user, MessageRole.assistant):
                payload_messages.append({"role": msg.role.value, "content": msg.content})
        payload_messages.append({"role": "user", "content": current_message})

        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": payload_messages,
            "stream": True,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=self._settings.ai_timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{_CLAUDE_BASE}/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": _CLAUDE_API_VERSION,
                    "Content-Type": "application/json",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            if chunk:
                                yield chunk

    async def _stream_deepseek(
        self,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator[str, None]:
        key = self._settings.get_deepseek_key()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY not configured")

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            if msg.role in (MessageRole.user, MessageRole.assistant):
                payload_messages.append({"role": msg.role.value, "content": msg.content})
        payload_messages.append({"role": "user", "content": current_message})

        async with httpx.AsyncClient(timeout=self._settings.ai_timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{_DEEPSEEK_BASE}/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": payload_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = data["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta

    async def _stream_ollama(
        self,
        messages: Sequence[Message],
        current_message: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AsyncGenerator[str, None]:
        base_url = self._settings.ollama_base_url.rstrip("/")
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            if msg.role in (MessageRole.user, MessageRole.assistant):
                payload_messages.append({"role": msg.role.value, "content": msg.content})
        payload_messages.append({"role": "user", "content": current_message})

        async with httpx.AsyncClient(timeout=self._settings.ai_timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": payload_messages,
                    "stream": True,
                    "options": {"num_predict": max_tokens, "temperature": temperature},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("done"):
                            break
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        continue

    def close(self) -> None:
        self._http.close()


# ── Dependency injection ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_cached_router() -> ModelRouter:
    return ModelRouter(get_settings())


def get_model_router(settings: Settings = Depends(get_settings)) -> ModelRouter:
    """FastAPI dependency. Returns the cached ModelRouter singleton."""
    return _get_cached_router()
