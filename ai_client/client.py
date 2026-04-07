"""
WorkMind Unified AI Client
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Interfaccia unificata per DeepSeek + Claude con:
- Selezione automatica del modello in base al ruolo
- Fallback chain: se il provider primario fallisce, usa il secondario
- Budget check prima di ogni chiamata
- Retry con backoff esponenziale
- Supporto Vision (base64 images) per Claude
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import httpx

from ai_client.budget import get_budget
from logging_system import get_logger, LogStatus, LogAction

log = get_logger("ai_client.client")


# ─── Model Role (quale modello usare per il task) ────────────────────────────

class ModelRole(str, Enum):
    FAST       = "fast"        # DeepSeek: classificazione, entità, riassunti interni (70%)
    RELIABLE   = "reliable"    # Claude Haiku: risposte customer-facing, fatti (20%)
    ANALYSE    = "analyse"     # Claude Sonnet: analisi complessa, report (8%)
    CHAT       = "chat"        # Claude Sonnet: chat supervisore, strategia (2%)
    VISION     = "vision"      # Claude Vision: OCR schermate RDP

    # Alias semantico: query che richiedono affidabilità fattuale → Haiku
    GROUND     = "reliable"    # = RELIABLE (usa KB + Haiku, mai DeepSeek)


# ─── Strutture dati ──────────────────────────────────────────────────────────

@dataclass
class AIMessage:
    role: str           # "user" | "assistant" | "system"
    content: str
    images: list[str] = field(default_factory=list)  # percorsi file immagine per Vision


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


# ─── Costanti provider / modelli ─────────────────────────────────────────────

_DEEPSEEK_BASE  = "https://api.deepseek.com"
_DEEPSEEK_MODEL = "deepseek-chat"

_CLAUDE_BASE    = "https://api.anthropic.com"
_CLAUDE_VERSION = "2023-06-01"

# Modelli Claude per tier di costo/qualità
# Haiku:  $0.80/MTok input,  $4/MTok output  → affidabile, economico
# Sonnet: $3.00/MTok input, $15/MTok output  → analisi complessa
_CLAUDE_HAIKU   = "claude-haiku-4-5"    # tier 1: affidabile, economico
_CLAUDE_SONNET  = "claude-sonnet-4-6"   # tier 2: analisi/chat avanzata

_MAX_RETRIES    = 3
_RETRY_BASE_S   = 2.0     # secondi base per backoff


# ─── AI Client ───────────────────────────────────────────────────────────────

class AIClient:
    """
    Interfaccia unificata. Seleziona il provider in base al ModelRole:
      FAST / VISION → DeepSeek per default, fallback Claude
      ANALYSE / CHAT → Claude per default, fallback DeepSeek
    """

    def __init__(
        self,
        deepseek_api_key: Optional[str] = None,
        claude_api_key:   Optional[str] = None,
        timeout_seconds:  int = 60,
    ) -> None:
        self._deepseek_key = deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self._claude_key   = claude_api_key   or os.getenv("ANTHROPIC_API_KEY", "")
        self._timeout      = timeout_seconds
        self._budget       = get_budget()
        self._http         = httpx.Client(timeout=timeout_seconds)

    # ── Public API ────────────────────────────────────────────────────────────

    def complete(
        self,
        messages: list[AIMessage],
        role: ModelRole = ModelRole.FAST,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> AIResponse:
        """
        Invia i messaggi al modello appropriato.
        In caso di errore o budget esaurito tenta il provider alternativo.
        """
        primary, fallback, claude_model = self._route(role)

        for provider in [primary, fallback]:
            if not provider:
                continue
            if not self._budget.can_spend(provider):
                log.warning(
                    f"Budget {provider} esaurito per oggi, skip.",
                    action=LogAction.MONITOR, status=LogStatus.WARNING,
                )
                continue
            try:
                response = self._call_with_retry(
                    provider, messages, system_prompt, max_tokens, temperature,
                    claude_model=claude_model,
                )
                self._budget.record_usage(
                    provider,
                    response.input_tokens,
                    response.output_tokens,
                    response.model,
                )
                return response
            except Exception as exc:
                log.warning(
                    f"Provider {provider} fallito: {exc} — tentativo con fallback",
                    action=LogAction.MONITOR, status=LogStatus.WARNING,
                )

        raise RuntimeError("Tutti i provider AI non disponibili o budget esaurito.")

    def complete_simple(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        role: ModelRole = ModelRole.FAST,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """Shortcut: messaggio singolo → testo risposta."""
        msgs = [AIMessage(role="user", content=user_prompt)]
        return self.complete(msgs, role, system_prompt, max_tokens, temperature).text

    def vision(
        self,
        image_path: Union[str, Path],
        prompt: str,
        max_tokens: int = 512,
    ) -> str:
        """OCR / analisi di uno screenshot via Claude Vision."""
        image_b64 = self._encode_image(image_path)
        msgs = [AIMessage(role="user", content=prompt, images=[image_path])]
        response = self._call_with_retry(
            "claude", msgs, None, max_tokens, 0.1, image_b64=image_b64
        )
        self._budget.record_usage("claude", response.input_tokens, response.output_tokens)
        return response.text

    # ── Routing ───────────────────────────────────────────────────────────────

    def _route(self, role: ModelRole) -> tuple[str, str, str]:
        """
        Ritorna (provider_primario, provider_fallback, modello_claude).

        Routing per costo/affidabilità:
          FAST     → DeepSeek (cheap) → fallback Claude Haiku
          RELIABLE → Claude Haiku     → fallback DeepSeek
          ANALYSE  → Claude Sonnet    → fallback DeepSeek
          CHAT     → Claude Sonnet    → fallback Claude Haiku
          VISION   → Claude Sonnet    (vision)
        """
        if role == ModelRole.FAST:
            return ("deepseek", "claude", _CLAUDE_HAIKU)
        if role == ModelRole.RELIABLE:       # alias GROUND
            return ("claude", "deepseek", _CLAUDE_HAIKU)
        if role in (ModelRole.ANALYSE, ModelRole.CHAT, ModelRole.VISION):
            return ("claude", "deepseek", _CLAUDE_SONNET)
        return ("claude", "deepseek", _CLAUDE_SONNET)

    # ── Retry wrapper ─────────────────────────────────────────────────────────

    def _call_with_retry(
        self,
        provider: str,
        messages: list[AIMessage],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        image_b64: Optional[str] = None,
        claude_model: str = _CLAUDE_SONNET,
    ) -> AIResponse:
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(_MAX_RETRIES):
            try:
                if provider == "deepseek":
                    return self._call_deepseek(messages, system_prompt, max_tokens, temperature)
                elif provider == "claude":
                    return self._call_claude(messages, system_prompt, max_tokens, temperature,
                                             image_b64, model=claude_model)
                else:
                    raise ValueError(f"Provider sconosciuto: {provider}")
            except httpx.TimeoutException as exc:
                last_exc = exc
                wait = _RETRY_BASE_S * (2 ** attempt)
                log.warning(f"Timeout {provider} (tentativo {attempt+1}/{_MAX_RETRIES}), attendo {wait:.1f}s")
                time.sleep(wait)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 502, 503, 504):
                    last_exc = exc
                    wait = _RETRY_BASE_S * (2 ** attempt)
                    time.sleep(wait)
                else:
                    raise
        raise last_exc

    # ── DeepSeek ──────────────────────────────────────────────────────────────

    def _call_deepseek(
        self,
        messages: list[AIMessage],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        if not self._deepseek_key:
            raise RuntimeError("DEEPSEEK_API_KEY non configurata")

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload_messages.append({"role": m.role, "content": m.content})

        t0 = time.monotonic()
        resp = self._http.post(
            f"{_DEEPSEEK_BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._deepseek_key}", "Content-Type": "application/json"},
            json={
                "model": _DEEPSEEK_MODEL,
                "messages": payload_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        latency_ms = (time.monotonic() - t0) * 1000

        data = resp.json()
        choice = data["choices"][0]["message"]["content"]
        usage  = data.get("usage", {})
        return AIResponse(
            text=choice,
            provider="deepseek",
            model=_DEEPSEEK_MODEL,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cost_usd=0.0,   # calcolato dopo da BudgetManager
            latency_ms=latency_ms,
        )

    # ── Claude (Anthropic) ───────────────────────────────────────────────────

    def _call_claude(
        self,
        messages: list[AIMessage],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        image_b64: Optional[str] = None,
        model: str = _CLAUDE_SONNET,
    ) -> AIResponse:
        if not self._claude_key:
            raise RuntimeError("ANTHROPIC_API_KEY non configurata")

        payload_messages = []
        for m in messages:
            if image_b64 and m.images:
                content = [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": m.content},
                ]
            else:
                content = m.content
            payload_messages.append({"role": m.role, "content": content})

        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": payload_messages,
        }
        if system_prompt:
            body["system"] = system_prompt

        t0 = time.monotonic()
        resp = self._http.post(
            f"{_CLAUDE_BASE}/v1/messages",
            headers={
                "x-api-key": self._claude_key,
                "anthropic-version": _CLAUDE_VERSION,
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        latency_ms = (time.monotonic() - t0) * 1000

        data  = resp.json()
        text  = data["content"][0]["text"]
        usage = data.get("usage", {})
        return AIResponse(
            text=text,
            provider="claude",
            model=_CLAUDE_MODEL,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _encode_image(path: Union[str, Path]) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("utf-8")

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ─── Singleton per uso globale ───────────────────────────────────────────────

_client: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    global _client
    if _client is None:
        _client = AIClient()
    return _client
