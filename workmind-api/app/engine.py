"""
WorkMind API — Async SQLAlchemy Engine
Connection pool management with proper startup/shutdown lifecycle.
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

log = structlog.get_logger("workmind.db")

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


async def init_db_engine(settings: Settings) -> None:
    """Initialize the async SQLAlchemy engine and session factory."""
    global _engine, _session_factory

    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_pre_ping=True,   # verify connection health before checkout
        echo=not settings.is_production,   # SQL logging in dev only
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    log.info(
        "db_engine_initialized",
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


async def close_db_engine() -> None:
    """Dispose the engine and close all connections."""
    global _engine
    if _engine:
        await _engine.dispose()
        log.info("db_engine_closed")
        _engine = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the raw session factory (for use outside FastAPI dependencies)."""
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_db_engine() first.")
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session.
    Commits on success, rolls back on exception.

    Usage:
        db: AsyncSession = Depends(get_db_session)
    """
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_db_engine() first.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
