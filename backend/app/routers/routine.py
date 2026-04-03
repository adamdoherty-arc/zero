"""Daily routine API."""
from fastapi import APIRouter

router = APIRouter()

@router.get("/morning")
async def morning_startup():
    from app.services.daily_routine_service import get_daily_routine_service
    return await get_daily_routine_service().morning_startup()

@router.get("/evening")
async def evening_review():
    from app.services.daily_routine_service import get_daily_routine_service
    return await get_daily_routine_service().end_of_day_review()

@router.get("/briefing")
async def get_briefing():
    from app.services.daily_routine_service import get_daily_routine_service
    text = await get_daily_routine_service().get_routine_briefing()
    return {"briefing": text}
