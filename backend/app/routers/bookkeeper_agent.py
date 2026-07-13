"""Bookkeeper agent API — onboarding seed, manual sweep, status.

The agent itself runs daily via the scheduler; these endpoints let the UI (and
Adam) trigger or inspect it on demand. Questions surface in /company/inbox via
the existing operator questions API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.infrastructure.auth import require_auth
from app.services.bookkeeper_agent_service import get_bookkeeper_agent_service

router = APIRouter(
    prefix="/api/company/bookkeeper",
    tags=["bookkeeper-agent"],
    dependencies=[Depends(require_auth)],
)


@router.post("/onboarding/seed")
async def seed_onboarding():
    """Seed the onboarding interview for every tracker gap. Idempotent."""
    return await get_bookkeeper_agent_service().seed_onboarding_questions()


@router.post("/sweep")
async def run_sweep():
    """Run the daily gap sweep now (auto-fixes drafts, files nags)."""
    return await get_bookkeeper_agent_service().daily_sweep(requested_by="dashboard")


@router.get("/status")
async def agent_status():
    """Last sweep report + last health grade + nag cooldown state."""
    return get_bookkeeper_agent_service().status()


@router.get("/health")
async def books_health():
    """Deterministic books-health grade (0-100 + dimensions), computed now."""
    return await get_bookkeeper_agent_service().books_health()


@router.post("/health/run")
async def run_health():
    """Full weekly health run now: grade + narrative + Legion report + facts mirror."""
    return await get_bookkeeper_agent_service().weekly_health_run(requested_by="dashboard")
