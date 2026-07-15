"""Fix-144 — circuit breaker exempts client-side errors from tripping the shared breaker.

Found by supervise run bba59892 (2026-07-15), act-with-approval / delegation domain.

The shared "legion" CircuitBreaker (failure_threshold=5) counted EVERY exception
raised by the wrapped call — including ``LegionAPIError``, which ``legion_client``
raises ONLY for client/routing errors (any 4xx and a non-GET 404, per Fix-140).
Net effect: a burst of stale-ID moves or bad payloads (e.g. a Legion/Zero
ID-drift event) trips the shared breaker, and then every OTHER Legion call —
healthy GET reads included — fails with ``CircuitBreakerError`` for 30s even
though Legion itself is up. Textbook circuit-breaker anti-pattern: client errors
(the caller's fault) must not be counted as downstream unhealth.

Fix: ``CircuitBreaker`` gains an ``ignore_exceptions`` exclude-list; those
exceptions re-raise WITHOUT counting toward the failure threshold.
``legion_client`` marks ``LegionAPIError`` exempt. ``LegionConnectionError``
(5xx exhausted / connection failure) still counts and opens the breaker.
"""

import pytest

from app.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerError,
    get_circuit_breaker,
    _registry,
)


class ClientError(Exception):
    """Stand-in for a 4xx client error (the LegionAPIError class)."""


class ServiceError(Exception):
    """Stand-in for a genuine service-down failure (the LegionConnectionError class)."""


async def _raise(exc):
    raise exc


async def _ok():
    return "ok"


async def test_ignored_exception_does_not_open_breaker():
    """N client errors (N >> threshold) never open the breaker."""
    cb = CircuitBreaker("t144_ignore_1", failure_threshold=3, ignore_exceptions=(ClientError,))
    for _ in range(10):
        with pytest.raises(ClientError):
            await cb.call(_raise, ClientError("400 bad payload"))
    assert cb.state == CircuitState.CLOSED
    assert cb.stats.consecutive_failures == 0
    assert cb.stats.total_failures == 0


async def test_service_error_still_opens_breaker():
    """Genuine service failures still open the breaker at threshold."""
    cb = CircuitBreaker("t144_ignore_2", failure_threshold=3, ignore_exceptions=(ClientError,))
    for _ in range(3):
        with pytest.raises(ServiceError):
            await cb.call(_raise, ServiceError("503 down"))
    assert cb.state == CircuitState.OPEN
    # subsequent call short-circuits without ever invoking fn
    with pytest.raises(CircuitBreakerError):
        await cb.call(_raise, ServiceError("still down"))


async def test_client_errors_do_not_contribute_to_service_threshold():
    """Interleaved client errors must not push a below-threshold service count over the edge."""
    cb = CircuitBreaker("t144_ignore_3", failure_threshold=3, ignore_exceptions=(ClientError,))
    for _ in range(2):  # 2 service errors, below threshold=3
        with pytest.raises(ServiceError):
            await cb.call(_raise, ServiceError("5xx"))
    assert cb.stats.consecutive_failures == 2
    for _ in range(5):  # a flood of client errors must NOT advance the counter
        with pytest.raises(ClientError):
            await cb.call(_raise, ClientError("4xx"))
    assert cb.state == CircuitState.CLOSED
    assert cb.stats.consecutive_failures == 2


async def test_ignored_exception_is_neutral_on_stats():
    """A client error is a pass-through: neither a failure nor a success."""
    cb = CircuitBreaker("t144_ignore_4", failure_threshold=3, ignore_exceptions=(ClientError,))
    with pytest.raises(ClientError):
        await cb.call(_raise, ClientError("4xx"))
    assert cb.stats.total_successes == 0
    assert cb.stats.total_failures == 0


async def test_success_resets_service_failures_client_errors_neutral():
    cb = CircuitBreaker("t144_ignore_5", failure_threshold=3, ignore_exceptions=(ClientError,))
    with pytest.raises(ServiceError):
        await cb.call(_raise, ServiceError("5xx"))
    assert cb.stats.consecutive_failures == 1
    with pytest.raises(ClientError):  # neutral — count untouched
        await cb.call(_raise, ClientError("4xx"))
    assert cb.stats.consecutive_failures == 1
    assert await cb.call(_ok) == "ok"  # real success clears it
    assert cb.stats.consecutive_failures == 0


async def test_default_breaker_is_backward_compatible():
    """No ignore_exceptions -> every exception counts (prior behaviour preserved)."""
    cb = CircuitBreaker("t144_ignore_6", failure_threshold=2)
    for _ in range(2):
        with pytest.raises(ClientError):
            await cb.call(_raise, ClientError("4xx"))
    assert cb.state == CircuitState.OPEN  # legacy behaviour unchanged


def test_get_circuit_breaker_updates_ignore_on_existing_instance():
    """Singleton-ordering safety: a later caller's exempt set applies to an existing breaker."""
    name = "t144_registry"
    _registry.pop(name, None)
    first = get_circuit_breaker(name, failure_threshold=5)  # created without exemptions
    assert first.ignore_exceptions == ()
    second = get_circuit_breaker(name, ignore_exceptions=(ClientError,))
    assert second is first  # same singleton
    assert first.ignore_exceptions == (ClientError,)  # now current
    _registry.pop(name, None)


async def test_legion_client_marks_legion_api_error_exempt():
    """Integration: the real 'legion' breaker exempts LegionAPIError, not LegionConnectionError."""
    from app.services.legion_client import (
        LegionAPIError,
        LegionConnectionError,
        LegionClient,
    )
    _registry.pop("legion", None)
    LegionClient()  # __init__ registers the 'legion' breaker with the exempt set
    cb = _registry["legion"]
    assert LegionAPIError in cb.ignore_exceptions
    for _ in range(10):  # client/routing errors never open it
        with pytest.raises(LegionAPIError):
            await cb.call(_raise, LegionAPIError("404 stale id"))
    assert cb.state == CircuitState.CLOSED
    for _ in range(5):  # genuine service-down opens it at threshold 5
        with pytest.raises(LegionConnectionError):
            await cb.call(_raise, LegionConnectionError("connection refused"))
    assert cb.state == CircuitState.OPEN
    _registry.pop("legion", None)
