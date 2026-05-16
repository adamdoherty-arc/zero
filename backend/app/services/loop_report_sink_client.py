"""Loop report sink client — pushes runs to Legion's mirror with replay buffer.

Why this exists: Legion is the durable system of record per the master plan,
but Legion is operationally fragile ("always goes down"). Zero must keep
loops running even when Legion is down. So:

1. Every successful run pushes to POST {legion}/api/loops/runs.
2. On failure (timeout / 5xx / connection refused), append the envelope to
   data/loop_replay_buffer.jsonl on disk.
3. The `loop_health_5min` scheduler job replays the buffer in batches when
   the circuit breaker indicates Legion is back.
4. Legion's endpoint is idempotent on `zero_run_id` (UNIQUE), so replay is
   safe regardless of how many partial successes happened during the outage.

The sink is also rate-limited (10 req/sec) so we don't hammer Legion's
RATE_LIMIT_RPM=200 backstop during a flush burst.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from app.infrastructure.circuit_breaker import CircuitBreaker, CircuitBreakerError

logger = structlog.get_logger(__name__)


_DEFAULT_LEGION_BASE = "http://host.docker.internal:8005"
_DEFAULT_BUFFER_PATH = "/app/app/data/loop_replay_buffer.jsonl"
_DEFAULT_RATE_LIMIT_PER_S = 10.0
_DEFAULT_TIMEOUT_S = 8.0


class LoopReportSinkClient:
    """Push loop runs to Legion. Buffer + replay on failure."""

    def __init__(
        self,
        *,
        legion_base: Optional[str] = None,
        buffer_path: Optional[str] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        rate_limit_per_s: float = _DEFAULT_RATE_LIMIT_PER_S,
    ) -> None:
        self._base = (legion_base or os.environ.get("ZERO_LEGION_BASE_URL") or _DEFAULT_LEGION_BASE).rstrip("/")
        self._buffer_path = Path(buffer_path or os.environ.get("ZERO_LOOP_REPLAY_BUFFER") or _DEFAULT_BUFFER_PATH)
        self._timeout_s = timeout_s
        self._min_interval_s = 1.0 / max(0.1, rate_limit_per_s)
        self._last_send_t = 0.0
        self._send_lock = asyncio.Lock()
        self._breaker = CircuitBreaker(
            name="legion-loop-sink",
            failure_threshold=3,
            recovery_timeout=60.0,
            half_open_max_calls=1,
        )

    def _headers(self) -> dict[str, str]:
        """Headers for the Legion sink callback."""
        token = (
            os.environ.get("ZERO_LEGION_SINK_TOKEN")
            or os.environ.get("ZERO_GATEWAY_TOKEN")
            or ""
        ).strip()
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def push(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Push one run envelope. On failure, buffer and return {status: 'buffered'}."""
        try:
            return await self._breaker.call(self._send, envelope)
        except (CircuitBreakerError, httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning(
                "loop_sink.push_failed",
                zero_run_id=envelope.get("zero_run_id"),
                error=str(exc),
            )
            self._buffer_envelope(envelope)
            return {"status": "buffered", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "loop_sink.push_unexpected",
                zero_run_id=envelope.get("zero_run_id"),
                error=str(exc),
            )
            self._buffer_envelope(envelope)
            return {"status": "buffered", "error": str(exc)}

    async def replay_buffer(self, *, max_batch: int = 50) -> dict[str, Any]:
        """Flush buffered envelopes one by one. Called by loop_health_5min job."""
        if not self._buffer_path.exists():
            return {"replayed": 0, "remaining": 0}

        envelopes: list[dict[str, Any]] = []
        try:
            with self._buffer_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        envelopes.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("loop_sink.replay_skip_invalid_line")
        except OSError as exc:
            logger.warning("loop_sink.replay_buffer_unreadable", error=str(exc))
            return {"replayed": 0, "remaining": 0, "error": str(exc)}

        if not envelopes:
            self._truncate_buffer()
            return {"replayed": 0, "remaining": 0}

        batch = envelopes[:max_batch]
        remaining = envelopes[max_batch:]
        replayed = 0
        failed: list[dict[str, Any]] = []
        # Replay bypasses the circuit breaker. The breaker exists to avoid
        # hammering Legion during a live outage from the hot path; replay is
        # already deferred work and we want it to drain as soon as Legion is
        # reachable, not wait for breaker recovery_timeout. Failures here
        # naturally re-buffer.
        for env in batch:
            try:
                result = await self._send(env)
                if result.get("status") == "ok":
                    replayed += 1
                else:
                    failed.append(env)
            except Exception:  # noqa: BLE001
                failed.append(env)

        # Rewrite buffer with anything we couldn't send (failed batch + leftover)
        self._rewrite_buffer(failed + remaining)
        logger.info(
            "loop_sink.replay_completed",
            replayed=replayed,
            failed=len(failed),
            remaining=len(remaining),
        )
        return {"replayed": replayed, "remaining": len(failed) + len(remaining)}

    @property
    def breaker_state(self) -> str:
        return self._breaker.state.value

    async def check_legion_health(self) -> dict[str, Any]:
        """Probe Legion's deep /health endpoint. Returns {ok, status_code, latency_ms}.

        Used by the loop_health_5min job to feed the PromptEvaluatorAgent
        tripwire: 3 consecutive failures -> we'd flip ENABLE_PROMPT_EVALUATOR=false.
        We can't actually edit Legion env at runtime from here, but we DO post
        a vault alert so the operator (you) knows the evaluator is now noisy
        on a system that's struggling.
        """
        url = f"{self._base}/health"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url)
                return {
                    "ok": resp.status_code < 500,
                    "status_code": resp.status_code,
                }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def buffer_count(self) -> int:
        if not self._buffer_path.exists():
            return 0
        try:
            with self._buffer_path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _send(self, envelope: dict[str, Any]) -> dict[str, Any]:
        async with self._send_lock:
            elapsed = time.monotonic() - self._last_send_t
            if elapsed < self._min_interval_s:
                await asyncio.sleep(self._min_interval_s - elapsed)
            self._last_send_t = time.monotonic()

        url = f"{self._base}/api/loops/runs"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s)) as client:
            resp = await client.post(url, json=envelope, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        return {
            "status": "ok",
            "legion_run_id": data.get("id"),
            "deduped": bool(data.get("deduped")),
        }

    def _buffer_envelope(self, envelope: dict[str, Any]) -> None:
        try:
            self._buffer_path.parent.mkdir(parents=True, exist_ok=True)
            with self._buffer_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(envelope, default=str) + "\n")
        except OSError as exc:
            logger.error("loop_sink.buffer_write_failed", error=str(exc))

    def _rewrite_buffer(self, envelopes: list[dict[str, Any]]) -> None:
        try:
            self._buffer_path.parent.mkdir(parents=True, exist_ok=True)
            with self._buffer_path.open("w", encoding="utf-8") as fh:
                for env in envelopes:
                    fh.write(json.dumps(env, default=str) + "\n")
        except OSError as exc:
            logger.error("loop_sink.buffer_rewrite_failed", error=str(exc))

    def _truncate_buffer(self) -> None:
        try:
            if self._buffer_path.exists():
                self._buffer_path.unlink()
        except OSError:
            pass


@lru_cache(maxsize=1)
def get_loop_sink() -> LoopReportSinkClient:
    return LoopReportSinkClient()
