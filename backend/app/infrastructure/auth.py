"""
Authentication for ZERO API.

Single-user API key authentication using the ZERO_GATEWAY_TOKEN.
Used as a FastAPI dependency on all protected routes.
"""

import os
import secrets
import time as _time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_api_token() -> str:
    """Get the API token from environment."""
    return os.getenv("ZERO_GATEWAY_TOKEN", "")


def _check_token(token: str) -> bool:
    """Check token against current and grace-period old token."""
    current = _get_api_token()
    if not current:
        return False

    if secrets.compare_digest(token, current):
        return True

    # During rotation, accept old token within grace period
    old_token = os.getenv("ZERO_OLD_TOKEN", "")
    grace_until = os.getenv("ZERO_TOKEN_GRACE_UNTIL", "0")
    if old_token and _time.time() < float(grace_until):
        if secrets.compare_digest(token, old_token):
            return True

    return False


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency that enforces Bearer token authentication.

    Usage:
        @router.get("/endpoint")
        async def my_endpoint(token: str = Depends(require_auth)):
            ...
    """
    expected_token = _get_api_token()

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not configured",
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _check_token(credentials.credentials):
        logger.warning("auth_rejected", path=request.url.path, method=request.method)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials
