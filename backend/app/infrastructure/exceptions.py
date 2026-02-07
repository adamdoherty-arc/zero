"""
Global exception handling for ZERO API.

Provides structured JSON error responses for all exception types,
preventing stack traces from leaking to clients.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class ZeroException(Exception):
    """Base exception for Zero application errors."""
    def __init__(self, message: str, status_code: int = 500, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ServiceUnavailableError(ZeroException):
    """Raised when an external service dependency is unavailable."""
    def __init__(self, service: str, message: str = None):
        super().__init__(
            message=message or f"Service '{service}' is unavailable",
            status_code=503,
            details={"service": service}
        )


class CircuitOpenError(ZeroException):
    """Raised when a circuit breaker is open."""
    def __init__(self, circuit_name: str):
        super().__init__(
            message=f"Circuit breaker '{circuit_name}' is open — service temporarily unavailable",
            status_code=503,
            details={"circuit": circuit_name}
        )


async def _zero_exception_handler(request: Request, exc: ZeroException) -> JSONResponse:
    """Handle Zero application exceptions."""
    error_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")

    logger.warning(
        "zero_exception",
        error_id=error_id,
        error_type=type(exc).__name__,
        message=exc.message,
        path=request.url.path,
        method=request.method,
        details=exc.details,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": type(exc).__name__,
                "error_id": error_id,
                "details": exc.details,
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    error_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")

    logger.error(
        "unhandled_exception",
        error_id=error_id,
        error_type=type(exc).__name__,
        error_message=str(exc),
        path=request.url.path,
        method=request.method,
        exc_info=exc,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "message": "Internal server error",
                "type": "InternalServerError",
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors with structured detail."""
    logger.warning(
        "validation_error",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "message": "Validation error",
                "type": "ValidationError",
                "details": exc.errors(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle HTTP exceptions with consistent format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "type": "HTTPException",
                "status_code": exc.status_code,
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


def register_exception_handlers(app: FastAPI):
    """Register all exception handlers with the FastAPI app."""
    app.add_exception_handler(ZeroException, _zero_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _global_exception_handler)
    logger.info("exception_handlers_registered")
