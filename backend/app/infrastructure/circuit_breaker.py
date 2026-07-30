"""
Circuit breaker for external service calls.

Prevents cascading failures by short-circuiting calls to services
that are known to be down. Transitions through three states:

  CLOSED  -> calls pass through normally
  OPEN    -> calls immediately fail/use fallback (service is down)
  HALF_OPEN -> a limited number of probe calls pass through to test recovery

Usage:
    breaker = CircuitBreaker("legion", failure_threshold=5, recovery_timeout=30)
    result = await breaker.call(some_async_fn, arg1, arg2)
"""

import asyncio
import time
from enum import Enum
from typing import TypeVar, Callable, Optional, Any, Dict
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitStats:
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    total_fallbacks: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    state_changes: int = 0


class CircuitBreakerError(Exception):
    """Raised when circuit is open and no fallback is configured."""
    def __init__(self, name: str, state: CircuitState):
        self.name = name
        self.state = state
        super().__init__(f"Circuit breaker '{name}' is {state.value}")


class CircuitBreaker:
    """
    Async circuit breaker with configurable thresholds and optional fallback.

    Args:
        name: Identifier for this circuit (used in logging).
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout: Seconds to wait before transitioning OPEN -> HALF_OPEN.
        half_open_max_calls: Max probe calls allowed in HALF_OPEN state.
        fallback: Optional callable returning a default value when circuit is open.
        ignore_exceptions: Exception types that represent CLIENT-side errors
            (e.g. a 4xx / stale-ID 404 from the caller's own bad request) rather
            than downstream unhealth. These re-raise WITHOUT counting toward the
            failure threshold, so one buggy caller can't trip the shared breaker
            and DoS every other call. Default () preserves prior behaviour.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 2,
        fallback: Optional[Callable[[], Any]] = None,
        ignore_exceptions: tuple = (),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.fallback = fallback
        self.ignore_exceptions = ignore_exceptions

        self._state = CircuitState.CLOSED
        self._opened_at: Optional[float] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self.stats = CircuitStats()

    @property
    def state(self) -> CircuitState:
        """Current state, auto-transitioning OPEN -> HALF_OPEN after timeout."""
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and (time.monotonic() - self._opened_at) >= self.recovery_timeout
        ):
            self._transition(CircuitState.HALF_OPEN)
        return self._state

    def _transition(self, new_state: CircuitState):
        old = self._state
        self._state = new_state
        self.stats.state_changes += 1

        if new_state == CircuitState.OPEN:
            self._opened_at = time.monotonic()
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0

        logger.info(
            "circuit_breaker_transition",
            name=self.name,
            from_state=old.value,
            to_state=new_state.value,
        )

    async def call(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Execute fn through the circuit breaker.

        If the circuit is OPEN and a fallback is configured, return fallback().
        If OPEN with no fallback, raise CircuitBreakerError.
        """
        async with self._lock:
            current_state = self.state  # may auto-transition OPEN->HALF_OPEN

            if current_state == CircuitState.OPEN:
                self.stats.total_calls += 1
                if self.fallback is not None:
                    self.stats.total_fallbacks += 1
                    return self.fallback()
                raise CircuitBreakerError(self.name, current_state)

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    # Too many probe calls already in flight
                    if self.fallback is not None:
                        self.stats.total_calls += 1
                        self.stats.total_fallbacks += 1
                        return self.fallback()
                    raise CircuitBreakerError(self.name, current_state)
                self._half_open_calls += 1

        # Execute outside the lock so we don't block other callers
        self.stats.total_calls += 1
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)

            await self._on_success()
            return result
        except Exception as exc:
            # Client-side errors (a 4xx / stale-ID 404 caused by the caller's
            # own bad request) are NOT a signal that the downstream service is
            # unhealthy. Counting them toward the failure threshold lets one
            # buggy caller trip the shared breaker and DoS every OTHER call
            # (reads included) for recovery_timeout seconds. Re-raise them
            # without recording a failure; only genuine service failures
            # (5xx exhausted, timeouts, connection errors) open the circuit.
            if self.ignore_exceptions and isinstance(exc, self.ignore_exceptions):
                raise
            await self._on_failure()
            raise

    async def _on_success(self):
        async with self._lock:
            self.stats.total_successes += 1
            self.stats.last_success_time = time.monotonic()
            self.stats.consecutive_failures = 0

            if self._state == CircuitState.HALF_OPEN:
                # Probe succeeded — close the circuit
                self._transition(CircuitState.CLOSED)

    async def _on_failure(self):
        async with self._lock:
            self.stats.total_failures += 1
            self.stats.last_failure_time = time.monotonic()
            self.stats.consecutive_failures += 1

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — reopen
                self._transition(CircuitState.OPEN)
            elif self.stats.consecutive_failures >= self.failure_threshold:
                self._transition(CircuitState.OPEN)

    async def record_success(self):
        """Record a successful call made OUTSIDE of `call()`.

        Manual-mode counterpart to `call()`, for callers whose failure policy is
        richer than "any exception counts". `unified_llm_client` is the motivating
        case: whether an LLM failure is *transient* depends on both exception type
        and message text (429/502/503/504 arrive as message content), which the
        type-based `ignore_exceptions` tuple cannot express. Such callers drive the
        same state machine explicitly instead of forking it.
        """
        await self._on_success()

    async def record_failure(self):
        """Record a failed call made OUTSIDE of `call()`. See `record_success()`."""
        await self._on_failure()

    async def reset(self):
        """Manually reset the circuit breaker to CLOSED."""
        async with self._lock:
            self._transition(CircuitState.CLOSED)
            self.stats.consecutive_failures = 0

    def status(self) -> Dict[str, Any]:
        """Return a JSON-serialisable status dict."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "stats": {
                "total_calls": self.stats.total_calls,
                "total_failures": self.stats.total_failures,
                "total_successes": self.stats.total_successes,
                "total_fallbacks": self.stats.total_fallbacks,
                "consecutive_failures": self.stats.consecutive_failures,
                "state_changes": self.stats.state_changes,
            },
        }


# ============================================
# GLOBAL REGISTRY
# ============================================

_registry: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    fallback: Optional[Callable[[], Any]] = None,
    ignore_exceptions: tuple = (),
) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per name)."""
    if name not in _registry:
        _registry[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            fallback=fallback,
            ignore_exceptions=ignore_exceptions,
        )
    elif ignore_exceptions:
        # The breaker is a singleton per name, so its config is fixed by
        # whichever call site created it first. If a later caller supplies an
        # exempt set (e.g. legion_client marking LegionAPIError), keep it
        # current so singleton-creation ordering can't silently drop it.
        _registry[name].ignore_exceptions = ignore_exceptions
    return _registry[name]


def all_circuit_breakers() -> Dict[str, CircuitBreaker]:
    """Return all registered circuit breakers."""
    return dict(_registry)
