"""
Docker readiness state machine for host_agent.

The Reachy stack on the Windows host depends on the Dockerized zero-api
(``host.docker.internal:18792``) for backend features the daemon supervisor
and UI consult after boot — vault queries, intent routing, briefings, etc.
Docker Desktop's WSL2 daemon takes 60-180 s to come up after a Windows cold
boot, while host_agent + the ``ZeroHostAgent`` scheduled task fire within
seconds of user logon. Without a readiness gate the watchdog logs probe
failures, the UI flashes red, and the daemon gets needlessly restarted.

This module owns a single in-process readiness state. ``probe_loop`` polls
``zero-api`` ``/health`` indefinitely with exponential backoff, never
blocking host_agent's own startup. Other modules read the state via
``get_status()`` and can request an out-of-band probe via ``probe_now()``
when the user clicks Smart Re-link in the UI.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import httpx
import structlog

logger = structlog.get_logger()


State = Literal["unknown", "waiting", "ready", "unreachable"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _ReadinessState:
    state: State = "unknown"
    last_check: datetime | None = None
    last_ready: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    consecutive_ready: int = 0
    probe_count: int = 0
    next_probe_in_s: float = 0.0
    backend_url: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_ready": self.last_ready.isoformat() if self.last_ready else None,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_ready": self.consecutive_ready,
            "probe_count": self.probe_count,
            "next_probe_in_s": self.next_probe_in_s,
            "backend_url": self.backend_url,
        }


class DockerReadiness:
    """Background poller that tracks whether the Dockerized backend is reachable."""

    INITIAL_DELAY_S = 2.0
    MAX_DELAY_S = 60.0
    BACKOFF_FACTOR = 1.7
    # 5 s gives Windows DNS time to fall through to IPv4 if it tries ::1
    # first. The earlier 3 s caused intermittent waiting->ready flapping on
    # an otherwise healthy zero-api.
    PROBE_TIMEOUT_S = 5.0
    UNREACHABLE_AFTER_FAILURES = 30
    READY_AFTER_SUCCESSES = 1
    # Once we've been ready, require this many consecutive failures before
    # flipping back to "waiting". Stops a single transient timeout from
    # turning the UI amber.
    FAILURES_BEFORE_LEAVING_READY = 2

    def __init__(self, backend_url: str, health_path: str = "/health") -> None:
        # Force IPv4. Windows commonly resolves "localhost" to ::1 first and
        # falls through to 127.0.0.1, which can blow past short timeouts on
        # fresh boots. The Dockerized zero-api binds 0.0.0.0:18792 so 127.0.0.1
        # always reaches it.
        normalized = backend_url.rstrip("/").replace("//localhost:", "//127.0.0.1:")
        self._backend_url = normalized
        self._health_url = f"{self._backend_url}{health_path}"
        self._state = _ReadinessState(backend_url=self._backend_url)
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def get_status(self) -> dict:
        return self._state.to_dict()

    @property
    def is_ready(self) -> bool:
        return self._state.state == "ready"

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._probe_loop(), name="docker_readiness_probe"
        )

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._task = None

    async def probe_now(self) -> dict:
        """Trigger an out-of-band probe and return the resulting state.

        Used by the Smart Re-link button so the UI gets a fresh answer
        instead of waiting for the next backoff window.
        """
        await self._probe_once()
        # Wake the loop so it recomputes its next backoff window.
        self._wake.set()
        return self.get_status()

    async def _probe_once(self) -> bool:
        async with self._lock:
            self._state.probe_count += 1
            self._state.last_check = _utcnow()
            try:
                async with httpx.AsyncClient(timeout=self.PROBE_TIMEOUT_S) as client:
                    resp = await client.get(self._health_url)
                ok = 200 <= resp.status_code < 500
                if ok:
                    self._state.consecutive_failures = 0
                    self._state.consecutive_ready += 1
                    self._state.last_error = None
                    if self._state.consecutive_ready >= self.READY_AFTER_SUCCESSES:
                        if self._state.state != "ready":
                            logger.info(
                                "docker_readiness_ready",
                                url=self._health_url,
                                probe_count=self._state.probe_count,
                            )
                        self._state.state = "ready"
                        self._state.last_ready = self._state.last_check
                    return True
                # Non-2xx but reachable still means Docker is up enough.
                self._state.consecutive_failures = 0
                self._state.consecutive_ready += 1
                self._state.last_error = f"http {resp.status_code}"
                self._state.state = "ready"
                self._state.last_ready = self._state.last_check
                return True
            except Exception as e:  # noqa: BLE001 — any network error is "not ready"
                was_ready = self._state.state == "ready"
                self._state.consecutive_ready = 0
                self._state.consecutive_failures += 1
                self._state.last_error = str(e)[:240]
                if self._state.consecutive_failures >= self.UNREACHABLE_AFTER_FAILURES:
                    self._state.state = "unreachable"
                elif (
                    was_ready
                    and self._state.consecutive_failures < self.FAILURES_BEFORE_LEAVING_READY
                ):
                    # Stay "ready" through a single transient timeout. Stops
                    # the UI from flapping amber on every passing network blip.
                    self._state.state = "ready"
                else:
                    self._state.state = "waiting"
                if self._state.consecutive_failures in (1, 5, 30):
                    logger.info(
                        "docker_readiness_waiting",
                        url=self._health_url,
                        consecutive_failures=self._state.consecutive_failures,
                        error=self._state.last_error,
                    )
                return False

    async def _probe_loop(self) -> None:
        delay = self.INITIAL_DELAY_S
        logger.info("docker_readiness_probe_started", url=self._health_url)
        while not self._stop.is_set():
            ok = await self._probe_once()
            if ok:
                # Stay in ready state with a generous re-check interval; if
                # Docker dies later we want to notice within ~30 s, not days.
                delay = self.MAX_DELAY_S / 2
            else:
                delay = min(delay * self.BACKOFF_FACTOR, self.MAX_DELAY_S)
            self._state.next_probe_in_s = delay
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        logger.info("docker_readiness_probe_stopped")


_singleton: DockerReadiness | None = None


def get_docker_readiness() -> DockerReadiness | None:
    return _singleton


def init_docker_readiness(backend_url: str) -> DockerReadiness:
    global _singleton
    if _singleton is None:
        _singleton = DockerReadiness(backend_url)
    return _singleton
