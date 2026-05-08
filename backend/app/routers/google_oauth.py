"""
Unified Google OAuth router for Gmail and Calendar.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from typing import Dict, Any
import structlog

from app.services.gmail_oauth_service import get_gmail_oauth_service
from app.infrastructure.config import get_settings

router = APIRouter()
logger = structlog.get_logger()


@router.get("/auth/status")
async def get_auth_status():
    """Aggregate connection status across all connected Google accounts.

    Reports `connected=True` if at least one account has valid tokens.
    `accounts` lists every connected identity for the multi-account UI.
    """
    oauth_service = get_gmail_oauth_service()
    accounts = await oauth_service.list_accounts()

    has_any = False
    primary_email = None
    for acct in accounts:
        if await oauth_service.has_valid_tokens(account_id=acct["id"]):
            has_any = True
            if acct.get("is_default") or primary_email is None:
                primary_email = acct["email"]

    return {
        "connected": has_any,
        "email_address": primary_email,
        "services": {"gmail": has_any, "calendar": has_any},
        "accounts": accounts,
    }


@router.get("/auth/start")
async def auth_start(label: str = Query(default="personal", description="Account label: personal, work, etc.")):
    """Start Google OAuth flow. `label` is recorded against the new account
    so the user can distinguish personal vs work after callback."""
    oauth_service = get_gmail_oauth_service()

    if not oauth_service.has_client_config():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth not configured. Check server environment variables."
        )

    try:
        result = oauth_service.get_auth_url(label=label)
        return RedirectResponse(url=result["auth_url"])
    except Exception as e:
        logger.error("failed_to_generate_auth_url", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate auth URL: {str(e)}"
        )


@router.get("/auth/url")
async def get_auth_url(label: str = Query(default="personal")):
    """Get Google OAuth authorization URL as JSON (for programmatic use)."""
    oauth_service = get_gmail_oauth_service()

    if not oauth_service.has_client_config():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth not configured. Check server environment variables."
        )

    try:
        result = oauth_service.get_auth_url(label=label)
        return result
    except Exception as e:
        logger.error("failed_to_generate_auth_url", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate auth URL: {str(e)}"
        )


@router.get("/auth/callback")
async def auth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state for CSRF protection")
):
    """
    Handle OAuth callback from Google.
    
    This endpoint receives the authorization code and exchanges it for tokens.
    Redirects user back to frontend after successful authentication.
    """
    oauth_service = get_gmail_oauth_service()
    settings = get_settings()
    
    try:
        result = await oauth_service.handle_callback(code, state)
        email = result.get("email_address", "unknown")

        logger.info("google_oauth_complete", email=email)

        # Reset Gmail circuit breaker and clear sync errors after successful re-auth
        try:
            from app.infrastructure.circuit_breaker import get_circuit_breaker
            from app.infrastructure.database import get_session
            from app.db.models import SyncStatusModel

            breaker = get_circuit_breaker("gmail", failure_threshold=3, recovery_timeout=60.0)
            await breaker.reset()

            async with get_session() as session:
                for svc in ["gmail", "calendar"]:
                    row = await session.get(SyncStatusModel, svc)
                    if row:
                        row.errors = []
                        row.connected = True
                        await session.merge(row)

            logger.info("gmail_circuit_breaker_reset_after_reauth")
        except Exception as reset_err:
            logger.warning("post_reauth_reset_failed", error=str(reset_err))

        # Redirect to frontend with success status
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?tab=integrations&status=connected&email={email}"
        )
        
    except ValueError as e:
        logger.error("google_oauth_callback_invalid", error=str(e))
        # Redirect to frontend with error
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?tab=integrations&status=error&message={str(e)}"
        )
    except Exception as e:
        logger.error("google_oauth_callback_failed", error=str(e))
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?tab=integrations&status=error&message=Authentication failed"
        )


@router.post("/auth/disconnect")
async def disconnect():
    """
    Disconnect Google account.
    
    Revokes OAuth tokens and removes local credentials.
    """
    oauth_service = get_gmail_oauth_service()
    
    try:
        await oauth_service.disconnect()
        return {
            "status": "disconnected",
            "message": "Google account disconnected successfully"
        }
    except Exception as e:
        logger.error("google_disconnect_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect account"
        )
