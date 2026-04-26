"""
Tests for chat endpoints.
Covers: /api/chat (non-streaming), /api/chat/stream (SSE), conversation management.
Uses mock AI providers to avoid real API calls.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.model_router import AIResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_AI_RESPONSE = AIResponse(
    text="Risposta di test dall'assistente AI.",
    provider="claude",
    model="claude-haiku-4-5",
    input_tokens=50,
    output_tokens=20,
    cost_usd=0.0001,
    latency_ms=250.0,
    metadata={},
)


async def _mock_complete(*args, **kwargs) -> AIResponse:
    return MOCK_AI_RESPONSE


async def _mock_complete_stream(*args, **kwargs):
    """Async generator that yields chunks."""
    chunks = ["Risposta ", "di test ", "dall'assistente ", "AI."]
    for chunk in chunks:
        yield chunk


# ── Chat (non-streaming) ──────────────────────────────────────────────────────

class TestChat:
    @pytest.mark.asyncio
    async def test_chat_basic(self, client, auth_headers):
        with patch("app.api.routes.chat.ModelRouter.complete", new=_mock_complete):
            resp = await client.post(
                "/api/chat",
                json={"message": "Ciao, come stai?"},
                headers=auth_headers,
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "conversation_id" in data
        assert "reply" in data
        assert "provider" in data
        assert "tokens" in data

    @pytest.mark.asyncio
    async def test_chat_empty_message(self, client, auth_headers):
        resp = await client.post(
            "/api/chat",
            json={"message": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_message_too_long(self, client, auth_headers):
        resp = await client.post(
            "/api/chat",
            json={"message": "a" * 5000},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_requires_auth(self, client):
        resp = await client.post(
            "/api/chat",
            json={"message": "Ciao"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_with_existing_conversation(self, client, auth_headers):
        with patch("app.api.routes.chat.ModelRouter.complete", new=_mock_complete):
            # First message — creates conversation
            resp1 = await client.post(
                "/api/chat",
                json={"message": "Prima domanda"},
                headers=auth_headers,
            )
            assert resp1.status_code == 200
            conv_id = resp1.json()["conversation_id"]

            # Second message — continues conversation
            resp2 = await client.post(
                "/api/chat",
                json={"message": "Seconda domanda", "conversation_id": conv_id},
                headers=auth_headers,
            )
            assert resp2.status_code == 200
            assert resp2.json()["conversation_id"] == conv_id

    @pytest.mark.asyncio
    async def test_chat_invalid_conversation_id(self, client, auth_headers):
        import uuid
        with patch("app.api.routes.chat.ModelRouter.complete", new=_mock_complete):
            resp = await client.post(
                "/api/chat",
                json={"message": "Test", "conversation_id": str(uuid.uuid4())},
                headers=auth_headers,
            )
        assert resp.status_code == 404


# ── Chat streaming ────────────────────────────────────────────────────────────

class TestChatStream:
    @pytest.mark.asyncio
    async def test_stream_returns_event_stream(self, client, auth_headers):
        with patch(
            "app.services.model_router.ModelRouter.complete_stream",
            new=lambda *a, **kw: _mock_complete_stream(*a, **kw),
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={"message": "Ciao streaming"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_stream_contains_chunks(self, client, auth_headers):
        with patch(
            "app.services.model_router.ModelRouter.complete_stream",
            new=lambda *a, **kw: _mock_complete_stream(*a, **kw),
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={"message": "Streaming test"},
                headers=auth_headers,
            )

        body = resp.text
        assert "data:" in body
        # Should contain chunk events
        assert '"type": "chunk"' in body or '"type":"chunk"' in body

    @pytest.mark.asyncio
    async def test_stream_ends_with_done(self, client, auth_headers):
        with patch(
            "app.services.model_router.ModelRouter.complete_stream",
            new=lambda *a, **kw: _mock_complete_stream(*a, **kw),
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={"message": "Fine streaming"},
                headers=auth_headers,
            )

        body = resp.text
        assert '"type": "done"' in body or '"type":"done"' in body

    @pytest.mark.asyncio
    async def test_stream_done_has_conversation_id(self, client, auth_headers):
        import json
        with patch(
            "app.services.model_router.ModelRouter.complete_stream",
            new=lambda *a, **kw: _mock_complete_stream(*a, **kw),
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={"message": "Conv ID test"},
                headers=auth_headers,
            )

        # Parse SSE events
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass

        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) >= 1
        assert "conversation_id" in done_events[0]

    @pytest.mark.asyncio
    async def test_stream_requires_auth(self, client):
        resp = await client.post(
            "/api/chat/stream",
            json={"message": "No auth"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_stream_has_no_cache_headers(self, client, auth_headers):
        with patch(
            "app.services.model_router.ModelRouter.complete_stream",
            new=lambda *a, **kw: _mock_complete_stream(*a, **kw),
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={"message": "Headers test"},
                headers=auth_headers,
            )
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"


# ── Conversations ─────────────────────────────────────────────────────────────

class TestConversations:
    @pytest.mark.asyncio
    async def test_list_conversations(self, client, auth_headers):
        resp = await client.get("/api/conversations", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_create_and_get_conversation(self, client, auth_headers):
        with patch("app.api.routes.chat.ModelRouter.complete", new=_mock_complete):
            chat_resp = await client.post(
                "/api/chat",
                json={"message": "Messaggio di test per conversazione"},
                headers=auth_headers,
            )
        assert chat_resp.status_code == 200
        conv_id = chat_resp.json()["conversation_id"]

        # Get conversation
        resp = await client.get(f"/api/conversations/{conv_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data or "id" in data

    @pytest.mark.asyncio
    async def test_delete_conversation(self, client, auth_headers):
        with patch("app.api.routes.chat.ModelRouter.complete", new=_mock_complete):
            chat_resp = await client.post(
                "/api/chat",
                json={"message": "Delete me conversation"},
                headers=auth_headers,
            )
        conv_id = chat_resp.json()["conversation_id"]

        del_resp = await client.delete(f"/api/conversations/{conv_id}", headers=auth_headers)
        assert del_resp.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_conversations_require_auth(self, client):
        resp = await client.get("/api/conversations")
        assert resp.status_code == 401
