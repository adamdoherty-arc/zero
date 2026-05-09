import pytest
from unittest import mock
from error_handlers import (
    TransientError, PermanentError, CircuitBreakerError,
    handle_service_errors, retry
)

def test_transient_error():
    with pytest.raises(TransientError):
        raise TransientError("Test transient error")

def test_permanent_error():
    with pytest.raises(PermanentError):
        raise PermanentError("Test permanent error")

def test_retry_success():
    call_count = 0
    
    @retry(max_attempts=3)
    def test_func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise TransientError("Transient")
        return "Success"
    
    assert test_func() == "Success"
    assert call_count == 2

def test_retry_failure():
    call_count = 0
    
    @retry(max_attempts=2)
    def test_func():
        nonlocal call_count
        call_count += 1
        raise TransientError("Transient")
    
    with pytest.raises(TransientError):
        test_func()
    assert call_count == 2

@mock.patch("time.time")
def test_circuit_breaker(mock_time):
    mock_time.side_effect = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1061]
    
    calls = []
    
    @handle_service_errors("test_service")
    def test_func():
        calls.append(1)
        raise TransientError("Test")
    
    # First 5 calls - should trip circuit breaker
    for _ in range(5):
        with pytest.raises(TransientError):
            test_func()
    
    # Circuit should be open
    with pytest.raises(CircuitBreakerError):
        test_func()
    
    # After reset timeout, should allow one call
    with pytest.raises(TransientError):
        test_func()
    assert len(calls) == 6  # 5 failures + 1 after reset

def test_circuit_breaker_success():
    calls = []
    
    @handle_service_errors("test_service")
    def test_func():
        calls.append(1)
        return "Success"
    
    assert test_func() == "Success"
    assert len(calls) == 1

def test_error_propagation():
    @handle_service_errors("test_service")
    def test_func():
        raise ValueError("Unexpected error")
    
    with pytest.raises(PermanentError) as exc_info:
        test_func()
    assert "ValueError" in str(exc_info.value)