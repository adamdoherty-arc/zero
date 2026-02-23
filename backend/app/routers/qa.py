"""
QA Verification API endpoints.

POST /api/qa/verify       — Trigger async QA (returns immediately)
POST /api/qa/verify/sync  — Trigger sync QA (waits for results)
GET  /api/qa/latest       — Latest report
GET  /api/qa/history      — Report history
GET  /api/qa/status       — Quick status summary
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
import structlog

from app.services.qa_verification_service import get_qa_verification_service

router = APIRouter()
logger = structlog.get_logger()


@router.post("/verify")
async def trigger_verification(
    background_tasks: BackgroundTasks,
    auto_create_tasks: bool = Query(True, description="Auto-create Legion tasks for failures"),
):
    """Trigger full QA verification in the background."""
    service = get_qa_verification_service()

    if service._running:
        return {"status": "already_running", "message": "QA verification is already in progress"}

    background_tasks.add_task(
        service.run_full_verification,
        trigger="manual",
        auto_create_tasks=auto_create_tasks,
    )
    return {"status": "started", "message": "QA verification running in background"}


@router.post("/verify/sync")
async def trigger_verification_sync(
    auto_create_tasks: bool = Query(True, description="Auto-create Legion tasks for failures"),
):
    """Trigger QA verification and wait for the full report."""
    service = get_qa_verification_service()
    report = await service.run_full_verification(
        trigger="manual",
        auto_create_tasks=auto_create_tasks,
    )
    return report


@router.get("/latest")
async def get_latest_report():
    """Get the most recent QA report."""
    service = get_qa_verification_service()
    report = await service.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No QA reports found. Run a verification first.")
    return report


@router.get("/history")
async def get_report_history(limit: int = Query(20, ge=1, le=100)):
    """Get recent QA reports."""
    service = get_qa_verification_service()
    reports = await service.get_report_history(limit=limit)
    return {"reports": reports, "count": len(reports)}


@router.get("/status")
async def get_qa_status():
    """Get lightweight QA status summary for quick polling."""
    service = get_qa_verification_service()
    return await service.get_status_summary()
