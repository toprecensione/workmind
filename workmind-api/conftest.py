"""Test fixtures for WorkMind API."""
from __future__ import annotations

import hashlib
import os
import uuid
from typing import AsyncGenerator

# ── Set env vars BEFORE importing any app modules ─────────────────────────────
# This satisfies pydantic-settings required fields (DATABASE_URL, REDIS_URL).
# The actual test DB is workmind_test; production DB is never touched.
_TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://workmind:Wm2026Bender!Pg@localhost:5432/workmind_test",
)
os.environ.setdefault("DATABASE_URL", _TEST_DB_URL)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # DB 15 = test slot
os.environ.setdefault("WORKMIND_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("WORKMIND_ENV", "development")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import create_app
from app.db.engine import get_db_session
from app.db.models import Base, Organization, User


TEST_DB_URL = _TEST_DB_URL


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    # NullPool: each session gets a brand-new connection — avoids asyncpg reuse errors.
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    # Create all tables in the test DB (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seed_base_orgs(test_session_factory, test_engine):
    """Ensure base orgs (test + medic) exist. autouse=True so all tests get them."""
    async with test_session_factory() as session:
        for org_data in [
            dict(id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                 slug="test-org", name="Test Organization", sector="test"),
            dict(id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                 slug="medic-org", name="MEDIC Organization", sector="medic"),
        ]:
            existing = await session.get(Organization, org_data["id"])
            if not existing:
                session.add(Organization(**org_data, is_active=True))
        await session.commit()


@pytest_asyncio.fixture(scope="session")
async def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)



@pytest_asyncio.fixture(scope="session")
async def test_org(test_session_factory) -> Organization:
    from sqlalchemy import select
    async with test_session_factory() as session:
        # Upsert: reuse if already exists (re-runs, parallel CI)
        existing = await session.get(Organization, uuid.UUID("00000000-0000-0000-0000-000000000001"))
        if existing:
            return existing
        org = Organization(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            slug="test-org",
            name="Test Organization",
            sector="test",
            is_active=True,
        )
        session.add(org)
        await session.commit()
        await session.refresh(org)
        return org


@pytest_asyncio.fixture(scope="session")
async def test_admin_user(test_session_factory, test_org) -> User:
    import bcrypt as _bcrypt
    async with test_session_factory() as session:
        existing = await session.get(User, uuid.UUID("00000000-0000-0000-0000-000000000010"))
        if existing:
            return existing
        user = User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            org_id=test_org.id,
            email="admin@test.com",
            email_hash=_email_hash("admin@test.com"),
            display_name="Test Admin",
            role="admin",
            password_hash=_bcrypt.hashpw(b"testpass123", _bcrypt.gensalt()).decode(),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture(scope="session")
async def medic_org(test_session_factory) -> Organization:
    """Org for MEDIC tests (UUID ...000002)."""
    async with test_session_factory() as session:
        existing = await session.get(Organization, uuid.UUID("00000000-0000-0000-0000-000000000002"))
        if existing:
            return existing
        org = Organization(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            slug="medic-org",
            name="MEDIC Organization",
            sector="medic",
            is_active=True,
        )
        session.add(org)
        await session.commit()
        await session.refresh(org)
        return org


@pytest_asyncio.fixture(scope="session")
async def medic_admin_user(test_session_factory, medic_org) -> User:
    """Admin user for MEDIC org."""
    import bcrypt as _bcrypt
    async with test_session_factory() as session:
        existing = await session.get(User, uuid.UUID("00000000-0000-0000-0000-000000000020"))
        if existing:
            return existing
        user = User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            org_id=medic_org.id,
            email="medic@test.com",
            email_hash=_email_hash("medic@test.com"),
            display_name="MEDIC Admin",
            role="admin",
            password_hash=_bcrypt.hashpw(b"testpass123", _bcrypt.gensalt()).decode(),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def client(test_session_factory) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client. Each request gets its own DB session (avoids asyncpg concurrency errors)."""
    app = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(client, test_admin_user) -> dict:
    """Get auth headers for admin user."""
    resp = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
