"""
Deep Research Router.
REST API for starting and viewing deep research reports.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.infrastructure.auth import require_auth
from app.models.agent_company import DeepResearchReport, DeepResearchRequest
from app.services.deep_research_service import get_deep_research_service

router = APIRouter(prefix="/api/research/deep", tags=["deep-research"], dependencies=[Depends(require_auth)])


@router.post("", response_model=DeepResearchReport, status_code=201)
async def start_research(req: DeepResearchRequest):
    """Start a deep research pipeline. Returns immediately; pipeline runs in background."""
    svc = get_deep_research_service()
    return await svc.start_research(req)


@router.get("", response_model=list[DeepResearchReport])
async def list_reports(status: Optional[str] = None, limit: int = 20):
    svc = get_deep_research_service()
    return await svc.list_reports(status=status, limit=limit)


@router.get("/{report_id}", response_model=DeepResearchReport)
async def get_report(report_id: str):
    svc = get_deep_research_service()
    report = await svc.get_report(report_id)
    if not report:
        raise HTTPException(404, f"Report {report_id} not found")
    return report
