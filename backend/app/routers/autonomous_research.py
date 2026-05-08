"""
Autonomous Research Loop Router.
Status + manual kick for the 24/7 background research driver.
"""

from fastapi import APIRouter, Depends

from app.infrastructure.auth import require_auth
from app.services.autonomous_research_loop_service import get_autonomous_research_loop

router = APIRouter(
    prefix="/api/research/autonomous",
    tags=["autonomous-research"],
    dependencies=[Depends(require_auth)],
)


@router.get("/status")
async def status():
    """Return current loop state: enabled flag, concurrency, budget, in-flight, active topics, vault availability."""
    svc = get_autonomous_research_loop()
    return await svc.status()


@router.post("/tick")
async def tick():
    """Run one loop tick on demand. Honors the same concurrency + budget gates as the scheduler."""
    svc = get_autonomous_research_loop()
    return await svc.tick()
