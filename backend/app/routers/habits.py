"""Habit tracking API."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class HabitCreate(BaseModel):
    name: str
    description: Optional[str] = None
    frequency: str = "daily"
    target_count: int = 1
    category: str = "general"

class HabitLog(BaseModel):
    note: Optional[str] = None

@router.post("/")
async def create_habit(req: HabitCreate):
    from app.services.habit_service import get_habit_service
    return await get_habit_service().create_habit(
        name=req.name, description=req.description,
        frequency=req.frequency, target_count=req.target_count, category=req.category,
    )

@router.get("/")
async def list_habits():
    from app.services.habit_service import get_habit_service
    return await get_habit_service().list_habits()

@router.post("/{habit_id}/log")
async def log_habit(habit_id: str, req: HabitLog = HabitLog()):
    from app.services.habit_service import get_habit_service
    return await get_habit_service().log_completion(habit_id, note=req.note)

@router.get("/today")
async def today_status():
    from app.services.habit_service import get_habit_service
    return await get_habit_service().get_today_status()
