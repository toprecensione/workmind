"""Tests for admin system endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_system_status_requires_auth(client: AsyncClient):
    # Without any token, in production mode this would return 401.
    # In development mode the fallback user has role "user", which triggers 403
    # from require_admin. Either 401 or 403 indicates the endpoint is protected.
    resp = await client.get("/api/admin/system/status")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_system_status_as_admin(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/admin/system/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "postgres" in data
    assert "redis" in data
    assert "ollama" in data


@pytest.mark.asyncio
async def test_system_metrics(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/admin/system/metrics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_pct" in data
    assert any(k in data for k in ("ram_pct", "ram_percent", "memory_pct"))


@pytest.mark.asyncio
async def test_system_overview(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/admin/system/overview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "active_users" in data
    assert any(k in data for k in ("documents", "documents_indexed", "documents_failed"))


@pytest.mark.asyncio
async def test_backup_list(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/admin/backup", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_audit_logs(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/admin/audit/logs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data or isinstance(data, list)
