"""
LangGraph checkpointer factory.

Tries PostgreSQL (async) for persistent crash recovery.
Falls back to MemorySaver (in-memory, lost on restart) if unavailable.

Configuration:
  Set ZERO_POSTGRES_URL in .env to enable PostgreSQL persistence.
  Example: ZERO_POSTGRES_URL=postgresql://zero:zero_dev@localhost:5433/zero
"""

import structlog

logger = structlog.get_logger(__name__)

_checkpointer = None
_pg_pool = None


async def get_checkpointer():
    """
    Get or create the LangGraph checkpointer (async).

    Returns AsyncPostgresSaver with a connection pool if ZERO_POSTGRES_URL
    is configured, otherwise MemorySaver.
    """
    global _checkpointer, _pg_pool
    if _checkpointer is not None:
        return _checkpointer

    from app.infrastructure.config import get_settings
    settings = get_settings()
    postgres_url = getattr(settings, "postgres_url", None)

    if postgres_url:
        try:
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            _pg_pool = AsyncConnectionPool(
                conninfo=postgres_url,
                min_size=1,
                max_size=3,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            await _pg_pool.open()
            _checkpointer = AsyncPostgresSaver(_pg_pool)
            await _checkpointer.setup()
            logger.info("checkpointer_initialized", type="AsyncPostgresSaver")
            return _checkpointer
        except ImportError:
            logger.warning("checkpointer_postgres_not_installed", fallback="MemorySaver")
        except Exception as e:
            logger.warning("checkpointer_postgres_failed", error=str(e), fallback="MemorySaver")

    # Fallback to in-memory
    try:
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()
        logger.info("checkpointer_initialized", type="MemorySaver")
    except ImportError:
        logger.warning("checkpointer_none_available")

    return _checkpointer
