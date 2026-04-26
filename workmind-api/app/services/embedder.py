"""
WorkMind — Embedder Service
Async wrapper around Ollama /api/embeddings endpoint (nomic-embed-text, 768 dims).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger("workmind.embedder")


class EmbedderError(RuntimeError):
    """Raised when Ollama is unreachable or returns an unexpected response."""


class Embedder:
    """
    Thin async client for Ollama embedding API.
    Uses a shared httpx.AsyncClient with a 30-second timeout.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            settings = get_settings()
            self._client = httpx.AsyncClient(
                base_url=settings.ollama_base_url,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def embed_text(self, text: str) -> list[float]:
        """
        Embed a single text string via Ollama.
        Returns a list[float] of length 768 (nomic-embed-text).
        Raises EmbedderError if Ollama is unavailable or returns an error.
        """
        settings = get_settings()
        client = self._get_client()
        payload: dict[str, Any] = {
            "model": settings.ollama_embed_model,
            "prompt": text,
        }
        try:
            response = await client.post("/api/embeddings", json=payload)
            response.raise_for_status()
            data = response.json()
            embedding: list[float] = data["embedding"]
            return embedding
        except httpx.HTTPStatusError as exc:
            log.error(
                "embedder_http_error",
                status_code=exc.response.status_code,
                body=exc.response.text[:200],
            )
            raise EmbedderError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            log.error("embedder_request_error", error=str(exc))
            raise EmbedderError(f"Ollama unreachable: {exc}") from exc
        except (KeyError, TypeError) as exc:
            log.error("embedder_parse_error", error=str(exc))
            raise EmbedderError(f"Unexpected Ollama response format: {exc}") from exc

    async def embed_batch(
        self, texts: list[str], rate_limit_delay: float = 0.05
    ) -> list[list[float]]:
        """
        Embed a list of texts sequentially with a small delay between calls
        to avoid overwhelming Ollama.
        Returns list of embeddings in the same order as input.
        """
        results: list[list[float]] = []
        for i, text in enumerate(texts):
            embedding = await self.embed_text(text)
            results.append(embedding)
            if i < len(texts) - 1:
                await asyncio.sleep(rate_limit_delay)
        return results

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level singleton
embedder = Embedder()
