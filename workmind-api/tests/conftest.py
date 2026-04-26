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
# Force-assign (not setdefault) — root conftest.py sets "development" first via setdefault,
# so setdefault here would be a no-op. Direct assign ensures tests always run in production mode.
os.environ["WORKMIND_ENV"] = "production"

import sqlalchemy
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import create_app
from app.db.engine import get_db_session
from app.db.models import Base, Organization, User
from app.config import invalidate_settings_cache

# Force cache clear so the test Settings (WORKMIND_ENV=production) takes effect
invalidate_settings_cache()


TEST_DB_URL = _TEST_DB_URL


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    # NullPool: each session gets a brand-new connection — avoids asyncpg reuse errors.
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    # Create all tables in the test DB (idempotent)
    async with engine.begin() as conn:
        # Extensions required before table creation
        await conn.execute(sqlalchemy.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(sqlalchemy.text('CREATE EXTENSION IF NOT EXISTS "vector"'))
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent schema patches — add columns that may be missing in older test DBs
        for stmt in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        ]:
            await conn.execute(sqlalchemy.text(stmt))
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
    # Ensure fresh Settings with WORKMIND_ENV=production for every test (prevents session-level
    # lru_cache contamination in pytest-asyncio AUTO+session-loop-scope mode).
    invalidate_settings_cache()
    app = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session")
def auth_headers(test_admin_user) -> dict:
    """JWT auth headers for admin user.
    Generated directly (no HTTP call) to avoid hitting slowapi rate limits on /api/auth/login.
    """
    from datetime import datetime, timezone, timedelta
    from jose import jwt as _jwt
    secret = os.environ.get("WORKMIND_SECRET_KEY", "test-secret-key-not-for-production")
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(test_admin_user.id),
        "org_id": str(test_admin_user.org_id),
        "role": test_admin_user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=1440),
    }
    token = _jwt.encode(payload, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}
