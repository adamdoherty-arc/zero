"""
LangGraph checkpointer factory.

Tries PostgreSQL for persistent crash recovery.
Falls back to MemorySaver (in-memory, lost on restart) if unavailable.

Configuration:
  Set ZERO_POSTGRES_URL in .env to enable PostgreSQL persistence.
  Example: ZERO_POSTGRES_URL=postgresql://zero:zero_dev@localhost:5433/zero
"""

import structlog

logger = structlog.get_logger(__name__)

_checkpointer = None


def get_checkpointer():
    """
    Get or create the LangGraph checkpointer.

    Returns PostgresSaver if ZERO_POSTGRES_URL is configured,
    otherwise MemorySaver.
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    from app.infrastructure.config import get_settings
    settings = get_settings()
    postgres_url = getattr(settings, "postgres_url", None)

    if postgres_url:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            _checkpointer = PostgresSaver.from_conn_string(postgres_url)
            logger.info("checkpointer_initialized", type="PostgresSaver")
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
