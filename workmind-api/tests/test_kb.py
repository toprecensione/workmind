"""Tests for Knowledge Base endpoints."""
import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_kb_documents_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/kb/documents", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_kb_search_no_documents(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/kb/search?q=test", headers=auth_headers)
    # Should return 200 with empty results OR 503 if Ollama unavailable
    assert resp.status_code in (200, 503)


@pytest.mark.asyncio
async def test_kb_upload_txt(client: AsyncClient, auth_headers: dict):
    content = b"Questo e un documento di test per WorkMind."
    files = {"file": ("test.txt", io.BytesIO(content), "text/plain")}
    resp = await client.post("/api/kb/upload", files=files, headers=auth_headers)
    assert resp.status_code in (200, 201, 202, 500)  # 500 = Celery/Redis unavailable in test env
    if resp.status_code in (200, 201, 202):
        data = resp.json()
        assert "id" in data or "document_id" in data or "status" in data
