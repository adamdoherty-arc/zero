"""Langfuse client wrapper — LLM trace capture, prompt registry, judge scores.

Self-hosted Langfuse instance runs in docker-compose.sprint.yml (zero-langfuse-web
+ zero-langfuse-clickhouse, sharing zero-temporal-postgres for relational
metadata). The carosel.txt blueprint Phase 1 mandates "trace everything to
Langfuse from day one" so every LLM call writes a generation span here, with
prompt name + version pulled from ``PromptVersionModel.id``.

Design:

- **Optional dependency.** When ``ZERO_LANGFUSE_PUBLIC_KEY`` is unset the
  module returns a no-op tracer so existing services don't crash on first
  import. The first time a user creates a Langfuse account in the local
  instance they get the keys and stick them in the env.
- **Async-safe.** ``Langfuse.trace()`` and ``generation()`` are sync but
  thread-safe; we wrap them in an async context manager to fit the call site.
- **Cheap on the hot path.** A single ``Langfuse`` client per process,
  lazily constructed.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, AsyncIterator, Optional

import structlog

logger = structlog.get_logger(__name__)


class _NoopGeneration:
    """Stand-in returned when Langfuse is not configured.

    Mirrors the subset of ``langfuse.client.StatefulGenerationClient`` we
    actually call so the trace-site code stays the same regardless of whether
    Langfuse is wired.
    """

    def update(self, **_: Any) -> None:
        return None

    def end(self, **_: Any) -> None:
        return None


class _NoopTracer:
    """Returned by ``get_langfuse_tracer()`` when keys are unset."""

    enabled = False

    @asynccontextmanager
    async def trace_generation(
        self,
        *,
        name: str,
        model: Optional[str] = None,
        prompt_version_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        input_messages: Optional[list[dict[str, Any]]] = None,
    ) -> AsyncIterator[_NoopGeneration]:
        yield _NoopGeneration()

    def flush(self) -> None:
        return None


class LangfuseTracer:
    """Production tracer backed by the Langfuse SDK.

    Lazily imports the SDK so missing-package environments don't crash
    on import.
    """

    enabled = True

    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        from langfuse import Langfuse  # local import — optional dep

        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            timeout=10,
        )
        self._host = host
        logger.info("langfuse_client_initialized", host=host)

    @asynccontextmanager
    async def trace_generation(
        self,
        *,
        name: str,
        model: Optional[str] = None,
        prompt_version_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        input_messages: Optional[list[dict[str, Any]]] = None,
    ) -> AsyncIterator[Any]:
        """Async context manager wrapping a Langfuse generation span.

        On enter: opens a generation. The yielded object's ``.update(output=...)``
        captures the completion text and ``.end()`` marks the span complete.
        On exit: span ends with the elapsed wall-clock time and any exception
        recorded as ``level=ERROR``.
        """
        meta = dict(metadata or {})
        if prompt_version_id:
            meta["prompt_version_id"] = prompt_version_id

        try:
            generation = self._client.generation(
                name=name,
                model=model,
                input=input_messages,
                metadata=meta,
                start_time=_utcnow(),
            )
        except Exception as exc:  # noqa: BLE001 — never let tracing crash the call
            logger.warning("langfuse_generation_open_failed", error=str(exc))
            yield _NoopGeneration()
            return

        t0 = time.monotonic()
        try:
            yield generation
        except Exception as exc:
            try:
                generation.update(level="ERROR", status_message=str(exc)[:500])
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            try:
                generation.end(end_time=_utcnow())
            except Exception:  # noqa: BLE001
                pass
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.debug("langfuse_generation_closed", name=name, elapsed_ms=elapsed_ms)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001
            pass


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_langfuse_tracer() -> LangfuseTracer | _NoopTracer:
    """Singleton tracer. Returns the no-op variant when keys are unset.

    The cache is process-wide; to force a re-read after rotating keys, call
    ``get_langfuse_tracer.cache_clear()``.
    """
    public_key = os.getenv("ZERO_LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("ZERO_LANGFUSE_SECRET_KEY", "").strip()
    host = os.getenv("ZERO_LANGFUSE_HOST", "http://zero-langfuse-web:3000").strip()

    if not (public_key and secret_key):
        logger.info("langfuse_disabled_no_keys")
        return _NoopTracer()

    try:
        return LangfuseTracer(public_key, secret_key, host)
    except ImportError:
        logger.warning("langfuse_sdk_not_installed")
        return _NoopTracer()
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse_init_failed", error=str(exc))
        return _NoopTracer()
