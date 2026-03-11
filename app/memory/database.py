"""
PostgreSQL async connection management via SQLAlchemy 2.x + asyncpg.
Replaces the Motor MongoDB connection.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str) -> None:
    """Create the async engine, session factory, and ensure tables exist."""
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Create tables if they don't exist
    from app.memory.models import Base

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("[DB] Connected to PostgreSQL")


async def close_db() -> None:
    """Dispose the engine on shutdown."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        logger.info("[DB] PostgreSQL connection closed")
    _engine = None
    _session_factory = None


def is_db_connected() -> bool:
    return _engine is not None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for repository use."""
    assert _session_factory is not None
    async with _session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    return _session_factory
