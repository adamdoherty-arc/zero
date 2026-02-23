"""
Email API endpoints for Gmail integration.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from typing import List, Optional, Dict, Any
import structlog

from pydantic import BaseModel, Field
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
    return await service.get_sync_status()


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


# ============================================================================
# Email Automation Endpoints
# ============================================================================

@router.get("/automation/status")
async def get_automation_status():
    """Get email automation status and statistics."""
    from app.infrastructure.config import get_settings
    from app.services.email_qa_service import get_email_qa_service
    
    settings = get_settings()
    qa_service = get_email_qa_service()
    
    pending_questions = qa_service.get_pending_questions()
    
    return {
        "enabled": settings.email_automation_enabled,
        "check_interval": settings.email_automation_check_interval,
        "confidence_threshold": settings.email_automation_confidence_threshold,
        "pending_questions": len(pending_questions),
        "model": settings.email_classifier_model
    }


@router.get("/questions/pending")
async def get_pending_questions():
    """Get all pending email automation questions."""
    from app.services.email_qa_service import get_email_qa_service
    
    qa_service = get_email_qa_service()
    questions = qa_service.get_pending_questions()
    
    return {
        "questions": [
            {
                "id": q.id,
                "email_id": q.email_id,
                "email_subject": q.email_subject,
                "email_from": q.email_from,
                "question": q.question,
                "options": q.options,
                "context": q.context,
                "created_at": q.created_at.isoformat(),
                "expires_at": q.expires_at.isoformat()
            }
            for q in questions
        ]
    }


@router.get("/questions/{question_id}")
async def get_question(question_id: str):
    """Get specific question details."""
    from app.services.email_qa_service import get_email_qa_service
    
    qa_service = get_email_qa_service()
    question = qa_service.get_question(question_id)
    
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    return {
        "id": question.id,
        "email_id": question.email_id,
        "email_subject": question.email_subject,
        "email_from": question.email_from,
        "question": question.question,
        "options": question.options,
        "context": question.context,
        "created_at": question.created_at.isoformat(),
        "expires_at": question.expires_at.isoformat(),
        "answered": question.answered,
        "answer": question.answer
    }


from pydantic import BaseModel

class QuestionAnswer(BaseModel):
    answer: str
    create_rule: bool = False


@router.post("/questions/{question_id}/answer")
async def answer_question(question_id: str, answer: QuestionAnswer):
    """Answer a pending question."""
    from app.services.email_qa_service import get_email_qa_service
    
    qa_service = get_email_qa_service()
    question = qa_service.answer_question(
        question_id=question_id,
        answer=answer.answer,
        create_rule=answer.create_rule
    )
    
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    logger.info(
        "email_question_answered_via_api",
        question_id=question_id,
        answer=answer.answer,
        create_rule=answer.create_rule
    )
    
    return {
        "status": "answered",
        "question_id": question.id,
        "answer": answer.answer,
        "rule_created": answer.create_rule
    }


@router.post("/automation/process")
async def process_new_emails():
    """Manually trigger email automation for new emails."""
    from app.infrastructure.config import get_settings
    from app.services.email_automation_service import get_email_automation_service
    
    settings = get_settings()
    
    if not settings.email_automation_enabled:
        raise HTTPException(
            status_code=400,
            detail="Email automation is disabled in configuration"
        )
    
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(
            status_code=401,
            detail="Gmail not connected. Complete OAuth flow first."
        )
    
    automation_service = get_email_automation_service()
    
    try:
        result = await automation_service.process_new_emails()
        return result
    except Exception as e:
        logger.error("email_automation_processing_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Automation processing failed: {str(e)}"
        )


@router.post("/automation/process/{email_id}")
async def process_single_email(email_id: str):
    """Manually trigger automation for a specific email."""
    from app.infrastructure.config import get_settings
    from app.services.email_automation_service import get_email_automation_service
    
    settings = get_settings()
    
    if not settings.email_automation_enabled:
        raise HTTPException(
            status_code=400,
            detail="Email automation is disabled in configuration"
        )
    
    automation_service = get_email_automation_service()
    
    try:
        result = await automation_service.process_email(email_id)
        return result
    except Exception as e:
        logger.error("email_automation_processing_failed", email_id=email_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Automation processing failed: {str(e)}"
        )


@router.get("/automation/history")
async def get_automation_history(limit: int = Query(default=50, ge=1, le=500)):
    """Get automation action history."""
    from app.services.email_automation_service import get_email_automation_service
    
    automation_service = get_email_automation_service()
    history = automation_service.get_history(limit=limit)
    
    return {"history": history, "count": len(history)}


@router.post("/automation/undo/{email_id}")
async def undo_automation_action(email_id: str):
    """Undo the most recent automation action on an email."""
    from app.services.email_automation_service import get_email_automation_service
    
    oauth_service = get_gmail_oauth_service()
    if not oauth_service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Gmail not connected")
    
    automation_service = get_email_automation_service()
    
    try:
        result = await automation_service.undo_action(email_id)
        
        if result["status"] ==  "error":
            raise HTTPException(status_code=400, detail=result["message"])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("undo_action_failed", email_id=email_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class JunkSenderRequest(BaseModel):
    sender_email: str


@router.post("/automation/junk/add")
async def add_junk_sender(request: JunkSenderRequest):
    """Mark a sender as junk."""
    from app.services.email_automation_service import get_email_automation_service
    
    automation_service = get_email_automation_service()
    result = automation_service.mark_as_junk(request.sender_email)
    
    return result


@router.post("/automation/junk/remove")
async def remove_junk_sender(request: JunkSenderRequest):
    """Remove a sender from junk list."""
    from app.services.email_automation_service import get_email_automation_service
    
    automation_service = get_email_automation_service()
    result = automation_service.remove_from_junk(request.sender_email)
    
    return result


@router.get("/automation/junk/list")
async def list_junk_senders():
    """Get list of junk senders."""
    from app.services.email_automation_service import get_email_automation_service

    automation_service = get_email_automation_service()
    rules = automation_service._load_automation_rules()

    return {"junk_senders": rules.get("junk_senders", [])}


# ============================================================================
# Email Rules Endpoints
# ============================================================================

from app.models.email_rule import (
    EmailRule as EmailRuleModel_,
    EmailRuleCreate,
    EmailRuleUpdate,
    RuleTestRequest,
    RuleTestResult,
)


@router.get("/rules", response_model=List[EmailRuleModel_])
async def list_rules(enabled_only: bool = Query(default=False)):
    """List all email rules ordered by priority."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    return await service.list_rules(enabled_only=enabled_only)


@router.post("/rules", response_model=EmailRuleModel_)
async def create_rule(data: EmailRuleCreate):
    """Create a new email rule."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    return await service.create_rule(data)


class RuleGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=5, max_length=500)


@router.post("/rules/generate", response_model=EmailRuleCreate)
async def generate_rule(request: RuleGenerateRequest):
    """Generate an email rule from a natural language description using LLM."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    try:
        return await service.generate_rule_from_prompt(request.prompt)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("rule_generation_failed", prompt=request.prompt[:100], error=str(e))
        raise HTTPException(status_code=500, detail=f"Rule generation failed: {str(e)}")


@router.get("/rules/{rule_id}", response_model=EmailRuleModel_)
async def get_rule(rule_id: str):
    """Get a single email rule."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    rule = await service.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/rules/{rule_id}", response_model=EmailRuleModel_)
async def update_rule(rule_id: str, data: EmailRuleUpdate):
    """Update an existing email rule."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    rule = await service.update_rule(rule_id, data)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str):
    """Delete an email rule."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    deleted = await service.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted", "rule_id": rule_id}


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, enabled: bool = Query(...)):
    """Enable or disable a rule."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    rule = await service.toggle_rule(rule_id, enabled)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "toggled", "rule_id": rule_id, "enabled": enabled}


@router.post("/rules/test", response_model=RuleTestResult)
async def test_rule(request: RuleTestRequest):
    """Test a rule against an email without executing actions."""
    from app.services.email_rule_service import get_email_rule_service
    service = get_email_rule_service()
    try:
        return await service.test_rule(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


