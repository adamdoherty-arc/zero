"""Cross-domain focus recommendations API."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def what_should_i_focus_on():
    from app.services.cross_domain_service import get_cross_domain_service
    return await get_cross_domain_service().what_should_i_focus_on()


@router.get("/daily")
async def daily_synthesis():
    from app.services.cross_domain_service import get_cross_domain_service
    text = await get_cross_domain_service().daily_synthesis()
    return {"synthesis": text}


@router.post("/check-notifications")
async def trigger_proactive_check():
    from app.services.proactive_service import get_proactive_service
    return await get_proactive_service().check_and_notify()
