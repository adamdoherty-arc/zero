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
    """
    Get Google OAuth connection status.
    
    Returns whether user has connected their Google account
    and the email address if connected.
    """
    oauth_service = get_gmail_oauth_service()
    
    has_tokens = oauth_service.has_valid_tokens()
    email_address = None
    
    if has_tokens:
        try:
            creds = oauth_service.get_credentials()
            if creds:
                from googleapiclient.discovery import build
                service = build("gmail", "v1", credentials=creds)
                profile = service.users().getProfile(userId="me").execute()
                email_address = profile.get("emailAddress")
        except Exception as e:
            logger.warning("failed_to_get_email_address", error=str(e))
    
    return {
        "connected": has_tokens,
        "email_address": email_address,
        "services": {
            "gmail": has_tokens,
            "calendar": has_tokens
        }
    }


@router.get("/auth/url")
async def get_auth_url():
    """
    Get Google OAuth authorization URL.
    
    User should visit this URL to authorize ZERO to access
    their Gmail and Google Calendar.
    """
    oauth_service = get_gmail_oauth_service()
    
    if not oauth_service.has_client_config():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth not configured. Check server environment variables."
        )
    
    try:
        result = oauth_service.get_auth_url()
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
        result = oauth_service.handle_callback(code, state)
        email = result.get("email_address", "unknown")
        
        logger.info("google_oauth_complete", email=email)
        
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
        oauth_service.disconnect()
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
