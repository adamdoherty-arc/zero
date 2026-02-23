"""
Database infrastructure for ZERO API.

Async SQLAlchemy engine and session management backed by PostgreSQL.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sqlalchemy
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
import structlog

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# Module-level engine and session factory (initialized on startup)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_async_url(url: str) -> str:
    """Convert a sync PostgreSQL URL to async (psycopg driver)."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url
    raise ValueError(f"Unsupported database URL scheme: {url}")


async def init_database(postgres_url: str) -> None:
    """Initialize the async engine and session factory."""
    global _engine, _session_factory

    async_url = _make_async_url(postgres_url)

    _engine = create_async_engine(
        async_url,
        pool_size=10,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=3600,
        echo=False,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("database_initialized", url=postgres_url.split("@")[-1])


async def close_database() -> None:
    """Dispose the engine and release connections."""
    global _engine, _session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("database_closed")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory. Raises if database not initialized."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _session_factory


def get_engine() -> AsyncEngine:
    """Get the async engine. Raises if database not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _engine


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async session scope."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables defined in models (for development/testing)."""
    engine = get_engine()
    async with engine.begin() as conn:
        # Enable pgvector extension for semantic search embeddings
        await conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_tables_created")
