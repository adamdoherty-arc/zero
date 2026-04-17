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

        # Safe column additions for existing tables (idempotent)
        safe_columns = [
            ("content_queue", "publish_status", "VARCHAR(20)"),
            ("content_queue", "publish_platform", "VARCHAR(30)"),
            ("content_queue", "publish_url", "TEXT"),
            ("content_queue", "published_at", "TIMESTAMPTZ"),
            ("content_queue", "publish_error", "TEXT"),
            ("content_queue", "caption", "TEXT"),
            ("content_queue", "hashtags", "JSONB"),
            # Sprint 1: affiliate links, import tracking
            ("tiktok_products", "affiliate_link", "TEXT"),
            ("tiktok_products", "tiktok_shop_url", "TEXT"),
            ("tiktok_products", "import_url", "TEXT"),
            ("tiktok_products", "import_source", "VARCHAR(30)"),
            # Sprint 1: reference video link on video_scripts
            ("video_scripts", "reference_video_id", "VARCHAR(64)"),
            # Sprint 2: content performance feedback
            ("tiktok_products", "content_performance_score", "FLOAT"),
            ("tiktok_products", "best_template_type", "VARCHAR(30)"),
            ("tiktok_products", "last_performance_update_at", "TIMESTAMPTZ"),
            # Sprint 6: soft delete + auto-retry
            ("tiktok_products", "archived_at", "TIMESTAMPTZ"),
            ("content_queue", "retry_count", "INTEGER DEFAULT 0"),
            # Phase 024: Character Autopilot
            ("characters", "autonomous_disabled", "BOOLEAN DEFAULT FALSE"),
            ("characters", "priority_tier", "VARCHAR(20) DEFAULT 'standard'"),
            ("characters", "discovery_source", "VARCHAR(50)"),
            ("characters", "discovery_evidence", "JSONB DEFAULT '{}'::jsonb"),
            ("characters", "discovery_hits", "INTEGER DEFAULT 0"),
            ("character_carousels", "auto_approved", "BOOLEAN"),
            ("character_carousels", "auto_approved_at", "TIMESTAMPTZ"),
            ("character_carousels", "auto_approve_reason", "TEXT"),
            # Phase 029: Research queue persistence
            ("characters", "research_completed_steps", "JSONB DEFAULT '[]'::jsonb"),
            # Content variety: hook style + content format
            ("character_carousels", "hook_style", "VARCHAR(50)"),
            ("character_carousels", "content_format", "VARCHAR(50)"),
            # Phase 028: TV & Movie content support
            ("character_carousels", "content_type", "VARCHAR(20) DEFAULT 'character'"),
            ("character_carousels", "media_title_id", "VARCHAR(64)"),
        ]

        # Phase 028: Make character_id nullable for media-only carousels
        try:
            await conn.execute(sqlalchemy.text(
                "ALTER TABLE character_carousels ALTER COLUMN character_id DROP NOT NULL"
            ))
        except Exception:
            pass  # Already nullable or doesn't exist
        for table, col, col_type in safe_columns:
            try:
                await conn.execute(sqlalchemy.text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
            except Exception:
                pass  # Column already exists or table doesn't exist yet

        # Composite indexes for common query patterns (idempotent)
        safe_indexes = [
            ("idx_tiktok_products_status_score", "tiktok_products", "(status, opportunity_score DESC)"),
            ("idx_tiktok_products_status_discovered", "tiktok_products", "(status, discovered_at DESC)"),
            ("idx_video_scripts_product_status", "video_scripts", "(product_id, status)"),
            ("idx_content_queue_product_status", "content_queue", "(product_id, status)"),
            ("idx_content_queue_publish_status", "content_queue", "(publish_status, created_at DESC)"),
            ("idx_reference_videos_product_status", "reference_videos", "(product_id, status)"),
        ]
        for idx_name, table, cols in safe_indexes:
            try:
                await conn.execute(sqlalchemy.text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} {cols}"
                ))
            except Exception:
                pass  # Index already exists or table doesn't exist yet

    logger.info("database_tables_created")
