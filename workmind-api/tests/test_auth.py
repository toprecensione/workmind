"""Tests for authentication endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={
        "email": "nobody@test.com",
        "password": "anypass",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient):
    login = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "testpass123",
    })
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]
    resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_logout(client: AsyncClient):
    # Login first to obtain a refresh token
    login = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "testpass123",
    })
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    # Logout using the refresh token (no Authorization header required)
    resp = await client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    # logout returns 204 No Content
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_refresh_after_logout_fails(client: AsyncClient):
    """After logout the refresh token must be invalidated."""
    login = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "testpass123",
    })
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    await client.post("/api/auth/logout", json={"refresh_token": refresh_token})

    resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401
