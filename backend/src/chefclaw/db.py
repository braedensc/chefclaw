"""Async database engine, session dependency, and connectivity ping."""

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chefclaw.config import get_settings

PING_TIMEOUT_SECONDS = 2.0

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily create the process-wide async engine from settings."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Lazily create the process-wide async session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession."""
    async with get_sessionmaker()() as session:
        yield session


async def ping() -> bool:
    """Return True iff ``SELECT 1`` succeeds within a short timeout."""
    try:
        async with asyncio.timeout(PING_TIMEOUT_SECONDS):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
