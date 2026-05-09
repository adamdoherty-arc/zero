import time
from functools import wraps
from typing import Optional, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)

class BaseServiceError(Exception):
    """Base class for all service-related exceptions"""
    def __init__(self, message: str, service_name: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.service_name = service_name
        self.status_code = status_code

class TransientError(BaseServiceError):
    """Errors that can be resolved with retry"""
    pass

class PermanentError(BaseServiceError):
    """Errors that require manual intervention"""
    pass

class CircuitBreakerError(BaseServiceError):
    """Error raised when circuit breaker is open"""
    pass

class CircuitBreaker:
    def __init__(self, max_failures: int = 5, reset_timeout: int = 60):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_reset = time.time()
        self.state = "closed"  # closed, open, half_open

    def record_success(self):
        if self.state == "closed":
            self.failure_count = 0
        elif self.state == "half_open":
            self.state = "closed"
            self.failure_count = 0
            self.last_reset = time.time()

    def record_failure(self):
        if self.state == "closed":
            self.failure_count += 1
            if self.failure_count >= self.max_failures:
                self.state = "open"
                self.last_reset = time.time()

    def can_call(self) -> bool:
        if self.state == "open":
            if time.time() - self.last_reset > self.reset_timeout:
                self.state = "half_open"
                return True
            return False
        return True

def retry(max_attempts: int = 3, delay: int = 1, backoff: int = 2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            current_delay = delay
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except TransientError as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        raise
                    logger.warning(f"Transient error in {func.__name__}: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator

def handle_service_errors(service_name: str):
    def decorator(func):
        breaker = CircuitBreaker()
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not breaker.can_call():
                raise CircuitBreakerError(
                    f"Circuit breaker open for {service_name}, service unavailable",
                    service_name
                )
            
            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except (TransientError, PermanentError) as e:
                if isinstance(e, TransientError):
                    logger.warning(f"Service {service_name} transient error: {e}")
                else:
                    logger.error(f"Service {service_name} permanent error: {e}")
                breaker.record_failure()
                raise
            except Exception as e:
                logger.exception(f"Unexpected error in {service_name}: {e}")
                breaker.record_failure()
                raise PermanentError(str(e), service_name) from e
        
        return wrapper
    return decorator