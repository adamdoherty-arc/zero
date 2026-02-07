"""
Email API endpoints for Gmail integration.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from typing import List, Optional, Dict, Any
import structlog

from app.models.email import (
    Email, EmailSummary, EmailLabel, EmailDigest,
    EmailCategory, EmailStatus, EmailSyncStatus, EmailToTaskRequest
)
from app.models.task import TaskCreate, TaskCategory, TaskPriority, TaskSource
from app.services.gmail_oauth_service import get_gmail_oauth_service
from app.services.gmail_service import get_gmail_service
from app.services.task_service import get_task_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================================================
# OAuth Endpoints
# ============================================================================

@router.get("/auth/url")
async def get_auth_url(
    redirect_uri: Optional[str] = Query(
        default=None,
        description="OAuth redirect URI (defaults to API callback)"
    )
):
    """
    Get Gmail OAuth authorization URL.

    User should visit this URL to authorize ZERO to access their Gmail.
    """
    oauth_service = get_gmail_oauth_service()

    if not oauth_service.has_client_config():
        raise HTTPException(
            status_code=400,
            detail="Gmail OAuth not configured. Set up client credentials first."
        )

    uri = redirect_uri or "http://localhost:18792/api/email/auth/callback"
    result = oauth_service.get_auth_url(uri)
    return result


@router.get("/auth/callback")
async def auth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state for CSRF protection")
):
    """
    Handle OAuth callback from Google.

    This endpoint receives the authorization code and exchanges it for tokens.
    """
    oauth_service = get_gmail_oauth_service()

    try:
        result = oauth_service.handle_callback(code, state)
        # Return HTML page that closes itself or redirects
        return {
            "status": "success",
            "message": "Gmail connected successfully",
            "email_address": result.get("email_address")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("gmail_auth_callback_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.post("/auth/config")
async def set_client_config(config: Dict[str, Any]):
    """
    Set Gmail OAuth client configuration.

    Upload the credentials.json downloaded from Google Cloud Console.
    This should be done once during initial setup.
    """
    oauth_service = get_gmail_oauth_service()

    if "installed" not in config and "web" not in config:
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials format. Expected Google OAuth credentials JSON."
        )

    oauth_service.set_client_config(config)
    return {"status": "configured", "message": "Gmail OAuth client configured"}


@router.post("/disconnect")
async def disconnect_gmail():
    """Disconnect Gmail account."""
    oauth_service = get_gmail_oauth_service()
    oauth_service.disconnect()
    return {"status": "disconnected", "message": "Gmail account disconnected"}


# ============================================================================
# Email Operations
# ============================================================================

@router.get("/status", response_model=EmailSyncStatus)
async def get_status():
    """Get email sync status."""
    service = get_gmail_service()
    return service.get_sync_status()


@router.post("/sync")
async def sync_inbox(
    max_results: int = Query(default=100, ge=10, le=500),
    days_back: int = Query(default=7, ge=1, le=30)
):
    """
    Sync inbox from Gmail.

    Fetches recent emails and caches them locally.
    """
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(
            status_code=401,
            detail="Gmail not connected. Complete OAuth flow first."
        )

    service = get_gmail_service()
    try:
        result = await service.sync_inbox(max_results, days_back)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("email_sync_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.get("/messages", response_model=List[EmailSummary])
async def list_emails(
    category: Optional[EmailCategory] = Query(default=None),
    status: Optional[EmailStatus] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    """List emails with optional filters."""
    service = get_gmail_service()
    return await service.list_emails(category, status, limit, offset)


@router.get("/messages/{email_id}", response_model=Email)
async def get_email(email_id: str):
    """Get full email by ID."""
    service = get_gmail_service()
    email = await service.get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


@router.post("/messages/{email_id}/read")
async def mark_as_read(email_id: str):
    """Mark email as read."""
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Gmail not connected")

    service = get_gmail_service()
    success = await service.mark_as_read(email_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to mark as read")
    return {"status": "success"}


@router.post("/messages/{email_id}/archive")
async def archive_email(email_id: str):
    """Archive email (remove from inbox)."""
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Gmail not connected")

    service = get_gmail_service()
    success = await service.archive_email(email_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to archive")
    return {"status": "success"}


@router.post("/messages/{email_id}/star")
async def star_email(
    email_id: str,
    starred: bool = Query(default=True)
):
    """Star or unstar an email."""
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Gmail not connected")

    service = get_gmail_service()
    success = await service.star_email(email_id, starred)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update star")
    return {"status": "success", "starred": starred}


@router.post("/messages/{email_id}/to-task")
async def convert_to_task(email_id: str, request: EmailToTaskRequest):
    """Convert email to a task."""
    gmail_service = get_gmail_service()
    task_service = get_task_service()

    email = await gmail_service.get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Determine priority based on category
    priority = TaskPriority.MEDIUM
    if request.priority:
        priority = TaskPriority(request.priority)
    elif email.category == EmailCategory.URGENT:
        priority = TaskPriority.HIGH
    elif email.category == EmailCategory.IMPORTANT:
        priority = TaskPriority.MEDIUM

    # Create task
    task_data = TaskCreate(
        title=f"[Email] {email.subject}",
        description=f"From: {email.from_address.email}\n\n{email.snippet}\n\n---\nEmail ID: {email.id}",
        sprint_id=request.sprint_id,
        project_id=request.project_id,
        category=TaskCategory(request.category) if request.category else TaskCategory.CHORE,
        priority=priority,
        source=TaskSource.MANUAL,
        source_reference=f"email:{email.id}"
    )

    task = await task_service.create_task(task_data)

    logger.info("email_converted_to_task", email_id=email.id, task_id=task.id)

    return {
        "status": "success",
        "task_id": task.id,
        "task_title": task.title
    }


@router.get("/labels", response_model=List[EmailLabel])
async def get_labels():
    """Get Gmail labels."""
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Gmail not connected")

    service = get_gmail_service()
    return await service.get_labels()


@router.get("/digest", response_model=EmailDigest)
async def get_digest():
    """Get email digest summary."""
    service = get_gmail_service()
    return await service.generate_digest()
